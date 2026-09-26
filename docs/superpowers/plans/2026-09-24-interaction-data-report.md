# Task 1 交付报告：读取缓存、商城与任务中心

## 实施内容

- `src/lib/read-cache.ts`：新增 10 秒共享读取缓存，支持新鲜值复用、在途合并、过期重读、同步读取旧值、前缀失效，以及失效后阻止旧在途响应重新写入缓存。
- `src/api/client.ts`：模板列表、分类、模板详情、模板版本、已发布生成配置、项目列表和项目详情接入缓存；相关写操作仅在成功返回后失效。未知写结果继续抛出原有 `ApiResultUnknownError`，不会提前清空缓存。
- `projectApi.get(projectId, options?: { force?: boolean })`：新增可选强制刷新；强制刷新绕过新鲜值，同时仍合并相同在途请求。画布生成步骤补充可选 `batchId`、`batchCreatedAt`。
- `PromptMarketplacePageNew.tsx`、`PromptDetailPanel.tsx`：选择模板后立即显示目标详情加载状态；失败可局部重试；快速切换和关闭后忽略旧响应；同一详情后台刷新时保留内容；写操作后的详情刷新只由父层执行一次。列表和分类失败不再清空已有内容。
- `usePublishedGenerationConfig.ts`、`ProjectManagementPage.tsx`：挂载时同步使用缓存快照，后台刷新失败时保留当前配置或项目列表。
- `TaskCenterPage.tsx`、`src/lib/task-center.ts`：活动任务每 3 秒串行刷新；终态停止；隐藏页面不轮询；窗口聚焦或恢复可见时立即校准；请求失败保留现有任务并继续下一轮。
- 新增商城交互专用样式，未修改共享 `index.css` 或 `studio.css`。

## 测试

- 新增 `tests/read-cache.test.ts`：覆盖在途合并、TTL、过期旧值、失效期间旧响应、失败恢复和强制刷新合并。
- 新增 `tests/shared-api-read-cache.test.ts`：覆盖项目、项目资产、提示词目录/分类/详情和已发布配置的缓存与写后失效，以及未知写结果语义。
- 扩展 `tests/task-center.test.ts`：覆盖活动态与终态判定。
- 扩展 Playwright：商城慢响应、快速切换、失败重试、单次写后详情刷新；项目后台刷新失败保留；任务串行更新、失败保留和终态停止。按分工未运行 E2E，也未启动服务器。
- 最终范围内单元测试：29/29 通过。
- `npm run typecheck`：通过。
- 三个修改过的 E2E 文件使用 TypeScript `--noEmit` 检查：通过。
- 完整 `npm test` 曾运行到 200/205；随后修复了本范围内唯一失败并通过对应回归。其余四项失败位于并行修改的生成配置市场层级、模块数量归一化、套图工作台控制和生成快照断言，由主任务统一处理。

## 关注点

- 缓存是当前浏览器页面进程内缓存，没有持久化，也没有新增依赖。
- 项目详情会缓存 10 秒；任务或供应商异步更新项目资产时，调用方应使用 `projectApi.get(id, { force: true })`。主工作台显式刷新已采用该参数。
