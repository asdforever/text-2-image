## 1. 类型定义扩展

- [ ] 1.1 在 `src/api/contracts.ts` 添加 `"hero"` 到 `OutputTarget` 类型联合，验证：TypeScript 编译通过且工作台代码可以引用 `"hero"` 类型
- [ ] 1.2 在 `src/api/contracts.ts` 添加 `"hero"` 到 `AssetType` 类型联合（如果是独立定义），验证：Asset 接口可以使用 `type: "hero"`
- [ ] 1.3 在 `src/types/asset.ts` 同步更新 Asset 类型定义（如有重复定义），验证：grep 搜索确认所有 AssetType 定义都包含 `"hero"`
- [ ] 1.4 添加 `SuiteTask` 类型定义（如不存在），包含 `id`, `name`, `moduleType`, `status`, `progress`, `position: {x: number, y: number}` 字段，验证：类型定义导出且可被 XYFlow 组件使用

## 2. Mock 数据扩展

- [ ] 2.1 在 `src/api/fixtures.ts` 创建 `mockGenerateHeroImage(assetId: string, params: { ratio: string, sellingPoint?: string, template: string })` 函数，验证：函数导出且类型检查通过
- [ ] 2.2 实现 mock 生成逻辑：延迟 2 秒后返回，模拟异步生成流程，验证：调用函数后 2 秒内返回 resolved Promise

## 3. 主图工作区组件 - 双栏布局

- [ ] 3.1 创建 `src/pages/HeroImageWorkspace.tsx`，采用双栏布局结构（CSS Grid），验证：文件创建成功且可以被 import
- [ ] 3.2 定义组件根元素样式：`display: grid; grid-template-columns: 360px 1fr;`，验证：渲染后显示左右两栏
- [ ] 3.3 创建左侧配置面板 `<aside className="config-panel">`，验证：左侧面板宽度固定为 360px
- [ ] 3.4 创建右侧结果画布 `<main className="result-canvas">`，验证：右侧画布占据剩余空间

### 3A. 左侧配置面板 - 产品素材选择器

- [ ] 3.5 在配置面板顶部添加产品素材选择器区域，显示白底图缩略图网格，验证：显示所有 type 为 "base" 的素材
- [ ] 3.6 实现缩略图点击选中逻辑，添加 `selectedBaseIds` state，验证：点击缩略图后高亮显示
- [ ] 3.7 支持 Ctrl/Cmd 多选缩略图，验证：按住 Ctrl 点击可选中多张

### 3B. 左侧配置面板 - 生成参数配置

- [ ] 3.8 添加生成参数 state：`ratio`（默认 "1:1"）、`sellingPoint`（默认 ""）、`template`（默认 "电商主图标准版"），验证：组件初始化时三个 state 都有默认值
- [ ] 3.9 在配置面板添加比例选择器 `<select>`，选项：1:1 方形 / 3:4 竖版 / 16:9 横版，验证：下拉框显示且可切换
- [ ] 3.10 添加卖点输入框 `<input placeholder="输入核心卖点（可选，最多50字）">`，验证：输入框显示且可输入
- [ ] 3.11 添加模板选择器 `<select>`，选项：电商主图标准版 / 场景化主图 / 简约风主图，验证：下拉框显示且可切换

### 3C. 左侧配置面板 - 批量生成按钮

- [ ] 3.12 在配置面板底部添加 `<Button onClick={handleBatchGenerate}>批量生成主图</Button>`，验证：按钮显示
- [ ] 3.13 实现按钮禁用逻辑：当 `selectedBaseIds.length === 0` 时禁用，验证：未选中素材时按钮为禁用状态
- [ ] 3.14 实现 `handleBatchGenerate` 函数：为每个选中的白底图创建 hero 类型素材，验证：点击后创建对应数量的 hero 素材

### 3D. 右侧结果画布 - 主图网格

- [ ] 3.15 在右侧画布中过滤 hero 类型素材：`project.assets.filter(asset => asset.type === "hero")`，验证：只显示 hero 类型素材
- [ ] 3.16 使用 TanStack Virtual 实现虚拟滚动网格（复用 BaseImageWorkspace 的网格逻辑），验证：网格正常滚动
- [ ] 3.17 添加空状态 UI：当 hero 素材为空时显示"暂无主图，请从左侧选择白底图开始生成"，验证：空状态文案正确显示
- [ ] 3.18 实现 `generate` 函数调用 `mockGenerateHeroImage`，传入 ratio、sellingPoint、template 参数，验证：生成时 console.log 输出包含三个参数值
- [ ] 3.19 更新生成完成后的版本模板字段为所选模板名称，验证：生成后资产的 `versions[].template` 字段值为用户选择的模板

## 4. 详情套图工作区组件 - 双栏布局 + XYFlow

- [ ] 4.1 创建或重构 `src/pages/SuiteImageWorkspace.tsx`，采用双栏布局结构（CSS Grid），验证：文件创建成功
- [ ] 4.2 定义组件根元素样式：`display: grid; grid-template-columns: 360px 1fr;`，验证：渲染后显示左右两栏
- [ ] 4.3 创建左侧配置面板 `<aside className="config-panel">`，验证：左侧面板宽度固定为 360px
- [ ] 4.4 创建右侧画布区域 `<main className="flow-canvas">`，验证：右侧画布占据剩余空间

### 4A. 左侧配置面板 - 模块配置

- [ ] 4.5 添加模块配置区域，包含复选框组：开箱展示 / 细节特写 / 使用场景 / 产品参数，验证：复选框显示
- [ ] 4.6 添加 `selectedModules` state 存储勾选的模块，验证：勾选后 state 正确更新
- [ ] 4.7 实现复选框交互逻辑，验证：勾选/取消勾选可切换模块启用状态

### 4B. 左侧配置面板 - 创作指令输入

- [ ] 4.8 添加创作指令文本框 `<textarea placeholder="把完整的创作指令写在这里..." maxLength={2000}>`，验证：文本框显示且可输入
- [ ] 4.9 添加字数统计显示 `<small>{prompt.length}/2000</small>`，验证：字数实时更新
- [ ] 4.10 实现输入限制：超过 2000 字阻止输入，验证：输入到 2000 字时无法继续输入

### 4C. 左侧配置面板 - 营销词库

- [ ] 4.11 添加营销词库区域，显示快捷标签（高端质感 / 简约设计 / 匠心工艺等），验证：标签云显示
- [ ] 4.12 实现标签点击插入逻辑：点击标签将词汇插入到文本框光标位置，验证：点击后词汇插入正确

### 4D. 左侧配置面板 - 生成规划按钮

- [ ] 4.13 在配置面板底部添加 `<Button onClick={handleGeneratePlan}>生成详情页规划</Button>`，验证：按钮显示
- [ ] 4.14 实现按钮禁用逻辑：当 `selectedModules.length === 0` 时禁用，验证：未勾选模块时按钮为禁用状态
- [ ] 4.15 实现 `handleGeneratePlan` 函数：为每个勾选的模块创建 SuiteTask，验证：点击后创建对应数量的任务节点

### 4E. 右侧 XYFlow 画板

- [ ] 4.16 检查是否存在 `src/components/TaskCanvas.tsx` 组件，验证：文件存在且使用 @xyflow/react
- [ ] 4.17 在右侧画布中引入 `<TaskCanvas tasks={suiteTasks} onSelect={...} onDoubleClick={...} />`，验证：画板渲染
- [ ] 4.18 实现任务节点数据转换：将 SuiteTask 转换为 ReactFlow Node 格式，验证：节点在画板中正确显示
- [ ] 4.19 实现节点状态样式：pending（灰色）/ generating（蓝色+进度条）/ ready（绿色），验证：不同状态显示不同样式
- [ ] 4.20 实现节点拖拽逻辑：更新 task.position 字段，验证：拖拽后位置保存
- [ ] 4.21 实现节点点击选中：高亮选中节点，左侧面板显示任务详情，验证：点击节点后高亮显示
- [ ] 4.22 实现节点双击编辑：弹出对话框编辑任务名称和参数，验证：双击后对话框显示
- [ ] 4.23 添加空状态 UI：当无任务时显示"暂无详情页任务，请从左侧配置模块并生成规划"，验证：空状态文案正确显示

## 5. 工作台标签调整

- [ ] 5.1 在 `src/pages/ProjectWorkbench.tsx` 定义标签文本映射对象 `TAB_LABELS: Record<OutputTarget, string>`，包含 base/hero/suite/video 四个键，验证：对象定义正确且类型检查通过
- [ ] 5.2 更新标签数组为 `["base", "hero", "suite", "video"]`，确保顺序正确，验证：代码中标签数组顺序为 base → hero → suite → video
- [ ] 5.3 使用 `TAB_LABELS[tab]` 替代原有的三元运算符文本映射，验证：标签文本通过对象映射获取
- [ ] 5.4 设置 suite 标签文本为"详情套图"，验证：`TAB_LABELS.suite` 的值为"详情套图"
- [ ] 5.5 设置 hero 标签文本为"主图"，验证：`TAB_LABELS.hero` 的值为"主图"
- [ ] 5.6 在标签页内容渲染逻辑中添加 hero 分支，渲染 `<HeroImageWorkspace />` 组件，验证：切换到主图标签时渲染 HeroImageWorkspace
- [ ] 5.7 在标签页内容渲染逻辑中添加/更新 suite 分支，渲染 `<SuiteImageWorkspace />` 组件，验证：切换到详情套图标签时渲染 SuiteImageWorkspace
- [ ] 5.8 导入 `HeroImageWorkspace` 和 `SuiteImageWorkspace` 组件到 `ProjectWorkbench.tsx`，验证：import 语句存在且路径正确

## 6. 样式实现

- [ ] 6.1 在 `src/index.css` 添加双栏布局样式 `.hero-workspace` 和 `.suite-workspace`，验证：样式定义存在
- [ ] 6.2 添加左侧配置面板样式 `.config-panel`（固定宽度、边框、内边距、滚动），验证：面板样式正确
- [ ] 6.3 添加右侧画布样式 `.result-canvas` 和 `.flow-canvas`（占满剩余空间、背景色），验证：画布样式正确
- [ ] 6.4 添加产品素材选择器样式 `.product-selector .thumbnail-grid`，验证：缩略图网格布局正确
- [ ] 6.5 添加生成参数表单样式 `.generation-params label, select, input`，验证：表单控件样式一致
- [ ] 6.6 添加营销词库标签样式 `.keyword-chips .chip`，验证：标签云布局正确

## 7. 项目创建默认配置

- [ ] 7.1 在 `src/store/useProjectStore.ts` 的 `createProject` 函数中，更新默认 `outputTargets` 为 `["base", "hero", "suite", "video"]`，验证：新建项目后 Zustand devtools 显示项目的 outputTargets 包含四个值

## 8. 端到端验证

- [ ] 8.1 创建新项目，验证工作台显示四个标签且顺序正确：白底图、主图、详情套图、视频
- [ ] 8.2 点击主图标签，验证显示双栏布局：左侧配置面板 + 右侧结果画布
- [ ] 8.3 验证主图工作区左侧面板显示产品素材选择器、生成参数配置、批量生成按钮
- [ ] 8.4 验证主图工作区右侧画布显示空状态："暂无主图，请从左侧选择白底图开始生成"
- [ ] 8.5 点击详情套图标签，验证标签文本显示为"详情套图"
- [ ] 8.6 验证详情套图工作区显示双栏布局：左侧配置面板 + 右侧 XYFlow 画板
- [ ] 8.7 验证详情套图工作区左侧面板显示模块配置、创作指令输入、营销词库、生成规划按钮
- [ ] 8.8 验证详情套图工作区右侧画板显示空状态："暂无详情页任务，请从左侧配置模块并生成规划"
- [ ] 8.9 在主图工作区选择白底图并点击批量生成，验证生成流程和参数传递
- [ ] 8.10 在详情套图工作区勾选模块并生成规划，验证任务节点在 XYFlow 画板中显示
- [ ] 8.11 验证详情套图任务节点可拖拽、可点击选中、可双击编辑
- [ ] 8.12 打开已有旧项目，验证主图标签显示且工作区为空状态（向后兼容性）
