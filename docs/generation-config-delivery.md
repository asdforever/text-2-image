# 生成配置中心交付记录

记录日期：2026-09-14

## 当前结论

阶段 2 的本地实现与自动化验证已完成。电商市场、生图模型、图片风格及五类提示词绑定现在由服务端持久化；配置编辑采用草稿与显式发布两步生命周期。主图和套图工作台只读取当前已发布版本，未发布草稿不会影响之后发起的生成。

当前远程数据库仍在阶段 1 revision `f6a7b8c9d0e1`。联调和前端人工验收前，需要执行一次只向前的 Alembic 升级到 `a7b8c9d0e1f2`；不得在当前远程业务数据库执行 downgrade。

## 已实现能力

- `generation_config` schema 下的不可变发布版本和工作区唯一草稿，包含递增版本号、规范化 JSON 文档与内容哈希。
- 初始化、草稿替换、放弃草稿和发布均以工作区锁定事务执行；并发进入不会重复创建初始版本，并发发布不会生成重复版本或使文档内版本号与数据库版本号不一致。
- 服务端权威默认目录：国内/国外范围下的具体电商平台、模型与支持分辨率、风格大类与风格项、主图和详情页内置模块。
- 每个风格大类最多四项；市场、模型和风格支持增删改，内置主图与详情页模块只允许绑定提示词。
- 市场、模型、风格、主图模块和详情页模块保存具体提示词模板 ID 与版本 ID；发布时校验版本存在及模板归属，并保存展示元数据。
- 草稿读取、整份替换、放弃草稿、显式发布、历史版本读取和当前已发布配置解析。
- 所有配置接口使用服务端身份确定工作区、统一响应信封、请求 ID 和持久化幂等边界。
- 生成配置页面使用真实 API 加载、保存草稿、发布和放弃；本地 store 只承载页面编辑态，不再以 localStorage 作为生成配置来源。
- 主图和套图工作台进入时只请求当前已发布配置；加载完成前或加载失败时阻止新生成。

## HTTP 接口

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET` | `/api/generation-config` | 读取当前已发布版本 |
| `GET` | `/api/generation-config/draft` | 读取当前草稿 |
| `PUT` | `/api/generation-config/draft` | 替换当前草稿 |
| `DELETE` | `/api/generation-config/draft` | 放弃草稿并恢复为当前发布版本 |
| `POST` | `/api/generation-config/publish` | 校验并发布草稿 |
| `GET` | `/api/generation-config/versions/{version}` | 读取历史发布版本 |
| `GET` | `/api/generation-config/resolve` | 为阶段 3A 解析当前发布配置与绑定快照 |

## 已完成验证

| 检查 | 命令 | 结果 |
| --- | --- | --- |
| Python 全量测试 | `python -m pytest -q backend/tests` | 132 通过，3 个专用数据库集成项按环境跳过 |
| Python 编译 | `python -m compileall -q backend alembic` | 通过 |
| 前端全量测试 | `npm test` | 115 通过 |
| 前端类型检查 | `npm run typecheck` | 通过 |
| 前端生产构建 | `npm run build` | 通过；保留既有大包体积提示 |
| OpenSpec 严格校验 | `openspec validate persistent-generation-config --strict` | 通过 |
| Alembic 离线升级与迁移图 | `backend/tests/test_generation_config_migration.py` | 通过，单一 head 为 `a7b8c9d0e1f2` |
| 配置 HTTP、幂等和安全契约 | `backend/tests/test_generation_config_api.py`、`test_generation_config_security.py` | 通过 |
| 配置浏览器生命周期 | `npx playwright test tests/e2e/generation-config.spec.ts --workers=1` | 3 通过，覆盖保存草稿不发布、显式发布和加载失败门禁 |

## 前端验收步骤

1. 打开“生成配置”，确认页面展示服务端已发布版本和独立草稿。
2. 修改一个市场或风格并点击“保存草稿”，再进入主图或套图，确认工作台仍显示旧的已发布内容。
3. 返回生成配置点击“发布配置”，重新进入主图或套图，确认新的市场、模型、分辨率或风格可见。
4. 新建第五个风格、使用失效提示词版本或修改内置模块时，确认保存或发布被阻止并显示稳定错误。
5. 保存草稿后点击“放弃草稿”，确认编辑内容恢复为当前已发布版本。

## 下一阶段边界

阶段 3A 才接入第一个真实图片 Provider、单个主图模块的一张图片任务、输入素材版本快照和结果落库。阶段 3A 必须调用 `/api/generation-config/resolve`，并把返回的发布版本、配置内容哈希和提示词绑定快照写入生成任务；不得读取草稿或浏览器本地配置。
