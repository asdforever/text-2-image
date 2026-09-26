# QuantumNous/new-api 交互流畅度源码笔记

调研日期：2026-09-24。范围仅限公开仓库 `QuantumNous/new-api` 的 React 前端源码，不运行服务、不登录、不调用任何付费 API，也不修改本地应用代码。

## 版本与核验方法

- 固定上游版本：[`d04c118c8803f49e0c9bab74dcf5b5efeab9464a`](https://github.com/QuantumNous/new-api/commit/d04c118c8803f49e0c9bab74dcf5b5efeab9464a)，GitHub commits Atom 显示该提交时间为 2026-09-23 13:00 UTC。
- GitHub REST API 在调研时返回公共限流 403，`git ls-remote` 也受网络限制；因此通过 GitHub 官方 codeload 下载 `main` 快照，通过官方 commits Atom 取得 HEAD SHA，再将本文引用的 12 个文件逐个与 `raw.githubusercontent.com/<SHA>/...` 做 SHA-256 字节比对，12/12 一致。
- 所有 GitHub 源码链接均固定到上述 SHA 和具体行号。仓库此版本前端是 React 19 + TypeScript + Rsbuild + TanStack Router/Query/Table；不能用旧版 Semi UI/Vite 架构解释当前实现。[依赖清单](https://github.com/QuantumNous/new-api/blob/d04c118c8803f49e0c9bab74dcf5b5efeab9464a/web/package.json#L20-L91)

## 高价值结论

### 1. 路由切换的流畅感来自“提前加载 + 轻量进度反馈 + 生产分包”的组合

**确凿代码事实：** Router 全局配置 `defaultPreload: 'intent'`，用户表达导航意图时即可预加载目标路由；`defaultPreloadStaleTime: 0` 让路由层不自行把 loader 数据视为新鲜数据，而由 Query 缓存负责数据新鲜度。[main.tsx 51-56](https://github.com/QuantumNous/new-api/blob/d04c118c8803f49e0c9bab74dcf5b5efeab9464a/web/src/main.tsx#L51-L56) 根组件一直挂载 `NavigationProgress`，它监听 Router 的 `pending` 状态，以 2px 顶部进度条立即反馈导航开始和结束。[__root.tsx 54-86](https://github.com/QuantumNous/new-api/blob/d04c118c8803f49e0c9bab74dcf5b5efeab9464a/web/src/routes/__root.tsx#L54-L86) [navigation-progress.tsx 23-41](https://github.com/QuantumNous/new-api/blob/d04c118c8803f49e0c9bab74dcf5b5efeab9464a/web/src/components/navigation-progress.tsx#L23-L41)

生产构建开启 TanStack Router 自动按路由拆包，开发环境故意关闭路由异步 chunk，以减少本地导航白闪并加快 HMR；同时 React、UI primitives、TanStack 被拆为稳定 vendor chunk。[rsbuild.config.ts 26-54](https://github.com/QuantumNous/new-api/blob/d04c118c8803f49e0c9bab74dcf5b5efeab9464a/web/rsbuild.config.ts#L26-L54) [rsbuild.config.ts 90-99](https://github.com/QuantumNous/new-api/blob/d04c118c8803f49e0c9bab74dcf5b5efeab9464a/web/rsbuild.config.ts#L90-L99)

**基于代码的推断：** 这套组合降低首次 bundle 体积，并在 chunk 或 loader 尚未完成时给出不遮挡内容的反馈，因此“响应快”和“等待可感知”同时成立。源码配置能证明机制存在，不能单独证明具体网络下的毫秒收益；还需要构建产物分析和浏览器性能数据才能量化。

### 2. 数据层把重复请求、短时间回访和系统初始化都收敛到共享缓存

**确凿代码事实：** 全局 QueryClient 将查询 `staleTime` 设为 10 秒、关闭窗口聚焦自动刷新，并只在生产对可重试错误做有限重试；Query 和 Mutation 的最终错误统一处理。[query-client.ts 36-64](https://github.com/QuantumNous/new-api/blob/d04c118c8803f49e0c9bab74dcf5b5efeab9464a/web/src/lib/query-client.ts#L36-L64) 应用挂载前先读本地缓存显示系统名和 favicon，再用同一个 QueryClient 的 `ensureQueryData` 后台刷新并预热 `['status']`，后续消费者复用同一结果。[main.tsx 70-98](https://github.com/QuantumNous/new-api/blob/d04c118c8803f49e0c9bab74dcf5b5efeab9464a/web/src/main.tsx#L70-L98)

**基于代码的推断：** 短时间内返回页面不必重复等待相同数据，品牌信息也不会等 React 挂载和网络完成才出现。这是比单纯增加 spinner 更直接的体感优化。10 秒只是全局默认值，不代表所有查询都使用相同缓存策略，页面仍可覆盖它。

### 3. HTTP 层另有“并发同参 GET 合并”，避免组件同时挂载造成请求风暴

**确凿代码事实：** Axios `get` 被包装：默认用 `session SID + URL + JSON params` 作为 key；相同请求尚未结束时直接返回已有 Promise，结束后清除；调用方可用 `disableDuplicate` 显式绕过。[http-client.ts 49-75](https://github.com/QuantumNous/new-api/blob/d04c118c8803f49e0c9bab74dcf5b5efeab9464a/web/src/lib/http-client.ts#L49-L75)

**基于代码的推断：** 即便多个组件没共用相同 Query key，同一会话中的完全相同 GET 也不会并发打两次，减少带宽、后端争用和后到响应覆盖先到响应的机会。

**边界：** key 只包含 SID、URL 和 `JSON.stringify(params)`，不包含其余 headers；参数对象键顺序不同也可能无法合并。它也不取消旧请求，不能替代页面级竞态保护。

### 4. 表格首载显示等结构骨架，翻页/筛选刷新则保留旧数据并只做轻微淡化

**确凿代码事实：** API Key 表把页码、每页数量、搜索词、token 过滤器和刷新触发器都纳入 Query key；分页由服务端处理，并设置 `placeholderData: previousData`。[api-keys-table.tsx 232-303](https://github.com/QuantumNous/new-api/blob/d04c118c8803f49e0c9bab74dcf5b5efeab9464a/web/src/features/keys/components/api-keys-table.tsx#L232-L303) 同样的 previous-data 策略也实际用于 channels、users、redemption codes 等列表，而非只存在于抽象层。

表格真正的初次 `isLoading` 才渲染 `TableSkeleton`；骨架读取当前可见列和页大小，最多生成 20 行、固定行高并使用变化的单元格宽度，保持表格几何结构稳定。[data-table-view.tsx 258-284](https://github.com/QuantumNous/new-api/blob/d04c118c8803f49e0c9bab74dcf5b5efeab9464a/web/src/components/data-table/core/data-table-view.tsx#L258-L284) [table-skeleton.tsx 45-88](https://github.com/QuantumNous/new-api/blob/d04c118c8803f49e0c9bab74dcf5b5efeab9464a/web/src/components/data-table/core/table-skeleton.tsx#L45-L88) 已有数据后的 `isFetching` 不换成全屏加载，而是保留列表、150ms 过渡到 60% 透明并暂时禁交互。[data-table-page.tsx 493-560](https://github.com/QuantumNous/new-api/blob/d04c118c8803f49e0c9bab74dcf5b5efeab9464a/web/src/components/data-table/layout/data-table-page.tsx#L493-L560)

**基于代码的推断：** 首载时骨架减少布局跳动，后续翻页/筛选时旧内容不会瞬间清空，页面空间和操作上下文保持稳定。这比所有请求统一使用居中 spinner 更能解释“丝滑”。旧数据在请求期间仍可见，因此必须像源码一样明确禁用交互或标示正在刷新，避免用户误把旧数据当新结果。

### 5. 搜索不在每个按键上发请求，并对中文输入法和旧响应做了针对性处理

**确凿代码事实：** 通用 `useDebounce` 默认延迟 500ms并在新值到来时清理旧定时器。[use-debounce.ts 21-40](https://github.com/QuantumNous/new-api/blob/d04c118c8803f49e0c9bab74dcf5b5efeab9464a/web/src/hooks/use-debounce.ts#L21-L40) 通用表格工具栏维护独立输入草稿，支持配置 debounce，并在 IME composing 时不提交搜索；API Key 和 Channel 表明确配置 500ms。[toolbar.tsx 174-215](https://github.com/QuantumNous/new-api/blob/d04c118c8803f49e0c9bab74dcf5b5efeab9464a/web/src/components/data-table/toolbar/toolbar.tsx#L174-L215) [api-keys-table.tsx 341-359](https://github.com/QuantumNous/new-api/blob/d04c118c8803f49e0c9bab74dcf5b5efeab9464a/web/src/features/keys/components/api-keys-table.tsx#L341-L359)

Billing history 是一个更完整的手写请求例子：搜索使用 debounced keyword；每次请求递增 request id，只允许最新请求写回 records/loading；用户继续输入时主动使在途 id 失效，搜索和每页数量变化都重置到第一页。[use-billing-history.ts 50-91](https://github.com/QuantumNous/new-api/blob/d04c118c8803f49e0c9bab74dcf5b5efeab9464a/web/src/features/wallet/hooks/use-billing-history.ts#L50-L91) [use-billing-history.ts 125-154](https://github.com/QuantumNous/new-api/blob/d04c118c8803f49e0c9bab74dcf5b5efeab9464a/web/src/features/wallet/hooks/use-billing-history.ts#L125-L154)

**基于代码的推断：** 防抖降低请求频率，IME 防护避免拼音组合中途提交，请求 id 防止慢旧响应覆盖新搜索结果。三者解决不同问题，不能只复制一个 debounce hook 就认为搜索竞态已经解决。

### 6. 分页、筛选和显示偏好被做成可恢复状态，而不是组件临时状态

**确凿代码事实：** `useTableUrlState` 从路由 search params 恢复页码、页大小、全局搜索和列筛选；页大小另存 localStorage。分页或筛选变化通过 Router 更新 URL，搜索/列筛选变化会清除页码回到第一页，越界页会被修正。[use-table-url-state.ts 107-181](https://github.com/QuantumNous/new-api/blob/d04c118c8803f49e0c9bab74dcf5b5efeab9464a/web/src/hooks/use-table-url-state.ts#L107-L181) [use-table-url-state.ts 183-253](https://github.com/QuantumNous/new-api/blob/d04c118c8803f49e0c9bab74dcf5b5efeab9464a/web/src/hooks/use-table-url-state.ts#L183-L253) 通用表格 hook 还支持把列可见性和列宽持久化到 localStorage。[use-data-table.ts 283-420](https://github.com/QuantumNous/new-api/blob/d04c118c8803f49e0c9bab74dcf5b5efeab9464a/web/src/components/data-table/hooks/use-data-table.ts#L283-L420)

**基于代码的推断：** 浏览器前进/后退、刷新和分享链接后仍能恢复用户所在列表上下文，减少“界面突然回默认状态”的割裂感。该机制主要提升连续工作流，不直接缩短网络耗时。

### 7. 动画克制且尊重 reduced motion；它是收尾，不是主要性能来源

**确凿代码事实：** 已认证布局实际使用 `AnimatedOutlet`；它以最终匹配的 route id 作为动画 key，同一路由仅参数变化时不会无谓 remount 页面并丢失本地状态。进入动画为短时 opacity/位移/blur，用户启用 reduced motion 时直接渲染普通容器。[page-transition.tsx 39-86](https://github.com/QuantumNous/new-api/blob/d04c118c8803f49e0c9bab74dcf5b5efeab9464a/web/src/components/page-transition.tsx#L39-L86) 侧栏切换使用 `AnimatePresence mode='wait'` 和 fast transition，也会在 reduced motion 时取消进入/退出位移动画。[app-sidebar.tsx 46-71](https://github.com/QuantumNous/new-api/blob/d04c118c8803f49e0c9bab74dcf5b5efeab9464a/web/src/components/layout/components/app-sidebar.tsx#L46-L71)

**基于代码的推断：** 150–250ms 级的小位移和淡入能把状态变化连起来，而按 route id 稳定 key 避免动画为了好看而破坏页面状态。流畅度的主要来源仍是预加载、缓存、保留旧数据和局部 loading；动画无法补救重复请求或空白等待。

## 反例与限制

1. **当前不能声称列表已启用虚拟化。** `@tanstack/react-virtual` 出现在 `package.json`，但对固定 SHA 的 `web/src` 全量搜索没有任何导入或 `useVirtualizer` 调用。实际大表策略是服务端分页和固定可选页大小；依赖存在不等于功能启用。[package.json 39-45](https://github.com/QuantumNous/new-api/blob/d04c118c8803f49e0c9bab74dcf5b5efeab9464a/web/package.json#L39-L45) [pagination.tsx 50-60](https://github.com/QuantumNous/new-api/blob/d04c118c8803f49e0c9bab74dcf5b5efeab9464a/web/src/components/data-table/core/pagination.tsx#L50-L60)
2. **`useMinimumLoadingTime` 没有实际调用。** Hook 会让骨架至少显示 1000ms以防闪烁，但 `web/src` 除定义文件外无引用，不能把现有体验归因于它。[use-minimum-loading-time.ts 21-51](https://github.com/QuantumNous/new-api/blob/d04c118c8803f49e0c9bab74dcf5b5efeab9464a/web/src/hooks/use-minimum-loading-time.ts#L21-L51)
3. **通用自动骨架封装也未发现业务调用。** `ContentSkeleton` / `QuerySkeleton` 已封装 `auto-skeleton-react` 和错误重试，但在 `web/src` 除定义文件外没有引用；当前可见的 loading 主要来自显式 `Skeleton`、`TableSkeleton` 和 `LoadingState`。[auto-skeleton.tsx 35-80](https://github.com/QuantumNous/new-api/blob/d04c118c8803f49e0c9bab74dcf5b5efeab9464a/web/src/components/auto-skeleton.tsx#L35-L80)
4. **并非所有局部请求都同等完善。** React Query 管理的请求通常自动避免旧 query key 串写；手写请求必须像 billing history 一样自己做 request id 或 AbortSignal。不能从一个良好例子推断整个前端所有弹窗/详情都具备竞态保护。
5. **本次是静态源码核验，不是性能基准。** 没有运行 New API 生产部署，也没有测 LCP、INP、路由耗时、chunk 大小或弱网表现。因此本文能回答“哪些已实现机制可能带来流畅感”，不能证明它在所有设备上更快，也不能给出各机制贡献比例。

## 对本地项目的直接启示

最值得复用的是状态策略，而不是技术栈名称：导航立刻给轻量反馈；相同请求共享；首载用等结构骨架；后台刷新保留已有内容；搜索草稿与已提交过滤条件分离；页码、筛选和选择状态可恢复；手写异步请求明确防旧响应写回。实施时应逐项用本地页面的真实请求与状态验证，不能因为已经安装 TanStack、动画库或 skeleton 依赖就认为机制已生效。

## 与本项目的源码对照

本地基线：`5041a5a7ccf3e2060de2b7fe8d3cc35c3c88122b` 加当前工作区。已有后端提示词规划修改不属于本次研究。本次仅新增研究文档，不修改应用逻辑。

### 1. 首次加载：路由静态引入所有页面

[src/routes/router.tsx](../../src/routes/router.tsx#L1) 静态引入工作台、画布、商城和配置页面；[ProjectWorkbench.tsx](../../src/pages/ProjectWorkbench.tsx#L12) 又静态引入三种图片工作台。[vite.config.ts](../../vite.config.ts) 没有额外分包配置。

2026-09-24 执行 `npm run build` 成功，含 UTF-8 检查、TypeScript 构建与 Vite 生产构建，实际输出：

| 产物 | 构建报告大小 | gzip 大小 |
| --- | ---: | ---: |
| 单个入口 JS | 1,876.15 kB | 524.27 kB |
| 入口 CSS | 199.98 kB | 34.06 kB |

构建器同时提示 chunk 超过 500 kB。这证明初始代码负担偏集中；不能据此声称用户操作已经掉帧，也不能拿它直接与未构建的 New API 比体积。生产 gzip 数字也不代表当前开发服务器实际传输量。

建议先按页面分割，重点把画布和图片编辑器移出普通管理页的初始依赖；按导航意图预加载时，只预取代码和安全的读取数据，不触发生成、编译或其他写操作。无需因为参考项目使用 Rsbuild 就更换现有 Vite。

### 2. 返回列表：缺少统一的服务端数据缓存

[提示词商城第 13、41–45、303 行](../../src/components/PromptMarketplace/PromptMarketplacePageNew.tsx#L41) 在组件内保存列表，每次挂载重新请求模板与分类，在两者结束前显示大块加载区域。失败被转换为空数组，用户可能看到“没有数据”，而非可重试的接口错误。

[项目管理第 16–27 行](../../src/pages/ProjectManagementPage.tsx#L16) 在每次读取时设为 loading，刷新期间替换列表。[已发布配置 hook 第 8–33 行](../../src/hooks/usePublishedGenerationConfig.ts#L8) 虽然读取共享 store，每次挂载仍发起刷新，没有在该 hook 内统一请求合并与有效期。

[请求层](../../src/api/client.ts#L460) 使用 `cache: "no-store"`。它控制 HTTP 缓存，不能单独用来断言应用完全没有缓存；真正的缺口是上述读取路径没有统一的查询缓存和在途请求合并策略。

建议把服务端数据交给统一查询层，例如 React Query；Zustand 继续管理编辑草稿、选择状态和工作区状态。列表再次进入先显示已知数据，后台更新；变更成功后只更新或失效相关数据。缓存按项目、查询参数及适用的身份隔离，任务状态采用单独的新鲜度策略。

### 3. 点击详情：立即选中，但没有详情加载状态

[商城 loadDetail 第 92–96 行](../../src/components/PromptMarketplace/PromptMarketplacePageNew.tsx#L92) 在请求返回后写入详情和选中 ID；[点击逻辑第 239 行](../../src/components/PromptMarketplace/PromptMarketplacePageNew.tsx#L239) 虽提前设置选中 ID，但 [PromptDetailPanel 第 33 行](../../src/components/PromptMarketplace/PromptDetailPanel.tsx#L33) 只根据详情数据渲染，空详情时仍是“选择一个提示词查看详情”。

准确说，是**详情区域已经存在，但点击后缺少 pending 内容反馈**，并不是整个侧栏一定等接口返回才挂载。连续切换模板时也没有请求序号或取消保护：源码允许较早请求较晚返回后覆盖最新选择。这是静态分析发现的竞态风险，尚未用延迟网络复现。

建议点击即显示目标模板名称与骨架占位，按模板 ID 缓存详情；仅接受与当前选择匹配的响应，并提供局部重试。已加载内容在同一资源刷新时保留；跨资源切换必须明确当前目标，避免把旧内容误当成新内容。

### 4. 保存详情：父子组件重复刷新

[父页面第 102–137 行](../../src/components/PromptMarketplace/PromptMarketplacePageNew.tsx#L102) 在保存新版本、更新信息、设置默认版本后刷新列表并读取详情；[详情组件第 42–80 行](../../src/components/PromptMarketplace/PromptDetailPanel.tsx#L42) 等父回调结束后，又调用 `onRefresh()`。当前调用链会再次读取详情。

建议明确由一层负责变更后的缓存更新/失效，移除双重刷新；互不依赖的必要读取并行。按钮立即进入提交状态，完成后局部更新并提示结果。删除、实际生成等操作不能因为追求流畅就假定服务端已成功。

### 5. 列表与输入：已有优化，但覆盖不一致

[PromptGrid 第 26–42 行](../../src/components/PromptMarketplace/PromptGrid.tsx#L26) 直接渲染全部结果，搜索通过本地 `useMemo` 过滤。当前搜索没有每输入一个字就请求后端，因此不应机械增加网络搜索防抖；条目量大时先测渲染开销，再决定分页、虚拟化或延后列表更新。

[BaseImageWorkspace 第 49–51、158 行](../../src/pages/BaseImageWorkspace.tsx#L49) 已真实启用虚拟列表；[shared.tsx](../../src/pages/shared.tsx#L8) 图片组件已有懒加载、异步解码、加载及失败反馈，应保留并复用这些能力。

[useProjectStore 第 115、125、336 行](../../src/store/useProjectStore.ts#L115) 使用 localStorage 持久化，未配置 partialize；输入相关更新与不断增长的快照可能增加同步序列化成本。这只是待测风险，不是已确认的卡顿根因。后续需以实际存储体积和性能采样决定是否分离草稿、限量快照或调整写入频率。

### 6. 长任务：状态连续比动画更关键

[TaskCenterPage 第 24–31、41 行](../../src/pages/TaskCenterPage.tsx#L24) 只有首次加载和手动刷新入口，组件内没有周期查询；不能期待停留在任务中心时状态自动推进。

同时，[useTaskRecovery](../../src/hooks/useTaskRecovery.ts#L19) 已有串行任务查询、终态停止和卸载清理；[白底图任务 hook](../../src/lib/use-white-background-tasks.ts#L13) 已有在途防重入、终态判断、完成刷新和窗口恢复时查询。问题是这些能力分散在不同页面。

建议复用统一的任务读取策略：存在活动任务时更新，终态停止，后台页面降低频率，窗口恢复时校准；错误显示“重连中”且保留已有进度。显示服务端确实提供的阶段、完成数量、耗时和最后更新时间，不伪造百分比；“查询了多少次”不应成为主要进度信息。是否改用 SSE 应在量化轮询负担后决定，不是流畅交互的前提。

### 7. 用户追加：画布在项目工作台内切换（2026-09-24）

用户反馈：点击“画布”不应进入独立页面；先记录，随后与本次交互优化一起实施。

当前实现：[ProjectWorkbench.tsx 第 39、100 行](../../src/pages/ProjectWorkbench.tsx#L39) 将画布按钮导航到独立的 `/suites/$suiteId/board` 路由；[router.tsx 第 56–70 行](../../src/routes/router.tsx#L56) 还将项目路由的 `tab=canvas` 重定向到该页面。这是工作台内的路由跳转，源码并未显示该入口新开浏览器窗口。

待改要求：画布作为当前项目工作台中的一个标签，与白底图、主图、详情套图并列；点击时只切换工作区域，保留项目标题、项目导航和当前项目上下文。往返切换时保留编辑草稿、任务状态以及画布编辑状态，避免重复加载造成闪屏。画布代码仍可按需加载，无需为内嵌显示而加入首屏包。

实施时同步调整画布按钮、快捷键和 `tab=canvas` 路由行为；兼容已有画布链接。验收包括：进入画布后项目导航仍可见，可直接切回其他标签；切换不丢失编辑状态、不重新提交生成任务；刷新或直接打开画布链接仍定位到对应项目。状态：已实施，并通过相关浏览器回归。

### 8. 用户追加：移除“参考套图”区块（2026-09-24）

用户通过截图明确要求删除“参考套图”部分，随上述交互优化一起处理。删除范围包含区块标题与说明、“选择参考套图”按钮、“上传参考套图”文件选择入口、“已选 0/12”数量提示，以及该区块内的选择、预览和排序界面。

已定位组件：[ReferenceAssetPicker.tsx](../../src/components/generation-workspace/ReferenceAssetPicker.tsx#L51)。实施时移除对应工作台配置入口并收拢间距；检查旧草稿中的参考套图选择，避免隐藏的旧选择继续影响新生成。该需求针对截图中的参考套图区块，不代表删除用户已上传的资产或下方独立的图片风格设置。验收：区块及其入口不再出现，配置布局无残留空白，旧选择不会在用户不可见的情况下继续参与新生成。状态：已实施，并通过相关浏览器回归。

### 9. 用户确认：结果区的页面布局和状态梳理（2026-09-24）

用户针对主图结果区截图确认，问题是“页面布局和状态”。截图同时出现“正在编译主图提示词 · 6 个模块”、10 张结果缩略图、顶部配置“1:1 · 标准 1K · 复古潮玩”、选中图片尺寸“1086×1448”和长 batch 文件名。截图无法证明这些图片属于正在编译的任务，也不能据此判定生成参数或图片风格出错；当前需要解决的是信息归属和展示层级不清楚。

待改方向：

- 顶部使用明确的任务状态区，显示当前执行任务的真实阶段与适用的进度信息；区分模块数量、计划图片数和已完成图片数。
- 结果区明确当前查看的生成批次；新任务执行期间若展示历史结果，标注“正在展示上次结果”或具体批次，不让历史图片数量看起来像当前任务进度。实施前核对真实任务与资产关联，无法确认归属时明确标示。
- 选中图片展示其所属批次的配置快照与实际尺寸；当前编辑配置须明确归属，不能混用当前风格或比例来描述历史图片。
- 图片主标题优先使用可读名称，例如“第 10 张 · 模块名称”；模块名来自真实数据，长技术文件名收进图片详情。
- 统一图片预览、缩放及操作工具栏的位置，合并重复的图片数量入口；底部缩略图按批次组织并明确选中态，减少分散的信息和无意义留白。
- 加载、编译、排队、生成、部分完成、失败及重连状态采用一致的局部反馈；刷新保留可查看结果，用户正在查看历史图时不因后台进度变化突然切换选中图片。

验收覆盖新任务执行同时查看历史结果、切换批次与图片、当前配置不同于历史图片配置、部分失败和网络重连等场景；任务与图片状态归属清楚，数量含义一致，结果更新不打断查看。状态：已实施；当前任务、历史批次与选中图片参数分开展示，后台刷新保持选中项。

## 建议实施顺序与验收

这些是后续建议，不是本次已经实施或获得的性能结果。

| 顺序 | 范围 | 主要收益 |
| --- | --- | --- |
| P0 | 提示词商城详情 pending、竞态保护、移除双重刷新、区分错误与空列表 | 点击有回应，保存少等待，连续选择不串内容 |
| P1（用户明确要求） | 画布改为当前项目工作台内的标签切换，兼容旧链接并保留编辑状态 | 不离开项目上下文，便于在图片工作台与画布之间往返 |
| P1（用户明确要求） | 移除参考套图整块配置入口，处理旧草稿中的隐藏选择 | 精简配置区，避免残留选择影响新生成 |
| P1（用户明确要求） | 梳理结果区布局，区分执行任务、查看批次与选中图片信息 | 状态、数量和配置归属清楚，查看结果不中断 |
| P1 | 模板/分类/配置/项目统一查询缓存；区分首次加载和后台刷新 | 返回页面不反复清空，减少重复请求 |
| P1 | 重页面与画布代码分割，适度预加载 | 减轻首次打开负担 |
| P1 | 任务中心复用活动任务查询策略，统一阶段反馈 | 停留页面时状态能继续更新 |
| P2 | 实测后优化大列表与草稿持久化，统一按钮/骨架/提示 | 提升长列表、连续输入和跨页面的一致性 |

验收应在同机、同浏览器、相同生产构建与数据集下记录首次/再次导航、点击详情、连续快速切换和保存四类流程，包含正常与慢网络。关注点击至第一次可见反馈、网络请求数及重复请求、主线程长任务、布局位移、缓存更新正确性。可把“点击后 100 ms 内出现明确反馈”作为设计目标，但本次没有测得该指标，也不把它当成外部项目的性能事实。

不要拿本地开发态与外部部署站点直接比较；不要将 Go 与 Python、Bun 与 npm、或组件库名称当作流畅程度的单一解释。New API 以管理页面为主，本项目还有图片解码、画布和耗时生成任务，这些负载需要单独测量。


## 实施结果（2026-09-24）

上述工作台调整和读取体验优化已落实。详细验证、现存测试失败的基线复现和构建体积见 [实施计划与验收记录](../superpowers/plans/2026-09-24-workspace-interaction.md)。本报告前文保留调研时的现状分析；详情竞态现已用延迟响应测试覆盖，未将包体积变化当作交互耗时测量结果。
