# 项目与素材域交付记录

记录日期：2026-09-14

## 当前结论

阶段 1 的本地实现已完成。工作台现在有独立于提示词商城的项目与资产数据域，支持项目创建、归档和删除，以及源图、白底图版本、预览、当前选择、幂等上传和对象清理；项目管理页和基础图工作台已接入这些真实接口。

远程数据库已完成前向升级到项目资产域 revision，项目域就绪检查通过。真实 PostgreSQL 的升级、回滚、再升级演练仍待专用测试库；该环境验收不阻塞后续阶段的本地开发，但属于部署前门槛。

## 已实现能力

- `project_workbench` schema 下的项目、对象、项目资产与当前选择关系。
- `/api/projects` 的创建、列表、详情、归档和删除接口；所有读写基于服务端工作区上下文。
- 源图和白底图版本上传、受控预览、选择与取消选择；生成图片类型及生成快照关联保留为空边界，不调用真实 Provider。
- 项目专属 MinIO 对象 key、文件元数据、图片校验、内容哈希和上传失败补偿。
- 资产引用保护、对象同步清理、`cleanup_pending` 状态和重试入口。
- 项目域依赖被纳入 `/api/ready`，不会影响 `/api/health` 的存活语义。
- 前端项目管理页使用真实项目列表、创建、归档和删除；项目工作台和基础图页使用真实项目详情、图片上传、受控预览、当前选择和删除。
- 主图、详情套图、视频、生成配置和真实生图仍未接入项目域；基础图页只管理上传版本，不触发模拟或真实生成。

## 已完成验证

| 检查 | 命令 | 结果 |
| --- | --- | --- |
| Python 全量测试 | `python -m pytest -q` | 97 通过，2 个外部集成项跳过 |
| Python 编译 | `python -m compileall -q backend/app backend/tests alembic` | 通过 |
| OpenSpec 严格校验 | `openspec validate project-asset-domain --strict` | 通过 |
| 迁移离线升级/回滚 | `backend/tests/test_project_migration.py` | 通过 |
| 项目资产 HTTP/安全契约 | `backend/tests/test_project_api.py` | 通过 |
| 前端项目客户端与代理 | `npm test -- tests/project-api-client.test.ts tests/vite-proxy-routing.test.ts` | 通过 |
| 前端类型检查 | `npm run typecheck` | 通过 |
| 远程数据库前向升级 | `python -m backend.cli migrate` | 已升级至 `f6a7b8c9d0e1` |
| 项目域就绪检查 | `GET /api/ready` | `database`、`schema`、`storage`、`projectDomain`、`projectStorage` 均为真 |
| 项目列表实连 | `GET /api/projects` | 200，返回真实空列表 |

## 待环境验收

专用 PostgreSQL 测试库可用后，执行项目域的 `base -> head -> e5f6a7b8c9d0 -> head` 演练，并验证项目、资产对象、白底图引用和选择记录在升级/回滚边界上的一致性。测试库名称必须包含 `test`，不得在当前远程业务数据库执行 downgrade。
