# 旧 Node API 依赖影响核查

核查时间：2026-09-21。范围：当前工作区源码、运行中 FastAPI OpenAPI、Vite 实际代理配置和浏览器只读操作。本次未修改运行代码、未启动旧 Node、未拆分仓库、未执行生成或数据写入。

## 结论

当前仓库没有旧 Node API 实现或启动脚本，本机 3001 端口未监听；8000 FastAPI、5173 Vite 正常监听。旧 Node 的主要影响是遗留代理和少量未迁移的调用，不能通过单纯补开 Worker 解决，也无需据此把 Node API 加入部署。

## 已复现的当前功能故障

| 请求/入口 | 直接请求 FastAPI 8000 | 经前端 5173 | 原因与影响 |
| --- | --- | --- | --- |
| `/api/test-product-libraries` | 200 | 502 | FastAPI 已实现，Vite 缺少匹配规则；当前侧栏测试库页面实际显示“请求失败” |
| 测试库详情、库内产品列表与增删改 | OpenAPI 中已注册 | 配置匹配至 3001 | 同一前缀漏代理；未执行写操作验证 |
| `/api/library/resources?resourceType=base_image&status=published&pageSize=100` | 404 | 502 | FastAPI 没有该旧聚合接口；白底图“从已有库选择”第一步实际失败 |
| `/api/health`、`/api/ready` | 200 | 502 | 健康检查路由也落入 Node 兜底；直接检查后端是正常的 |
| `/api/projects` | 200 | 200 | 已正确代理到 FastAPI |
| `/api/generation-worker/status` | 200 | 200 | 已正确代理到 FastAPI，和上述遗留代理故障不同 |

`src/pages/BaseImageWorkspace.tsx` 的 `loadLibraryItems` 先等待共享资源接口成功，才依次读取成品库和测试库。第一个请求失败会进入整个函数的 catch，因此并非只缺少共享素材，后两种来源也无法加载。浏览器实测点击“从已有库选择”后只发出失败的 `/api/library/resources`，没有继续发出成品库请求。

对运行中 OpenAPI 的路径与实际 Vite 代理逐项比对，确认六个已注册路径模板漏转 FastAPI：四个测试库模板及两个健康接口。输入图预览仅允许 `original|thumbnail`，使用这两个合法值时代理正确，不能把任意 `{kind}` 占位值的匹配失败算作漏配。

## 保留但当前未挂载的旧界面

- `src/main.tsx` 仅启动 `src/routes/router.tsx` 的 RouterProvider，未使用 `src/app/App.tsx`。
- `StartPage.tsx` 和 `StyleLibraryPage.tsx` 被旧 `app/App.tsx` 引用，但不在当前路由树中。旧平台、RAG 搜索、白底版本、规划等接口调用主要在这些页面。
- 当前 `BoardPage` 返回 `CanvasStudio`，并不渲染同文件中的 `BoardInner`、`LibraryPanel`。旧 `WorkbenchBoardPage.tsx` 也未接入当前页面。
- 因此这些旧界面里的 `/api/generation-attempts/*/retry`、`/api/library/*`、`white-resource` 等调用需要清理或迁移，但不能据文本搜索直接断言当前画布全部依赖 Node。
- 当前主图/详情批次、图片编辑、画布生成等使用 `/api/projects/*`、`/api/image-editor/*`、已匹配的 workbench 路径；本次未发现这些主要路径被转发到 Node。此结论为路由检查，不等于重新验收所有业务操作。

## 配置、依赖和文档残留

- `vite.config.ts` 的 `/api` 兜底指向 `127.0.0.1:3001`。
- 根 `.env.example` 仍有 `PORT=3001` 和 `VITE_NODE_API_PROXY_TARGET`。`PORT` 也是 Python Settings 接受的字段，拆分时应统一后端端口说明。
- `tests/vite-proxy-routing.test.ts` 明确断言旧规划接口继续去 Node，后续取消 Node 兜底时需要同步改测试。
- `docs/backend-selective-cutover.md` 描述的是早期仅迁移 suite/input-image 的状态，已不能准确代表当前系统。
- `package.json` 中存在 `pg`、`minio`、`sharp`、Langfuse/OTel 等依赖；对 `src` 的导入检索未发现使用这些包。它们是后续拆分时可核对的依赖清理候选，不代表存在可运行的 Node API。
- Node.js 仍是前端构建工具所需运行时，与旧 Node API 服务是两回事。

## 拆仓前建议顺序

1. 修复测试库和健康接口的代理，或在明确不再兼容旧服务后将 `/api` 统一指向 FastAPI。
2. 将白底图图库选择接到已实现的素材库、成品库、测试库接口，并使各来源独立处理失败。仅改代理会使旧共享接口由 502 变成 404，功能仍未修复。
3. 验证测试库读取、图库选择、图片预览和主流程；测试避免真实生成请求。
4. 清理未挂载旧页面、旧客户端接口、旧 Node 配置及过期切流文档，再完成两个独立仓库和 Drone 配置。

本次没有修改原项目代码，也没有创建两个新仓库。


## 修复记录

用户确认清理后，已统一 `/api` 到 FastAPI，移除旧 Node 代理和示例配置；白底图库迁移到现有三类库并隔离读取失败；移除未挂载旧页面、旧画布实现和 26 个旧客户端方法。旧页面原始内容（含原有未提交修改）备份于被 Git 忽略的 `.scratch/legacy-node-before-cleanup/`。本节之后以修复后的运行和测试结果为准，上面的 502/404 表格记录的是修复前证据。拆仓仍未执行。
