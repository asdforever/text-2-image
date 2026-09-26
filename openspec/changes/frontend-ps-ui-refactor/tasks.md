## 1. 项目初始化与依赖配置

- [x] 1.1 安装 shadcn/ui 初始化脚本并配置 Tailwind CSS，验证 `tailwind.config.js` 和 `components.json` 文件生成
- [x] 1.2 安装核心依赖（TanStack Router、Zustand、react-window、react-resizable-panels、react-hotkeys-hook），验证 `package.json` 更新且 `npm install` 无报错
- [x] 1.3 复制 shadcn/ui 基础组件到 `src/components/ui/`（Button、Dialog、Tabs、Select、Input、Textarea），验证组件文件存在且可导入
- [x] 1.4 配置 TanStack Router 并创建路由文件结构 `src/routes/`，验证 `npm run dev` 启动无报错

## 2. Mock 数据与 Fixtures

- [x] 2.1 扩展 `src/api/fixtures.ts`，添加 `mockProjects`、`mockBaseImages`、`mockSuiteTasks` 数据结构，验证类型符合 `src/api/contracts.ts`
- [x] 2.2 添加 mock 操作函数（`mockGenerateBaseImage`、`mockGenerateSuite` 等），使用 `setTimeout` 模拟 2 秒延迟，验证函数返回 Promise 且延迟生效
- [x] 2.3 在 `public/mock-assets/` 放置预设图片资源（白底图样例、套图样例各 5 张），验证浏览器可访问 `/mock-assets/base-1.png`
- [x] 2.4 创建 Zustand store `src/store/useProjectStore.ts`，定义 `projects`、`currentProjectId`、`selectedAssetId` 状态和 actions，验证 `useProjectStore()` 可在组件中调用

## 3. 欢迎页与项目管理

- [x] 3.1 创建 `src/pages/WelcomePage.tsx`，展示项目列表（从 Zustand store 读取），验证空状态时显示“暂无项目”提示
- [x] 3.2 创建 `src/components/ProjectCreateDialog.tsx`，实现三步表单（上传图片 / 选择输出目标 / 填写基础信息），验证点击“创建项目”后 Zustand store 新增项目
- [x] 3.3 在 `WelcomePage` 添加项目卡片点击跳转逻辑，验证点击后路由跳转到 `/projects/:id`
- [x] 3.4 在 `WelcomePage` 底部添加快速启动按钮（批量去背景 / 生成套图），验证点击后弹出简化对话框并创建对应类型项目

## 4. 工作台布局与路由

- [x] 4.1 创建 `src/pages/ProjectWorkbench.tsx`，使用 CSS Grid 实现三栏布局（60px / 1fr / 280px），验证布局在 1440px 屏幕下正常显示
- [x] 4.2 在 `ProjectWorkbench` 顶部添加 tab 栏（白底图 / 套图 / 视频），使用 TanStack Router 的 `useSearch()` 管理 `?tab=` 参数，验证点击 tab 后 URL 更新且工作区切换
- [x] 4.3 集成 `react-resizable-panels`，使右侧面板可拖拽调整宽度（200-400px）和收起，验证拖拽手柄显示且交互流畅
- [x] 4.4 创建 `src/components/Toolbar.tsx`，根据当前 tab 动态显示不同工具按钮，验证在白底图 tab 显示“批量选择”按钮，套图 tab 显示“生成套图”按钮
- [x] 4.5 使用 `react-hotkeys-hook` 添加 `Ctrl+Tab` 快捷键切换 tab，验证按键触发 tab 切换

## 5. 右侧面板（资产库与历史）

- [x] 5.1 创建 `src/components/AssetLibraryPanel.tsx`，按类型分组展示资产（原图 / 白底图 / 套图 / 视频），验证折叠/展开交互正常
- [x] 5.2 在资产库顶部添加搜索框和筛选器，验证输入“充电宝”后列表只显示匹配资产
- [x] 5.3 实现资产卡片点击定位功能，验证点击白底图卡片时切换到白底图 tab 并滚动到对应卡片
- [x] 5.4 创建 `src/components/HistoryVersionPanel.tsx`，以时间线形式展示选中资产的版本，验证未选中资产时显示空状态提示
- [x] 5.5 在历史面板添加版本对比功能（选中两个版本并排显示），验证对比视图正常显示差异

## 6. 白底图工作区

- [x] 6.1 创建 `src/pages/BaseImageWorkspace.tsx`，使用 `react-window` 或 `@tanstack/react-virtual` 实现虚拟滚动网格，验证 100 张图片时滚动流畅（60fps）
- [x] 6.2 创建图片卡片组件 `src/components/BaseImageCard.tsx`，显示缩略图 / 文件名 / 尺寸 / 状态，验证悬浮时显示操作按钮
- [x] 6.3 实现单张生成白底图功能：点击按钮弹出模板选择对话框，选择后调用 `mockGenerateBaseImage`，验证卡片状态变为“生成中”再变为“已生成”
- [x] 6.4 实现批量选择交互：点击工具栏“批量选择”按钮后，图片卡片左上角显示选中框，验证选中 3 张后工具栏显示“已选 3 张”
- [x] 6.5 实现批量生成白底图：选中多张图片后点击“生成白底图”，验证对话框提示“将对 3 张图片应用相同模板”，确认后所有选中图片并发生成
- [x] 6.6 实现导出功能：单张图片点击“导出”按钮下载文件，批量选中后点击“导出”下载 ZIP，验证下载文件名正确

## 7. 套图工作区 - 配置审核界面

- [x] 7.1 创建 `src/pages/SuiteWorkspace.tsx`，使用 `useState` 管理 `'config' | 'canvas'` 状态，验证状态切换时组件正确渲染
- [x] 7.2 创建 `src/components/SuiteConfigPanel.tsx`，表单包含平台 / 语言 / 主图数量 / 详情图数量 / 类别选择，验证所有字段可输入且值保存到 Zustand store
- [x] 7.3 添加商品资料（RAG）搜索框，输入关键词后显示 mock Chunk 列表，验证勾选后 Chunk 添加到已选列表
- [x] 7.4 添加“人工补充事实”文本框，验证输入内容保存到 Zustand store
- [x] 7.5 实现“生成结构计划”按钮：点击后调用 `mockGeneratePlan`（2 秒延迟），验证按钮变为“生成中...”并禁用表单
- [x] 7.6 创建结构计划审核界面，显示主图分配 / 详情图类别分配 / 全局风格卡 / 缺失事实，验证用户可点击“编辑”按钮修改内容
- [x] 7.7 实现“确认并生成提示词”按钮：点击后调用 `mockGenerateCategoryPrompts`，验证生成成功后状态切换到 `'canvas'`

## 8. 套图工作区 - 画布视图

- [x] 8.1 从现有 `src/pages/WorkbenchBoardPage.tsx` 提取画布逻辑，创建 `src/components/TaskCanvas.tsx` 组件，验证 XYFlow 节点和连线正常渲染
- [x] 8.2 创建 `src/components/SuiteCanvasView.tsx`，嵌入 `TaskCanvas` 并添加顶部工具栏（批量生成 / 调整布局 / 重新规划），验证工具栏按钮显示
- [x] 8.3 实现画布节点数据绑定：从 Zustand store 读取任务卡数据，映射为 XYFlow 节点，验证节点显示标题 / 类别 / 状态
- [x] 8.4 实现节点点击事件：点击任务卡节点时更新 Zustand store 的 `selectedAssetId`，验证右侧面板切换为该任务卡详情
- [x] 8.5 实现批量生成按钮：点击后遍历所有任务卡调用 `mockGenerateSuite`，验证所有节点状态变为“生成中”再逐个完成
- [x] 8.6 实现单卡生成：在右侧面板点击某任务卡的“生成”按钮，验证只有该节点状态更新
- [x] 8.7 实现“重新规划”按钮：点击后状态切换回 `'config'`，验证配置表单预填上次的值

## 9. 图片编辑器集成

- [x] 9.1 创建 `src/components/ImageEditorDialog.tsx`，弹窗形式包裹现有 Konva 编辑器，验证双击生成结果节点时对话框打开
- [x] 9.2 将现有 `src/pages/WorkbenchBoardPage.tsx` 中的 Konva 编辑逻辑迁移到新对话框，验证编辑工具栏（添加文字 / 局部重绘 / 消除）正常显示
- [x] 9.3 实现编辑保存逻辑：点击“保存”按钮后调用 `mockEditImage`（生成新版本），验证画布上生成结果节点下方新增“编辑版本 v2”子节点

## 10. 视频工作区占位

- [x] 10.1 创建 `src/pages/VideoWorkspace.tsx`，显示“敬请期待”占位内容，验证切换到视频 tab 时显示该组件
- [x] 10.2 在工具栏添加视频 tab 的占位按钮，点击后显示 toast “功能开发中”，验证交互响应

## 11. 样式与主题

- [x] 11.1 配置 Tailwind 暗色主题（`darkMode: 'class'`），在 `<html class="dark">` 上启用，验证所有组件使用暗色背景
- [x] 11.2 自定义 Tailwind 调色板（PS 风格灰色系），验证 `bg-gray-900` 等 class 生效
- [x] 11.3 为 XYFlow 节点创建 CSS Module 样式 `src/components/TaskCanvas.module.css`，验证节点边框 / 阴影 / 悬浮效果符合 PS 风格
- [x] 11.4 调整全局间距为紧凑模式（Tailwind spacing 缩放 0.8 倍），验证 UI 间距符合设计稿

## 12. 数据持久化（可选）

- [x] 12.1 添加 Zustand persist middleware，将 store 持久化到 localStorage，验证刷新页面后项目列表不丢失
- [x] 12.2 添加“清除所有数据”按钮（在用户菜单中），验证点击后 localStorage 清空且项目列表恢复空状态

## 13. 端到端验收

- [x] 13.1 完整走通用户旅程 1：欢迎页 → 新建项目（上传 3 张图）→ 白底图 tab 批量生成 → 导出，验证所有步骤无报错且文件下载成功
- [x] 13.2 完整走通用户旅程 2：欢迎页 → 新建项目 → 套图 tab → 填写配置 → 生成结构计划 → 审核确认 → 画布视图批量生成 → 双击生成结果编辑，验证所有步骤无报错
- [x] 13.3 验证 tab 切换：在白底图 / 套图 / 视频 tab 间切换，验证工作区内容正确渲染且右侧面板同步更新
- [x] 13.4 验证右侧面板：点击资产库中不同资产，验证定位功能正常；切换到历史 tab，验证版本时间线显示
- [x] 13.5 验证键盘快捷键：按 `Ctrl+Tab` 切换 tab，按 `Escape` 关闭对话框，验证所有快捷键响应
- [ ] 13.6 性能验证：在白底图工作区模拟 100 张图片，验证滚动流畅（Chrome DevTools Performance 面板 60fps）
- [x] 13.7 响应式验证：在 1440x900 和 1920x1080 分辨率下测试，验证布局不错位且右侧面板可收起

## 14. 文档与交付

- [x] 14.1 更新 `README.md`，添加“运行前端 Demo”章节（`npm install` → `npm run dev`），验证按文档操作可启动项目
- [x] 14.2 添加 `docs/UI-DEMO.md`，截图展示三栏布局 / 白底图工作区 / 套图画布 / 资产库面板，验证文档图片清晰可见
- [x] 14.3 录制演示视频（3-5 分钟），覆盖完整用户旅程，验证视频上传到项目 `artifacts/` 目录
