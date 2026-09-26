## Why

当前项目只有前端 mock 运行模式，根目录的后端脚本指向不存在的 `server/`，无法形成可启动、可测试、可逐步迁移的服务端基座。现有 Node 服务和数据库迁移包含了可复用的业务知识，但缺少 FastAPI 的应用边界、配置管理和第一条真实数据链路，因此现在需要先建立一个稳定的 Python 后端骨架。

## What Changes

- 新建独立的 FastAPI 后端工程目录，提供应用工厂、生命周期管理、环境配置、结构化日志、统一错误响应和 OpenAPI 入口。
- 建立 PostgreSQL 数据访问边界和迁移执行入口，保留现有 SQL schema 的可追溯迁移能力，不在本 change 重写全部业务表。
- 建立 MinIO/S3 兼容对象存储抽象，所有文件读写通过依赖注入的存储接口完成，密钥仅从环境变量读取。
- 实现第一条垂直切片：suite 创建/查询，以及 input image 的 multipart 上传、校验、去重、元数据持久化和预览地址返回。
- 对齐现有前端 `/api` 响应信封和错误码约定，补充请求幂等键、健康检查和可自动化测试的依赖覆盖。
- 增加本地开发、测试和 CI 所需的 Python 依赖、配置样例和启动命令；不迁移完整计划、任务、提示词、反推或图片编辑业务。

## Capabilities

### New Capabilities

- `backend-foundation`: FastAPI 应用生命周期、配置、错误契约、健康检查、数据库会话、迁移和对象存储边界。
- `suite-input-images`: suite 基础资源以及 input image 上传、校验、去重、持久化和预览访问。

### Modified Capabilities

<!-- 本 change 暂不修改现有前端能力的业务要求。 -->

## Impact

- 新增 `backend/` Python 包、依赖清单、测试目录和环境变量样例。
- 新增 FastAPI 路由与前端现有 `/api/suites`、`/api/suites/{id}`、`/api/suites/{id}/input-images` 契约的适配层。
- 复用 `pic_agent_suite_workbench/db/migrations/` 中的 schema 作为迁移参考；不会删除或覆盖现有 Node 服务。
- 开发环境需要 Python 3.11+、PostgreSQL 和 MinIO；真实模型 Provider、认证授权和异步任务队列留到后续 change。
