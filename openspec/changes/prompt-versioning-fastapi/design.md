## Context

根项目已有 FastAPI 应用工厂、异步 SQLAlchemy 会话、PostgreSQL 仓储和项目/素材基础 API，但提示词运行时仍位于旧 Node 服务；现有迁移命令还读取旧目录 SQL。根目录 `prompt/` 为空，旧提示词模板明确不再自动导入。设计需要在不依赖 `pic_agent_suite_workbench/` 的前提下，建立可重置、可迁移、可审计的提示词版本服务。

## Goals / Non-Goals

**Goals:**

- 用 SQLAlchemy 模型和 Repository 管理模板聚合、不可变版本和版本解析。
- 用 Alembic 作为唯一表结构变更来源，并提供受保护的开发数据库重置流程。
- 让根 `prompt/` 保存每个 code 的最新 Markdown，支持文件导入和商城保存后的原子覆盖。
- 提供 FastAPI API 和商城 UI，实现版本历史查看、基于任意版本编辑、默认最新和显式历史选择。
- 保留同步失败状态、错误信息和幂等重试能力。

**Non-Goals:**

- 本 change 不迁移旧 Node 的规划、图片生成、画布、反推或其它业务接口。
- 不导入旧目录中的任何提示词内容，不设计跨环境发布审批或多用户权限系统。
- 不把数据库历史版本全部反向写成多个文件；文件仓库始终只保留最新版本。

## Decisions

### 1. FastAPI 分层

请求路由只负责校验输入和响应映射；`PromptService` 负责版本创建、hash 去重、默认版本更新和文件同步；`PromptRepository` 通过异步 SQLAlchemy Session 执行事务；`PromptFileStore` 负责 Markdown 解析、渲染、临时文件和原子替换。这样数据库事务和文件系统副作用隔离，后续生成模块可以复用 `resolve_version` 而无需了解存储细节。

### 2. SQLAlchemy + Alembic

新增 `PromptTemplate`、`PromptVersion` 和必要的基础业务模型，使用 PostgreSQL UUID、JSONB、唯一约束和索引。版本不可变性由服务层校验和数据库触发器双重保障。Alembic 使用异步环境，`alembic/versions/0001_initial.py` 建立 FastAPI 基线，后续迁移只从 ORM 变更生成；移除自定义 SQL 迁移 runner 对旧目录的路径依赖。

### 3. 版本和默认指针

`prompt_templates.default_version_id` 指向当前默认版本；`prompt_versions.version_no` 在模板级唯一。创建新版本在同一数据库事务中锁定模板、计算下一个版本号、插入版本并更新默认指针。内容 hash 在模板级索引约束/事务检查下去重，重复提交返回冲突或既有版本。

### 4. 文件同步的一致性

数据库版本先以 `pending` 状态提交，再执行文件写入；文件先写同目录临时文件、flush/fsync 后使用 `os.replace` 原子替换。成功更新为 `synced`，异常更新为 `failed` 并记录错误。数据库版本不会因文件系统故障回滚，重试只重做文件副作用，不新增版本。服务启动和商城详情都暴露同步状态，避免静默不一致。

### 5. 文件格式与导入

根 `prompt/` 下每个 code 一个 `.md` 文件，frontmatter 保存 code、名称、类型、阶段、执行目标和当前 version，正文固定为 System Prompt、User Prompt Template、Input Schema、Output Schema 区块。`prompt-import` CLI 扫描根目录并调用同一 PromptService；旧目录路径不出现在 FastAPI 或 CLI 实现中。新文件创建 v1，hash 变化创建下一版本。

### 6. API 和商城聚合

FastAPI 提供模板列表/详情、版本列表/详情、创建新模板、创建新版本、版本解析和同步重试接口。列表只返回模板聚合项和默认版本摘要，详情再加载版本历史。编辑器持有未保存草稿，保存请求必须带完整提示词和可选 change note；从历史版本保存时仍沿用模板的下一个版本号。

空列表状态必须同时提供“新建提示词”入口。创建表单收集稳定 code、名称、kind、stage、执行目标、System Prompt 及可选 User Prompt/Schema；客户端先做必填与 code 格式校验，再调用创建模板接口。成功后刷新聚合列表并展示 v1 的文件同步状态，失败时保留表单内容并显示服务端错误。

### 7. 全量重置和部署切换

`db-reset --confirm-reset` 仅在配置环境为 development 且操作者显式确认时执行；命令显示目标数据库的非敏感标识后删除应用 schema，再运行 `alembic upgrade head`。Vite 默认 `/api` 代理改为 FastAPI 8000；根项目启动说明和测试不再启动旧 Node。真实远程数据库的重置在执行前单独确认，不由应用启动自动触发。

## Risks / Trade-offs

- **数据库已提交但文件写入失败** → 记录 `failed` 状态和错误，提供 API/CLI 重试；商城明确显示警告。
- **并发保存产生相同版本号** → 在模板行上加锁，并由 `(template_id, version_no)` 唯一约束兜底。
- **进程在文件替换后、状态更新前崩溃** → 重试操作幂等；启动巡检可根据文件 hash 修正状态。
- **生产环境误执行重置** → development 环境校验、显式确认参数和非敏感目标回显三重保护。
- **当前其它页面依赖旧 Node API** → 本 change 明确不迁移这些业务；前端迁移范围只覆盖提示词商城及其 API 客户端。

## Migration Plan

1. 增加 Alembic 基线和提示词版本迁移，先在专用开发数据库执行 `db-reset` 与 `alembic upgrade head`。
2. 部署 FastAPI 提示词路由、Repository、Service 和 CLI，默认不导入旧模板。
3. 更新前端 API 代理和商城页面，使用聚合模板与版本接口。
4. 在确认专用数据库和文件目录可写后，执行根 `prompt/` 的首次导入（空目录时保持空数据库）。
5. 若需回滚，停止新提示词路由并恢复前端代理；数据库使用 Alembic 迁移回退或恢复专用开发库快照，文件可由失败版本重试覆盖。

## Open Questions

无。创建者固定为 `local-user`、版本保存即设为默认、旧模板不导入和本 change 不迁移其它 Node 业务均已确认。
