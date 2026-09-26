## Why

现有 PicAgent 套图工作台采用"流程页面式"交互，用户需要在多个页面间跳转完成上传、白底精修、规划、生成套图等步骤。这种设计适合批量 SOP 生产，但存在以下问题：

- **心智模型不匹配**：用户期望"项目容器"概念（类似 Photoshop 文件），但现有 Suite 只对应"一次套图生产"，无法在同一项目内同时产出白底图、套图、视频等多种资产
- **缺少并行操作能力**：流程式页面强制线性操作，用户无法快速回溯或同时查看多个阶段的资产
- **资产管理分散**：原图、白底图、生成结果散落在不同页面，缺少统一的资产库视图
- **工具触达性差**：AI 生成能力（去背景、生成套图、图片编辑）隐藏在流程节点中，不够直观

目标：构建 **PS 风格的电商 AI 工作台**，以项目为中心，采用三栏布局（工具栏 + 工作区 + 资产库），支持白底图、套图、视频三种产物的独立或组合生产。

## What Changes

- **新建 Project 顶层概念**：替代现有 Suite 作为用户的核心工作单元，一个 Project 可包含白底图、套图、视频等多种产物
- **新建三栏工作台布局**：左侧工具栏（动作触发器）+ 中间工作区（随 tab 切换形态）+ 右侧资产库与历史面板
- **新建白底图工作区**：网格/列表视图展示所有原图和白底图，支持批量选择、批量生成白底图、单张编辑
- **新建套图工作区**：包含两个子界面状态
  - 配置审核界面：填写套图参数（平台/类别/商品资料）、生成并审核结构计划、生成类别提示词
  - 画布视图：XYFlow 节点展示任务卡、生成结果、编辑历史的血缘关系，支持拖拽布局、单卡操作
- **新建视频工作区**：UI 占位，显示"敬请期待"提示
- **新建统一资产库面板**：右侧面板展示项目内所有资产（原图/白底图/套图/视频），按类型分组，支持筛选和快速定位
- **新建历史/版本面板**：展示当前选中资产的版本历史和操作记录
- **重构前端路由**：从多页面（`/suites/:id` → `/suites/:id/board`）改为单工作台多 tab（`/projects/:id?tab=base|suite|video`）
- **本次不涉及后端改动**：UI 使用 mock 数据（`src/api/fixtures.ts`）验证交互流程，后端 API 对接留待后续 change

## Capabilities

### New Capabilities

- `project-management`: 项目生命周期管理 UI（欢迎页、新建项目对话框、项目列表）
- `workspace-layout`: 三栏工作台布局系统（顶部 tab 栏、左侧工具栏、中间工作区容器、右侧面板）
- `base-image-workspace`: 白底图工作区 UI（网格视图、批量操作、单张精修入口）
- `suite-workspace`: 套图工作区 UI（配置审核子界面 + XYFlow 画布视图的状态切换）
- `asset-library-panel`: 统一资产库面板（跨 tab 共享，展示项目内所有资产并支持交互）
- `history-version-panel`: 历史/版本面板（展示选中资产的版本链和操作时间线）

### Modified Capabilities

（无，本次为纯前端 UI 构建，不修改现有后端能力）

## Impact

- **前端代码**：`src/` 目录几乎完全重构
  - 保留：`src/api/contracts.ts`（类型定义供参考）、`src/api/fixtures.ts`（扩展为完整 mock 数据源）
  - 新建：`src/pages/ProjectWorkbench.tsx`（工作台主容器）、`src/components/workspace/*`（工作区组件）、`src/components/panels/*`（面板组件）
  - 移除或归档：现有 `StartPage.tsx`、`WorkbenchBoardPage.tsx`（逻辑保留，重新组织）
- **路由变更**：`/suites/*` 路径废弃，新路由为 `/projects/:id?tab=base|suite|video`
- **样式系统**：可能引入组件库（如 shadcn/ui、Ant Design）或重写 CSS，需在 design.md 中确定
- **后端 API**：本次 change **不改动**，所有数据交互使用 fixtures 模拟
- **数据迁移**：暂不考虑（UI 验证通过后，后续 change 处理 Suite → Project 的数据映射）
- **现有用户**：**破坏性变更**，旧 URL 将失效，需在后续集成时考虑兼容层或迁移提示
