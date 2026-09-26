## Why

提示词目前分散在旧 Node 服务和旧目录中，项目文件与数据库没有统一的版本来源，商城也无法编辑并追踪每次迭代。现在需要在根项目的 FastAPI 后端建立全新的提示词版本系统，让数据库保存完整历史、根 `prompt/` 只保留最新文件，并为商城和后续生成流程提供可追溯的版本选择。

## What Changes

- **BREAKING**：根项目运行时不再依赖或启动 `pic_agent_suite_workbench/`，提示词相关能力全部迁移到 FastAPI。
- 使用 SQLAlchemy 模型和 Repository 实现提示词模板、版本、默认版本和同步状态的 CRUD。
- 使用 Alembic 建立根项目独立的数据库基线；提供带开发环境保护和显式确认的全量重置命令。
- 新建提示词版本模型：版本号递增且不可变，记录完整内容、来源、修改说明、创建者、hash、文件同步状态和时间信息。
- 根目录 `prompt/` 采用一个提示词一个 Markdown 文件；导入新文件创建 `v1`，商城保存新版本时自动原子覆盖对应文件。
- 文件同步失败时保留数据库版本，记录错误并提供幂等重试命令/API。
- FastAPI 提供模板聚合列表、模板详情、版本历史、创建新版本、版本解析和同步重试接口。
- 提示词商城按模板聚合展示版本历史，默认使用最新版本，允许选择历史版本用于生成或作为编辑起点。
- 前端 `/api` 代理切换到 FastAPI；删除指向旧 Node 服务的提示词运行入口。
- 商城在空数据库时提供新建提示词表单，首次保存形成 `v1` 并显示同步结果。
- 现有旧提示词模板不自动导入，数据库重置后从空状态开始。

## Capabilities

### New Capabilities

- `prompt-versioning`: 提示词模板身份、不可变版本、默认版本、版本选择和审计元数据。
- `prompt-file-sync`: 根 `prompt/` Markdown 格式、文件导入、自动原子覆盖、失败状态和重试。
- `prompt-marketplace`: FastAPI 提示词 API 与按模板聚合的商城编辑、历史查看和版本选择体验。

### Modified Capabilities

无。当前 `openspec/specs/` 没有既有能力规范，本 change 建立新的提示词能力契约。

## Impact

- 新增/调整 `backend/app` 的 SQLAlchemy 模型、Repository、Service、FastAPI 路由和 CLI。
- 新增 `alembic/` 配置与迁移版本，重建 FastAPI 所需数据库 schema；不读取旧目录迁移。
- 调整根前端 API 客户端、提示词商城页面和 Vite 代理配置。
- 新增 Python API、Repository、文件同步和迁移测试，以及前端合约测试。
- 不迁移旧 Node 的规划、生成、画布、反推等业务；`pic_agent_suite_workbench/` 不作为运行时依赖。
