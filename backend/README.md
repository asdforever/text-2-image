# PicAgent FastAPI 后端

## 本地开发

首次安装和升级数据库：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
python -m backend.cli migrate
```

推荐用统一命令，在一个 PowerShell 终端保持 API 和批次生图执行器同时运行：

```powershell
npm run api
# 等价于 python -m backend.dev
```

命令先检查端口和数据库配置，等待 API 依赖就绪后再启动执行器；任一进程退出时一并停止并报告错误。默认关闭代码热重载，避免编辑文件中断正在生图的任务。启动会处理已确认、未取消的排队任务。请先处理不再需要的队列任务，再启动执行器。

需要单独调试时，也可分别打开两个终端：

```powershell
# 终端 1：HTTP API
npm run api:http
```

```powershell
# 终端 2：已确认批次的图片生成 Worker
npm run api:worker
```

Worker 只领取用户已经确认的生成槽位。真实图片 Provider 可能产生费用；只检查 Worker 能否初始化时，应先确认开发数据库没有排队任务，再运行 `python -m backend.cli generation-worker --once`。

设置 `DATABASE_URL` 后，使用 `python -m backend.cli migrate` 显式升级数据库。Alembic 是唯一有效的数据库迁移来源；应用启动不会执行 DDL。旧表 `schema_migrations` 仅保留作历史审计，不再驱动任何迁移。

## 已有数据库的一次性基线

不要直接对未知旧库执行 `stamp`。先备份数据库，再运行只读检查：

```powershell
python -m backend.cli schema-check
```

只有输出 `compatible: true`、确认该库结构已与当前 Alembic head 一致且 `public.alembic_version` 尚未登记时，才执行：

```powershell
python -m backend.cli baseline-stamp --confirm-baseline
```

该命令只登记 Alembic head，不重放历史 DDL，也不删除旧 `schema_migrations` 记录。若检查列出缺失结构，应停止并先在数据库副本制定专项迁移方案，不能强行 stamp。

未配置数据库与 MinIO 时，应用使用内存仓储和对象存储，适合运行 API 契约测试。需要连接真实依赖时设置 `DATABASE_URL` 与 `MINIO_*` 环境变量，密钥不得提交到版本库。

## 项目成品档案

项目创建时会自动建立成品档案，源图、白底图、主图、详情图、场景图和编辑结果写入项目资产后会实时关联到该档案。成品档案只保存关系，不复制对象存储文件；提示词商城测试结果保存在独立的“测试结果”库。

升级旧开发数据库后，执行一次幂等回填：

```powershell
python -m backend.cli project-archive-backfill --page-size 100
```

命令输出 `scanned`、`created`、`reused`、`linked`、`unlinked` 和 `failed` 计数。可以重复执行；第二次执行不应新增产品或资产关联。

## 运行检查

```powershell
# API 存活；不检查数据库和对象存储
Invoke-RestMethod http://127.0.0.1:8000/api/health

# 依赖就绪；数据库迁移、对象存储和业务依赖异常时返回 503
Invoke-RestMethod http://127.0.0.1:8000/api/ready

# 查看 API 与 Worker 是否都在运行
Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" |
  Where-Object { $_.CommandLine -match 'uvicorn backend\.app\.main:app|backend\.cli generation-worker' } |
  Select-Object ProcessId, CommandLine
```

正常开发环境应看到一条 Uvicorn 命令和一条 `generation-worker` 命令。`/api/health` 成功但 `/api/ready` 失败，说明进程存活但数据库、迁移或对象存储尚未就绪。

运行测试：

```powershell
python -m pytest backend/tests -q
```

存活检查为 `/api/health`，依赖就绪检查为 `/api/ready`。只有在专用 PostgreSQL 与 MinIO 测试服务可用时才设置 `PICAGENT_INTEGRATION=1` 运行集成入口。

## 阶段六：图片编辑接口

图片编辑由服务端会话保存草稿，不依赖浏览器临时状态。写操作使用会话修订号处理并发冲突；提交后创建异步编辑任务，不在工作台请求中直接调用图片 Provider。

| 方法与路径 | 用途 |
| --- | --- |
| `GET /api/image-editor/capabilities` | 查询当前支持的编辑和 OCR 能力 |
| `POST /api/image-editor/sessions` | 为项目图片版本创建编辑会话 |
| `GET /api/image-editor/sessions?projectId=...` | 查询项目编辑会话 |
| `GET /api/image-editor/sessions/{session_id}` | 恢复会话、操作草稿和修订号 |
| `POST /api/image-editor/sessions/{session_id}/operations` | 按修订号新增或更新编辑操作 |
| `DELETE /api/image-editor/sessions/{session_id}/operations/{operation_id}` | 按修订号删除编辑操作 |
| `POST /api/image-editor/sessions/{session_id}/ocr` | 识别并保存源图文字及区域 |
| `POST /api/image-editor/sessions/{session_id}/submit` | 固化快照并创建排队中的编辑任务 |
| `GET /api/image-editor/tasks/{task_id}` | 查询任务、尝试和版本指针 |
| `POST /api/image-editor/attempts/{attempt_id}/retry` | 重试失败尝试并保留历史 |
| `POST /api/image-editor/tasks/{task_id}/regenerate` | 基于同一会话再次生成 |
| `POST /api/image-editor/tasks/{task_id}/versions/{version_id}/select` | 选择当前版本或终版 |
| `POST /api/image-editor/sessions/{session_id}/archive` | 归档编辑会话 |

## 正式产品库接口

正式成品库与提示词测试产物分开存储。项目创建时自动建立产品条目，项目资产实时汇总到产品档案；生成成功或显式发布时继续形成不可变来源版本快照。

| 方法与路径 | 用途 |
| --- | --- |
| `POST /api/product-libraries` | 创建正式产品库 |
| `GET /api/product-libraries` | 查询正式产品库，默认过滤已归档记录 |
| `GET /api/product-libraries/{library_id}` | 查询产品库详情 |
| `POST /api/product-libraries/{library_id}/archive` | 归档产品库 |
| `POST /api/product-libraries/{library_id}/products` | 创建产品条目 |
| `GET /api/product-libraries/{library_id}/products` | 查询产品条目和版本摘要 |
| `GET /api/products/{product_id}` | 查询产品详情 |
| `GET /api/products/{product_id}/versions` | 按成品类型或状态筛选版本 |
| `POST /api/product-libraries/{library_id}/products/{product_id}/versions/publish` | 使用幂等键显式发布成功版本 |
| `GET /api/products/{product_id}/versions/{version_id}/preview` | 通过站内受控地址预览正式版本 |
| `POST /api/products/{product_id}/versions/{version_id}/archive` | 归档正式产品版本 |
| `POST /api/products/{product_id}/archive` | 归档产品条目 |

阶段六的完整边界、验收结果和人工验收路径见 `docs/image-editing-and-product-library-delivery.md`。
