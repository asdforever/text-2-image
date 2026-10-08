from contextlib import asynccontextmanager
import logging
from pathlib import Path
from uuid import UUID

from fastapi import FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from minio import Minio

from .core.config import Settings, get_settings
from .generation_worker_health import MemoryWorkerHealth, PostgresWorkerHealth
from .core.context import request_id_or_new, request_id_var
from .core.http import (
    error_response,
    http_error_code,
    public_http_message,
    success_response,
)
from .core.identity import LocalSingleUserIdentityProvider
from .application.ports import MemoryIdempotencyStore, SystemClock
from .application.idempotency import PostgresIdempotencyStore
from .application.library_services import (
    SqlAlchemyAssetService,
    SqlAlchemyProductService,
    SqlAlchemyTestRunService,
)
from .application.suite_service import SuiteService
from .application.project_service import ProjectService
from .core.errors import AppError
from .application.model_connection_service import ModelConnectionService
from .providers.configured_prompt_models import PromptModelResolver
from .model_connection_repository import MemoryModelConnectionRepository, PostgresModelConnectionRepository
from .providers.configured_image_editor import ConfiguredImageEditor
from .routes.model_connections import model_connection_router
from .repository import ImageRecord, InMemoryRepository
from .schemas import ResponseEnvelope, SuiteAggregate, SuiteCreate, SuiteOut
from .storage import MemoryObjectStorage
from .storage_minio import MinioObjectStorage
from .db import create_engine, create_session_factory
from .postgres_repository import PostgresRepository
from .prompt_repository import MemoryPromptRepository
from .prompt_sqlalchemy_repository import SqlAlchemyPromptRepository
from .prompt_service import PromptService
from .routes.prompts import prompt_router
from .routes.assets import asset_router
from .routes.products import product_router
from .routes.test_runs import test_run_router
from .routes.projects import project_router
from .minio_utils import AssetMinioStorage, MemoryAssetStorage
from .test_executor import TestExecutor
from .project_repository import InMemoryProjectRepository, PostgresProjectRepository
from .project_storage import MemoryProjectAssetStorage, MinioProjectAssetStorage
from .application.project_asset_service import ProjectAssetService
from .application.generation_config_service import GenerationConfigService
from .generation_config_repository import (
    InMemoryGenerationConfigRepository,
    PostgresGenerationConfigRepository,
)
from .routes.generation_config import generation_config_router
from .routes.hero_generations import hero_generation_router
from .routes.batch_generations import batch_generation_router
from .routes.suite_plans import suite_plan_router
from .routes.task_center import task_center_router
from .routes.workbench import workbench_router
from .routes.image_editing import image_editing_router
from .application.image_editing_service import ImageEditingService
from .application.image_editing_worker import ImageEditingWorker
from .application.canvas_generation_service import CanvasGenerationService
from .application.canvas_lineage import canvas_generation_steps, reverse_execution_steps
from .reverse_execution_batch_repository import MemoryReverseBatchRepository, PostgresReverseBatchRepository
from .canvas_generation_repository import MemoryCanvasGenerationRepository, PostgresCanvasGenerationRepository
from .routes.canvas_generations import canvas_generation_router
from .application.style_harmonization_service import StyleHarmonizationService
from .routes.style_harmonization import style_harmonization_router
from .application.long_image_service import LongImageService
from .routes.long_images import long_image_router
from .application.product_library_service import ProductLibraryService, SqlAlchemyProductLibraryService
from .application.project_archive_service import ProjectArchiveCoordinator
from .routes.product_library import router as product_library_router
from .image_editing_repository import (
    InMemoryImageEditingRepository,
    PostgresImageEditingRepository,
)
from .workbench_repository import InMemoryWorkbenchRepository, PostgresWorkbenchRepository
from .application.workbench_service import WorkbenchService
from .hero_generation_repository import (
    InMemoryHeroGenerationRepository,
    PostgresHeroGenerationRepository,
)
from .application.hero_generation_service import HeroGenerationService
from .application.batch_generation_service import BatchHeroPromptCompilationService
from .application.batch_generation_confirmation_service import BatchGenerationConfirmationService
from .application.suite_planning_confirmation_service import SuitePlanningConfirmationService
from .application.suite_planning_ports import EmptyPlanningReferenceResolver
from .application.suite_planning_service import SuitePlanningService
from .batch_generation_repository import InMemoryBatchGenerationRepository, PostgresBatchGenerationRepository
from .suite_planning_repository import (
    InMemorySuitePlanningRepository,
    PostgresSuitePlanningRepository,
)
from .providers.openai_compatible import (
    OpenAICompatibleImageEditor,
    OpenAICompatiblePromptCompiler,
    OpenAICompatibleSuitePlannerCompiler,
    OpenAICompatibleModulePlanner,
)
from .module_planning_repository import MemoryModulePlanningRepository, PostgresModulePlanningRepository
from .application.module_planning_service import ModulePlanningService
from .routes.module_plans import module_plan_router
from .routes.planning_conversations import planning_conversation_router
from .application.planning_conversation_service import PlanningConversationService
from .planning_conversation_repository import MemoryPlanningConversationRepository, PostgresPlanningConversationRepository
from .routes.reverse_projects import reverse_project_router
from .routes.reverse_execution import reverse_execution_router
from .reverse_project_repository import (
    InMemoryReverseProjectRepository,
    PostgresReverseProjectRepository,
)
from .application.reverse_project_service import ReverseProjectService
from .reverse_execution_repository import (
    InMemoryReverseExecutionRepository,
    PostgresReverseExecutionRepository,
)
from .application.reverse_execution_service import ReverseExecutionService
from .application.reverse_execution_generation_service import ReverseExecutionGenerationService
from .application.reverse_execution_parameters import ReverseExecutionParameterPlanner

logger = logging.getLogger("picagent")


def _suite_view(suite, request: Request) -> dict:
    return SuiteOut(id=suite.id, name=suite.name, status=suite.status, createdAt=suite.created_at, updatedAt=suite.updated_at).model_dump(mode="json")


def _image_view(image: ImageRecord, request: Request) -> dict:
    base = str(request.base_url).rstrip("/")
    return {"id": image.id, "suiteId": image.suite_id, "ordinal": image.ordinal, "sha256": image.sha256, "width": image.width, "height": image.height, "mimeType": image.mime_type, "originalFilename": image.filename, "createdAt": image.created_at, "originalPreviewUrl": f"{base}/api/suites/{image.suite_id}/input-images/{image.id}/preview/original", "thumbnailPreviewUrl": f"{base}/api/suites/{image.suite_id}/input-images/{image.id}/preview/thumbnail"}


def create_app(
    settings: Settings | None = None,
    repository=None,
    storage=None,
    prompt_repository=None,
    identity_provider=None,
    clock=None,
    idempotency_store=None,
    asset_service=None,
    product_service=None,
    test_run_service=None,
    project_repository=None,
    project_service=None,
    project_asset_storage=None,
    project_asset_service=None,
    product_library_service=None,
    project_archive=None,
    generation_config_repository=None,
    generation_config_service=None,
    hero_generation_repository=None,
    hero_generation_service=None,
    prompt_compiler=None,
    image_editor=None,
    batch_generation_repository=None,
    batch_generation_service=None,
    batch_generation_confirmation_service=None,
    suite_planning_repository=None,
    suite_planning_service=None,
    suite_planning_confirmation_service=None,
    planning_reference_resolver=None,
    suite_planner_compiler=None,
    module_planning_service=None,
    module_planning_repository=None,
    module_planner=None,
    workbench_repository=None,
    workbench_service=None,
    image_editing_repository=None,
    image_editing_service=None,
    reverse_project_repository=None,
    reverse_project_service=None,
    reverse_execution_repository=None,
    reverse_execution_service=None,
    reverse_execution_generation_service=None,
) -> FastAPI:
    cfg = settings or get_settings()
    cfg.validate_startup()
    repo = repository or InMemoryRepository()
    engine = None
    if repository is None and cfg.database_url:
        engine = create_engine(cfg.database_url)
        repo = PostgresRepository(create_session_factory(engine))
    object_storage = storage or MemoryObjectStorage()
    minio_client = None
    if storage is None and cfg.minio_endpoint and cfg.minio_access_key and cfg.minio_secret_key and cfg.minio_bucket:
        endpoint = cfg.minio_endpoint.removeprefix("http://").removeprefix("https://")
        minio_client = Minio(endpoint, access_key=cfg.minio_access_key, secret_key=cfg.minio_secret_key, secure=cfg.minio_endpoint.startswith("https://"))
        object_storage = MinioObjectStorage(minio_client, cfg.minio_bucket)

    session_factory = create_session_factory(engine) if engine is not None else None
    asset_storage = (
        AssetMinioStorage(minio_client, cfg.minio_bucket)
        if minio_client is not None and cfg.minio_bucket
        else MemoryAssetStorage()
    )
    resolved_project_asset_storage = project_asset_storage or (
        MinioProjectAssetStorage(minio_client, cfg.minio_bucket)
        if minio_client is not None and cfg.minio_bucket
        else MemoryProjectAssetStorage()
    )
    test_executor = None
    if (
        session_factory is not None
        and asset_storage is not None
    ):
        test_executor = TestExecutor(
            session_factory,
            asset_storage,
            api_base_url=cfg.image_generation_base_url or "",
            api_key=cfg.image_generation_api_key or "",
            model=cfg.image_generation_model,
        )
    resolved_asset_service = asset_service or (
        SqlAlchemyAssetService(session_factory, asset_storage)
        if session_factory is not None and asset_storage is not None
        else None
    )
    resolved_product_service = product_service or (
        SqlAlchemyProductService(session_factory, asset_storage)
        if session_factory is not None
        else None
    )
    resolved_test_run_service = test_run_service or (
        SqlAlchemyTestRunService(session_factory, asset_storage, test_executor)
        if session_factory is not None
        else None
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        # 启动时检查并创建 MinIO 桶
        if asset_storage is not None:
            await asset_storage.ensure_bucket_exists()

        yield
        if engine is not None:
            await engine.dispose()

    app = FastAPI(title=cfg.app_name, version="0.1.0", lifespan=lifespan)
    app.state.generation_worker_health = PostgresWorkerHealth(session_factory) if session_factory else MemoryWorkerHealth()
    resolved_identity_provider = identity_provider or LocalSingleUserIdentityProvider.from_settings(cfg)
    resolved_clock = clock or SystemClock()
    resolved_idempotency_store = idempotency_store or (
        PostgresIdempotencyStore(session_factory)
        if session_factory is not None
        else MemoryIdempotencyStore()
    )
    resolved_project_repository = project_repository or (
        PostgresProjectRepository(session_factory)
        if session_factory is not None
        else InMemoryProjectRepository()
    )
    resolved_product_library_service = product_library_service or (
        SqlAlchemyProductLibraryService(session_factory, resolved_identity_provider)
        if session_factory is not None
        else ProductLibraryService(resolved_identity_provider)
    )
    resolved_project_archive = project_archive or ProjectArchiveCoordinator(
        resolved_product_library_service
    )
    suite_service = SuiteService(
        repository=repo,
        storage=object_storage,
        clock=resolved_clock,
        identity_provider=resolved_identity_provider,
        idempotency_store=resolved_idempotency_store,
        max_upload_bytes=cfg.max_upload_bytes,
    )
    resolved_project_asset_service = project_asset_service or ProjectAssetService(
        resolved_project_repository,
        resolved_project_asset_storage,
        resolved_identity_provider,
        max_upload_bytes=cfg.max_upload_bytes,
        idempotency_store=resolved_idempotency_store,
        project_archive=resolved_project_archive,
    )
    resolved_project_service = project_service or ProjectService(
        resolved_project_repository,
        resolved_identity_provider,
        resolved_idempotency_store,
        project_archive=resolved_project_archive,
        project_assets=resolved_project_asset_service,
    )

    app.state.repository = repo; app.state.storage = object_storage; app.state.settings = cfg
    app.state.identity_provider = resolved_identity_provider
    app.state.idempotency_store = resolved_idempotency_store
    app.state.suite_service = suite_service
    app.state.project_repository = resolved_project_repository
    app.state.project_service = resolved_project_service
    app.state.project_asset_storage = resolved_project_asset_storage
    app.state.project_asset_service = resolved_project_asset_service
    app.state.project_archive = resolved_project_archive
    app.state.asset_storage = asset_storage
    app.state.test_executor = test_executor
    app.state.asset_service = resolved_asset_service
    app.state.product_service = resolved_product_service
    app.state.test_run_service = resolved_test_run_service
    # Setup database session factory for new APIs
    if engine is not None:
        app.state.db_session = session_factory
    else:
        # Set to None if no database configured
        app.state.db_session = None

    if prompt_repository is not None:
        prompt_repo = prompt_repository
    elif engine is not None:
        prompt_repo = SqlAlchemyPromptRepository(session_factory)
    else:
        prompt_repo = MemoryPromptRepository()
    prompt_service = PromptService(prompt_repo)
    app.state.prompt_service = prompt_service

    resolved_generation_config_repository = generation_config_repository or (
        PostgresGenerationConfigRepository(session_factory)
        if session_factory is not None
        else InMemoryGenerationConfigRepository()
    )
    resolved_generation_config_service = generation_config_service or GenerationConfigService(
        resolved_generation_config_repository,
        resolved_identity_provider,
        resolved_idempotency_store,
        resolved_clock,
        prompt_repository=prompt_repo,
    )
    app.state.generation_config_repository = resolved_generation_config_repository
    app.state.generation_config_service = resolved_generation_config_service
    model_connections = ModelConnectionService(
        PostgresModelConnectionRepository(session_factory) if session_factory is not None else MemoryModelConnectionRepository(),
        resolved_identity_provider, cfg, resolved_generation_config_service,
    )
    app.state.model_connection_service = model_connections
    prompt_models = PromptModelResolver(model_connections)
    resolved_generation_config_service.model_connections = model_connections
    if test_executor is not None:
        test_executor.model_connections = model_connections
    if test_run_service is None and resolved_test_run_service is not None:
        resolved_test_run_service.model_connections = model_connections
    # 注入假模型的自动化测试保持独立，不访问真实连接。
    generation_connections = model_connections if image_editor is None else None
    resolved_hero_generation_repository = hero_generation_repository or (
        PostgresHeroGenerationRepository(session_factory)
        if session_factory is not None
        else InMemoryHeroGenerationRepository()
    )
    resolved_prompt_compiler = prompt_compiler or OpenAICompatiblePromptCompiler(
        base_url=cfg.context_base_url,
        api_key=cfg.context_api_key,
        model=cfg.context_model,
        timeout_ms=cfg.context_timeout_ms,
    )
    resolved_image_editor = image_editor or ConfiguredImageEditor(
        model_connections,
        timeout_ms=cfg.image_generation_timeout_ms,
    )
    resolved_hero_generation_service = hero_generation_service or HeroGenerationService(
        project_repository=resolved_project_repository,
        project_storage=resolved_project_asset_storage,
        project_asset_service=resolved_project_asset_service,
        generation_config_service=resolved_generation_config_service,
        prompt_repository=prompt_repo,
        task_repository=resolved_hero_generation_repository,
        prompt_compiler=resolved_prompt_compiler,
        image_editor=resolved_image_editor,
        identity_provider=resolved_identity_provider,
        provider_model=cfg.image_generation_model,
        model_connections=generation_connections,
        prompt_models=prompt_models,
    )
    app.state.hero_generation_repository = resolved_hero_generation_repository
    app.state.hero_generation_service = resolved_hero_generation_service
    resolved_batch_generation_repository = batch_generation_repository or (
        PostgresBatchGenerationRepository(session_factory)
        if session_factory is not None
        else InMemoryBatchGenerationRepository()
    )
    resolved_batch_generation_service = batch_generation_service or BatchHeroPromptCompilationService(
        project_repository=resolved_project_repository,
        project_storage=resolved_project_asset_storage,
        generation_config_service=resolved_generation_config_service,
        prompt_repository=prompt_repo,
        batch_repository=resolved_batch_generation_repository,
        prompt_compiler=resolved_prompt_compiler,
        image_editor=resolved_image_editor,
        identity_provider=resolved_identity_provider,
        provider_model=cfg.image_generation_model,
        model_connections=generation_connections,
        prompt_models=prompt_models,
    )
    app.state.batch_generation_repository = resolved_batch_generation_repository
    app.state.batch_generation_service = resolved_batch_generation_service
    app.state.batch_generation_confirmation_service = (
        batch_generation_confirmation_service or BatchGenerationConfirmationService(
            resolved_batch_generation_repository, resolved_identity_provider
        )
    )
    resolved_suite_planning_repository = suite_planning_repository or (
        PostgresSuitePlanningRepository(session_factory)
        if session_factory is not None
        else InMemorySuitePlanningRepository()
    )
    resolved_suite_planner_compiler = suite_planner_compiler or OpenAICompatibleSuitePlannerCompiler(
        base_url=cfg.context_base_url,
        api_key=cfg.context_api_key,
        model=cfg.context_model,
        timeout_ms=cfg.context_timeout_ms,
    )
    resolved_suite_planning_service = suite_planning_service or SuitePlanningService(
        project_repository=resolved_project_repository,
        project_storage=resolved_project_asset_storage,
        generation_config_service=resolved_generation_config_service,
        prompt_repository=prompt_repo,
        plan_repository=resolved_suite_planning_repository,
        reference_resolver=planning_reference_resolver or EmptyPlanningReferenceResolver(),
        planner_compiler=resolved_suite_planner_compiler,
        identity_provider=resolved_identity_provider,
        provider_model=cfg.image_generation_model,
        model_connections=generation_connections,
        prompt_models=prompt_models,
    )
    app.state.suite_planning_repository = resolved_suite_planning_repository
    app.state.suite_planning_service = resolved_suite_planning_service
    resolved_module_repository = module_planning_repository or (PostgresModulePlanningRepository(session_factory) if session_factory is not None else MemoryModulePlanningRepository())
    resolved_module_planner = module_planner or OpenAICompatibleModulePlanner(
        base_url=cfg.context_base_url, api_key=cfg.context_api_key, model=cfg.context_model,
        timeout_ms=cfg.context_timeout_ms,
    )
    resolved_reverse_project_repository = reverse_project_repository or (
        PostgresReverseProjectRepository(session_factory)
        if session_factory is not None
        else InMemoryReverseProjectRepository()
    )
    resolved_reverse_project_service = reverse_project_service or ReverseProjectService(
        resolved_reverse_project_repository,
        resolved_identity_provider,
        storage=resolved_project_asset_storage,
        max_upload_bytes=cfg.max_upload_bytes,
        project_repository=resolved_project_repository,
        generation_config_service=resolved_generation_config_service,
        planner=resolved_module_planner,
        prompt_models=prompt_models,
    )
    app.state.reverse_project_repository = resolved_reverse_project_repository
    app.state.reverse_project_service = resolved_reverse_project_service
    reverse_parameter_planner = ReverseExecutionParameterPlanner(
        planner=resolved_module_planner,
        project_asset_service=resolved_project_asset_service,
        config_service=resolved_generation_config_service,
        prompt_models=prompt_models,
    )
    resolved_reverse_execution_repository = reverse_execution_repository or (
        PostgresReverseExecutionRepository(session_factory)
        if session_factory is not None
        else InMemoryReverseExecutionRepository()
    )
    resolved_reverse_execution_service = reverse_execution_service or ReverseExecutionService(
        resolved_reverse_execution_repository,
        resolved_identity_provider,
        resolved_project_repository,
        resolved_reverse_project_service,
        parameter_planner=reverse_parameter_planner,
    )
    reverse_batch_repository = (PostgresReverseBatchRepository(session_factory) if session_factory is not None else MemoryReverseBatchRepository())
    resolved_reverse_execution_generation_service = reverse_execution_generation_service or ReverseExecutionGenerationService(
        plan_service=resolved_reverse_execution_service,
        batch_repository=reverse_batch_repository,
        timeout_ms=cfg.image_generation_timeout_ms,
        repository=resolved_reverse_execution_repository,
        project_repository=resolved_project_repository,
        project_asset_service=resolved_project_asset_service,
        reverse_project_service=resolved_reverse_project_service,
        image_editor=resolved_image_editor,
        project_archive=resolved_project_archive,
        identity_provider=resolved_identity_provider,
        provider_model=cfg.image_generation_model,
        model_connections=model_connections,
    )
    app.state.reverse_execution_repository = resolved_reverse_execution_repository
    app.state.reverse_execution_service = resolved_reverse_execution_service
    app.state.reverse_execution_generation_service = resolved_reverse_execution_generation_service
    app.state.reverse_execution_batch_repository = reverse_batch_repository
    resolved_module_service = module_planning_service or ModulePlanningService(
        resolved_module_repository, resolved_project_repository, resolved_project_asset_storage,
        resolved_generation_config_service, prompt_repo, resolved_identity_provider,
        resolved_module_planner, prompt_models,
    )
    app.state.module_planning_repository = resolved_module_repository
    app.state.module_planning_service = resolved_module_service
    conversation_repository = PostgresPlanningConversationRepository(session_factory) if session_factory is not None else MemoryPlanningConversationRepository()
    app.state.planning_conversation_service = PlanningConversationService(conversation_repository, resolved_module_service)
    resolved_module_service.conversations = app.state.planning_conversation_service
    resolved_module_service.reverse_projects = resolved_reverse_project_service
    resolved_suite_planning_service.module_planning = resolved_module_service
    resolved_suite_planning_service.reverse_projects = resolved_reverse_project_service
    resolved_batch_generation_service.module_planning = resolved_module_service
    resolved_batch_generation_service.reverse_projects = resolved_reverse_project_service
    app.state.suite_planning_confirmation_service = (
        suite_planning_confirmation_service or SuitePlanningConfirmationService(
            plan_repository=resolved_suite_planning_repository,
            batch_repository=resolved_batch_generation_repository,
            identity_provider=resolved_identity_provider,
        )
    )
    resolved_workbench_repository = workbench_repository or (
        PostgresWorkbenchRepository(session_factory)
        if session_factory is not None
        else InMemoryWorkbenchRepository()
    )
    resolved_workbench_service = workbench_service or WorkbenchService(
        resolved_workbench_repository,
        resolved_identity_provider,
        suite_planning_service=resolved_suite_planning_service,
        batch_repository=resolved_batch_generation_repository,
        suite_service=suite_service,
        project_repository=resolved_project_repository,
    )
    app.state.workbench_repository = resolved_workbench_repository
    app.state.workbench_service = resolved_workbench_service

    resolved_image_editing_repository = image_editing_repository or (
        PostgresImageEditingRepository(session_factory)
        if session_factory is not None
        else InMemoryImageEditingRepository()
    )
    resolved_image_editing_service = image_editing_service or ImageEditingService(
        resolved_image_editing_repository,
        resolved_project_repository,
        resolved_identity_provider,
        model_connections=generation_connections,
    )
    app.state.image_editing_repository = resolved_image_editing_repository
    app.state.image_editing_service = resolved_image_editing_service
    app.state.product_library_service = resolved_product_library_service
    app.state.image_editing_worker = ImageEditingWorker(
        resolved_image_editing_repository,
        resolved_project_repository,
        resolved_project_asset_storage,
        resolved_image_editing_service,
        resolved_image_editor,
        resolved_project_asset_service,
        resolved_product_library_service,
    )
    async def load_canvas_steps(project_id):
        scope = resolved_identity_provider.get_context().workspace_id
        assets = await resolved_project_repository.list_assets(project_id, scope)
        edits = await resolved_image_editing_service.repository.list_tasks(project_id, scope)
        steps = await canvas_generation_steps(project_id, scope, assets, resolved_batch_generation_repository, edits)
        steps.extend(reverse_execution_steps(await resolved_reverse_execution_generation_service.list_batches(project_id), assets))
        return steps

    app.state.canvas_generation_service = CanvasGenerationService(
        PostgresCanvasGenerationRepository(session_factory) if session_factory is not None else MemoryCanvasGenerationRepository(),
        resolved_project_repository, resolved_project_asset_storage, resolved_project_asset_service,
        resolved_image_editor, resolved_product_library_service, resolved_identity_provider,
        load_canvas_steps, cfg.image_generation_model, prompt_repository=prompt_repo,
        model_connections=generation_connections,
    )

    # Register all routers
    app.state.style_harmonization_service = StyleHarmonizationService(
        app.state.canvas_generation_service.repository,
        resolved_project_repository, resolved_project_asset_storage, resolved_project_asset_service,
        resolved_image_editor, resolved_product_library_service, resolved_identity_provider,
        cfg.image_generation_model, prompt_repo,
        model_connections=generation_connections,
    )
    app.include_router(style_harmonization_router)
    app.include_router(prompt_router)
    app.include_router(project_router)
    app.include_router(generation_config_router)
    app.include_router(model_connection_router)
    app.include_router(hero_generation_router)
    app.include_router(batch_generation_router)
    app.include_router(suite_plan_router)
    app.include_router(module_plan_router)
    app.include_router(planning_conversation_router)
    app.include_router(reverse_project_router)
    app.include_router(reverse_execution_router)
    app.include_router(task_center_router)
    app.include_router(workbench_router)
    app.include_router(canvas_generation_router)
    app.state.long_image_service = LongImageService(resolved_project_asset_service, resolved_product_library_service, resolved_idempotency_store)
    app.include_router(long_image_router)
    app.include_router(image_editing_router)
    app.include_router(product_library_router)

    app.include_router(asset_router)
    if resolved_product_service is not None:
        app.include_router(product_router)
    if resolved_test_run_service is not None:
        app.include_router(test_run_router)

    app.add_middleware(CORSMiddleware, allow_origins=cfg.cors_origin_list, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = request_id_or_new(request.headers.get("X-Request-ID"))
        request.state.request_id = request_id
        token = request_id_var.set(request_id)
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            request_id_var.reset(token)

    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError):
        return error_response(
            exc.code, exc.message, exc.status_code, request.state.request_id
        )

    @app.exception_handler(HTTPException)
    async def http_error_handler(request: Request, exc: HTTPException):
        return error_response(
            http_error_code(exc.status_code),
            public_http_message(exc.status_code, exc.detail),
            exc.status_code,
            request.state.request_id,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        return error_response(
            "INVALID_REQUEST",
            "request validation failed",
            400,
            request.state.request_id,
        )

    @app.exception_handler(Exception)
    async def unexpected_error_handler(request: Request, exc: Exception):
        logger.error(
            "unhandled request failure",
            extra={"request_id": request.state.request_id},
        )
        return error_response(
            "INTERNAL_ERROR",
            "internal server error",
            500,
            request.state.request_id,
        )

    @app.get("/api/health")
    async def health(): return success_response({"ready": True})

    @app.get("/api/generation-worker/status")
    async def generation_worker_status():
        try:
            return success_response(await app.state.generation_worker_health.status())
        except Exception:
            return success_response({"status": "unknown", "lastSeenAt": None})

    @app.get("/api/ready")
    async def ready():
        if hasattr(repo, "readiness_checks"):
            checks = await repo.readiness_checks()
        else:
            checks = {
                "database": await repo.ready() if hasattr(repo, "ready") else True
            }
        checks["storage"] = True
        if hasattr(object_storage, "ready"):
            checks["storage"] = await object_storage.ready()
        checks["projectDomain"] = await resolved_project_repository.ready()
        checks["projectStorage"] = await resolved_project_asset_storage.ready()
        checks["generationConfig"] = await resolved_generation_config_repository.ready()
        checks["heroGeneration"] = await resolved_hero_generation_repository.ready()
        checks["batchGeneration"] = await resolved_batch_generation_repository.ready()
        checks["suitePlanning"] = await resolved_suite_planning_repository.ready()
        checks["workbench"] = await resolved_workbench_repository.ready() if hasattr(resolved_workbench_repository, "ready") else True
        checks["reverseBatches"] = await reverse_batch_repository.ready()
        if not all(checks.values()):
            failed = ", ".join(name for name, ok in checks.items() if not ok)
            return error_response(
                "DEPENDENCY_NOT_READY",
                f"service dependencies are not ready: {failed}",
                503,
            )
        return success_response({"ready": True, "checks": checks})

    @app.post("/api/suites", status_code=201)
    async def create_suite(payload: SuiteCreate, request: Request, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
        suite = await suite_service.create_suite(payload.name, idempotency_key); return success_response(_suite_view(suite, request))

    @app.get("/api/suites")
    async def list_suites(request: Request): return success_response([_suite_view(item, request) for item in await suite_service.list_suites()])

    @app.get("/api/suites/{suite_id}")
    async def get_suite(suite_id: UUID, request: Request):
        suite = await suite_service.get_suite(suite_id)
        if not suite: raise AppError("INVALID_SUITE_ID", "suite does not exist", 404)
        data = _suite_view(suite, request); data["inputImages"] = [_image_view(item, request) for item in suite.images]
        return success_response(data)

    @app.post("/api/suites/{suite_id}/input-images", status_code=201)
    async def upload_image(suite_id: UUID, request: Request, file: UploadFile = File(...), ordinal: int | None = None, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
        record = await suite_service.upload_input_image(
            suite_id,
            await file.read(),
            file.content_type,
            file.filename or "upload",
            ordinal,
            idempotency_key,
        )
        return success_response(_image_view(record, request))

    @app.get("/api/suites/{suite_id}/input-images/{image_id}/preview/{kind}")
    async def preview(suite_id: UUID, image_id: UUID, kind: str):
        obj = await suite_service.get_input_image_preview(suite_id, image_id, kind)
        return Response(content=obj.data, media_type=obj.content_type, headers={"cache-control": "private, max-age=60"})

    return app
app = create_app()
