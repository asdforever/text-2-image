## Context

参见 `proposal.md` 的动机与范围。当前根项目是 React/Vite 前端，真正的服务端实现位于 `pic_agent_suite_workbench/server/`，使用 Node/TypeScript、PostgreSQL、MinIO 和一组可复用的 SQL migration；根项目没有 Python 工程、服务入口或测试基架。第一阶段只迁移 suite 与 input image 这条垂直切片，其他业务继续由现有 Node 服务或 mock 承担。

## Goals / Non-Goals

**Goals:**

- 让 FastAPI 服务可以在本地和 CI 中独立启动，并可通过依赖覆盖进行快速测试。
- 把 HTTP、领域逻辑、数据库和对象存储隔离，使后续业务域可以按同一模式迁移。
- 复用现有数据库 schema 和响应契约，支持安全的增量迁移和回滚到 Node 服务。
- 让上传链路在数据库失败时清理已写入对象，避免产生孤立文件。

**Non-Goals:**

- 本阶段不迁移完整 Node API，不实现认证授权、队列、模型 Provider 或多租户。
- 不在 Python 中重新定义全部历史 schema；迁移文件的长期归属另开 change 决定。
- 不把明文 `.env`、外部 API key 或数据库密码提交到仓库。

## Decisions

### 1. 采用可测试的应用工厂和分层目录

后端放在根目录 `backend/`，入口使用 `create_app(settings=None, overrides=None)` 工厂。目录按职责划分为 `app/api`（路由与依赖）、`app/core`（配置、日志、请求上下文）、`app/domain`（领域模型与规则）、`app/repositories`（数据库接口与实现）、`app/storage`（对象存储接口与实现）和 `tests/`。路由只能依赖领域服务，不能直接拼接 SQL 或调用 MinIO 客户端。

选择应用工厂而不是模块导入时创建全局连接，是为了让测试能够替换数据库和存储，并让启动与关闭生命周期显式释放连接池。备选是单文件 FastAPI 应用，初期更短，但会把依赖和业务边界锁死在 HTTP 层。

### 2. 使用 Pydantic Settings、异步 PostgreSQL 和显式 Repository 协议

配置由 Pydantic Settings 读取环境变量，按 `development`、`test`、`production` 选择默认值；生产环境缺少必填项时 fail-fast。数据库使用 SQLAlchemy 2 的异步会话和 `asyncpg`，Repository 通过协议暴露 suite、input image 和幂等记录的最小操作。API schema 与数据库模型分离，避免把 ORM 字段直接暴露给客户端。

相比同步 psycopg，异步会话更适合后续生成任务和外部 Provider 调用；相比 SQLModel，显式 schema/repository 边界更容易在迁移期间同时容纳旧 Node 数据结构。数据库连接池参数和事务超时必须可配置。

### 3. 保留现有 SQL migration，增加受锁保护的迁移入口

第一版迁移 runner 从配置的 `MIGRATIONS_DIR` 读取按文件名排序的 SQL，默认指向现有 `pic_agent_suite_workbench/db/migrations/`。执行前创建并使用 `schema_migrations` 记录文件名、校验和和执行时间，并通过 PostgreSQL advisory lock 保证单实例执行；同一文件校验和变化时拒绝静默覆盖。迁移命令和应用启动迁移分开，默认启动只检查 schema 版本，显式命令才执行变更。

这样可以复用现有 21 个可幂等 migration，同时避免当前 Node runner 每次启动重复执行全部文件。Alembic 是后续 Python 负责 schema 演进时的候选方案，但本阶段直接把所有 SQL 改写成 Alembic revision 会扩大范围并制造双重 source of truth。

### 4. 通过存储端口隔离 MinIO，并为测试提供内存实现

定义 `ObjectStorage` 接口，包含 put、get、delete 和预签名/预览 URL 操作；生产实现使用 MinIO Python SDK，阻塞调用通过线程池转移，避免占用 ASGI 事件循环；测试实现使用内存字典。上传服务先读取并验证文件，再写入原图、缩略图和生成输入对象，最后在同一数据库事务中写入元数据；任一步骤失败都执行补偿删除并返回稳定错误码。

图片真实性和尺寸由 Pillow 解码校验，允许类型为 JPG、PNG、WebP，单文件上限 12MB。数据库中的对象 key 只保存服务端生成的路径，不接受客户端提供任意 bucket 或绝对路径。

### 5. 统一请求上下文、错误信封和幂等策略

ASGI 中间件读取合法的 `X-Request-ID`，否则生成 UUID，并把它写入响应和日志上下文。异常处理器把 Pydantic 校验、资源不存在、唯一键冲突和依赖不可用映射为统一错误信封，不返回堆栈。需要副作用的路由要求 `Idempotency-Key`，以现有 `suite_workbench.idempotency_keys` 为持久化边界，scope 包含 HTTP 方法、路由和资源 ID；重复 key 返回第一次结果，复用但不重复写对象。

### 6. 健康检查分为存活和就绪

`/api/health` 只检查进程是否能响应；`/api/ready` 并行探测 PostgreSQL 和对象存储。就绪失败返回 503 和错误信封，避免负载均衡把未完成迁移或依赖断开的实例当作可用服务。CORS 允许来源由环境变量配置，生产环境禁止通配符。

### 7. 测试以契约测试为主，真实依赖测试可选

使用 pytest、HTTPX ASGI transport 和依赖覆盖测试应用行为；suite 与 upload 路由各覆盖成功、校验失败、重复提交、依赖故障和补偿清理。Repository 另做针对 PostgreSQL 约束的集成测试，只有设置测试数据库环境时才运行。不会在单元测试中调用真实 MinIO、LLM 或图片 Provider。

## Risks / Trade-offs

- [现有 SQL migration 不是为 Python runner 设计的] -> 默认只允许显式迁移命令，记录校验和并加 advisory lock；执行失败时保留失败文件和日志，禁止继续到不一致版本。
- [FastAPI 与 Node 在迁移期同时存在] -> 只让 FastAPI 接管本 change 声明的路由，前端通过可配置代理目标切换；保留 Node 端口作为回滚路径。
- [MinIO SDK 为同步调用] -> 所有 I/O 经线程池封装，并在测试中使用内存适配器验证超时和清理逻辑。
- [上传文件可能在数据库事务失败后残留] -> 采用“先对象、后数据库、失败补偿删除”的流程，并增加孤立对象清理测试。
- [现有目录含明文凭据] -> 新后端只读取环境注入的密钥；上线前轮换已暴露凭据，并在 CI 中阻止提交 `.env`。

## Migration Plan

1. 新增 `backend/` Python 工程、依赖和测试命令，默认监听独立端口，不改变现有 Node 服务。
2. 配置 `MIGRATIONS_DIR` 指向现有 SQL 目录，在专用测试数据库执行迁移 runner，验证 `suites`、`input_images` 和 `idempotency_keys` 表。
3. 启动 FastAPI 并运行契约测试；用测试 MinIO/内存适配器验证上传与预览，再连接真实 PostgreSQL/MinIO 做一次集成检查。
4. 通过前端代理把 suite/input-image 请求切换到 FastAPI；其余路径继续走原有实现。
5. 若需要回滚，将代理目标切回 Node 服务并停止 FastAPI；不删除数据库表或对象，保留迁移记录和兼容响应。
