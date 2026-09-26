## Context

当前项目工作台支持白底图、套图、视频三种输出类型。白底图工作区已实现素材网格、批量生成、版本历史等核心功能。套图工作区处理详情页场景。需要在两者之间插入主图工作区，并对主图和详情套图工作区采用**双栏布局**（左侧配置 + 右侧画布）。

技术栈：
- React + TypeScript
- Zustand 状态管理
- TanStack Router
- TanStack Virtual 虚拟滚动
- **@xyflow/react (v12.11.3)** - 用于详情套图的任务流程可视化
- Lucide 图标库

## Goals / Non-Goals

**Goals:**
- 新增 `hero` 类型支持，与现有类型平级
- **主图工作区采用双栏布局**：左侧配置面板 + 右侧结果网格
- **详情套图工作区重构为双栏布局**：左侧配置面板 + 右侧 XYFlow 画板（任务流程可视化）
- 标签顺序调整：base → hero → suite → video
- 套图工作区标签文本更新为"详情套图"

**Non-Goals:**
- 不涉及后端 API 修改（使用 mock 数据）
- 不重构现有 BaseImageWorkspace 组件（保持网格布局）

## Decisions

### Decision 1: 主图 OutputTarget 使用 `"hero"` 标识

**Rationale:** `hero` 在电商和营销领域是常见术语，指首屏主图或核心视觉。比 `main` 更具体，避免与"主要的"混淆。

**Alternatives:**
- `main`: 语义模糊，可能与"主要功能"混淆
- `primary`: 过于通用
- `listing`: 特定于电商平台术语，不够通用

**Chosen:** `"hero"` - 行业认可度高，语义明确

### Decision 2: 主图工作区采用双栏布局

**Rationale:** 参考业界电商图片生成工具的 UX 模式，将配置和结果分离：

**布局结构:**
```
+------------------+------------------------+
| 左侧配置面板      | 右侧结果画布            |
| (300-400px固定)  | (flex-grow占满)        |
|                  |                        |
| - 产品素材选择器  | +------------------+   |
|   [缩略图网格]    | | 主图结果网格      |   |
|                  | | (虚拟滚动)        |   |
| - 生成参数       | +------------------+   |
|   比例: [1:1▼]   |                        |
|   卖点: [____]   |                        |
|   模板: [___▼]   |                        |
|                  |                        |
| [批量生成]       |                        |
+------------------+------------------------+
```

**优势:**
- 配置区域固定可见，减少滚动操作
- 结果区域最大化，适合展示多张主图
- 符合用户从参考图中认知的交互模式

**Implementation:**
- 创建 `src/pages/HeroImageWorkspace.tsx`
- 根元素使用 `display: grid; grid-template-columns: 360px 1fr;`
- 左侧面板：产品素材选择器（基于 base 类型素材）+ 生成参数表单
- 右侧画布：复用 TanStack Virtual 网格展示 hero 类型结果

### Decision 3: 详情套图工作区重构为双栏布局 + XYFlow 画板

**Rationale:** 详情页套图本质是**多模块任务流程**（开箱 → 细节 → 场景 → 参数...），而非简单的图片列表。当前代码已有 `TaskCanvas` 组件（使用 @xyflow/react），可复用于可视化任务编排。

**布局结构:**
```
+------------------+------------------------+
| 左侧配置面板      | 右侧 XYFlow 画板        |
| (300-400px固定)  | (flex-grow占满)        |
|                  |                        |
| - 组图配置       |   +---------------+    |
|   模块: [✓]开箱  |   | [开箱] -----> |    |
|         [✓]细节  |   |   |           |    |
|         [ ]场景  |   |   v           |    |
|                  |   | [细节]        |    |
| - 创作指令       |   +---------------+    |
|   [文本框]       |   (ReactFlow 画板)     |
|   最多2000字     |                        |
|                  |                        |
| - 营销词库       |                        |
|   [快捷标签]     |                        |
|                  |                        |
| [生成详情页规划]  |                        |
+------------------+------------------------+
```

**优势:**
- 任务依赖关系可视化（节点连线）
- 支持拖拽调整任务顺序
- 节点状态实时反馈（待处理/生成中/已完成）
- 复用现有 `TaskCanvas` 组件（已实现节点拖拽、连线、点击编辑）

**Implementation:**
- 重构 `src/pages/SuiteImageWorkspace.tsx`（如不存在则创建）
- 左侧面板：模块配置 + 创作指令输入 + 词库快捷插入
- 右侧画布：`<TaskCanvas tasks={tasks} onSelect={...} onDoubleClick={...} />`
- 复用现有 `SuiteTask` 类型（已有 `position`, `status`, `progress` 字段）

### Decision 4: 标签文本映射采用内联对象

**Rationale:** 当前代码使用三元运算符映射标签文本：
```typescript
{tab === "base" ? "Base images" : tab === "suite" ? "Suite" : "Video"}
```

改为对象映射更清晰：
```typescript
const TAB_LABELS: Record<OutputTarget, string> = {
  base: "白底图",
  hero: "主图",
  suite: "详情套图",
  video: "视频"
};
```

### Decision 5: 项目创建默认包含所有四种输出类型

**Rationale:** 与之前的重构保持一致（移除输出目标选择步骤），新项目默认启用所有工作区。

**Implementation:**
```typescript
outputTargets: ["base", "hero", "suite", "video"]
```

### Decision 6: 使用 mock 生成函数，不涉及后端 API

**Rationale:** 后端 API 和提示词系统在另一个模块，本次变更聚焦前端工作区结构调整。

**Implementation:**
- 创建 `mockGenerateHeroImage` 函数
- 模拟生成流程：设置 status 为 "generating" → 延迟 → 更新为 "ready"
- 生成结果包含比例、卖点、模板信息

## Risks / Trade-offs

**Risk: 主图和详情套图功能重叠**
- Mitigation: 通过 specs 明确定位 - 主图聚焦首屏转化（1-6张），详情套图聚焦完整故事叙事（多图组合）

**Risk: 标签文本变更可能影响用户已有的工作流习惯**
- Mitigation: "套图" → "详情套图" 是语义澄清，不改变功能。数据结构中的 `suite` 类型保持不变

**Risk: 四个标签可能导致标签栏拥挤**
- Mitigation: 当前标签栏有足够空间。如果未来需要更多标签，考虑下拉菜单或标签分组

**Risk: 双栏布局在小屏幕设备上可能拥挤**
- Mitigation: 左侧面板固定 360px，右侧画布自适应。最小支持 1280px 宽度（常见笔记本屏幕）
- 后续可考虑响应式：在小屏设备上左侧面板可折叠

**Risk: 详情套图工作区重构可能破坏现有用户流程**
- Mitigation: 保持 `SuiteTask` 数据结构不变，仅更新 UI 呈现方式
- 现有的任务创建、编辑、生成逻辑保持兼容

**Trade-off: XYFlow 画板学习成本**
- 优势: 任务流程可视化、依赖关系清晰、支持拖拽调整
- 劣势: 用户需要学习节点操作（拖拽、连线）
- Mitigation: 保留传统列表视图作为备选，或在画板上添加操作提示

**Trade-off: 复制代码 vs 抽象公共组件**
- 选择：主图工作区初期独立实现双栏布局
- 原因：主图和白底图虽然都是图片生成，但交互模式不同（白底图：批量网格选择；主图：配置驱动生成）
- 后续优化：如果发现布局模式相似，可抽取 `TwoColumnWorkspace` 公共布局组件

## Migration Plan

1. **类型定义扩展** - 添加 `"hero"` 到 OutputTarget 和 AssetType 联合类型
2. **Mock 函数扩展** - 添加 mockGenerateHeroImage
3. **主图工作区组件** - 创建双栏布局的 HeroImageWorkspace
4. **详情套图工作区重构** - 改为双栏布局 + XYFlow 画板
5. **工作台路由更新** - 调整标签数组和文本映射
6. **默认项目配置** - 更新 useProjectStore 的项目创建逻辑

**向后兼容:**
- 现有项目数据中没有 `hero` 类型素材，主图工作区显示为空状态
- 现有的 `suite` 类型素材继续在详情套图工作区正常显示
- 标签文本变更不影响数据结构
- SuiteTask 数据结构保持不变，只更新渲染方式（从列表到 XYFlow 画板）

**验证步骤:**
1. 创建新项目，确认四个标签页都可访问
2. 主图工作区：验证双栏布局，左侧配置面板，右侧结果网格
3. 主图工作区：验证生成参数（比例/卖点/模板）配置和生成流程
4. 详情套图工作区：验证双栏布局，左侧配置面板，右侧 XYFlow 画板
5. 详情套图工作区：验证任务节点显示、拖拽、连线、状态更新
6. 验证详情套图标签文本显示为"详情套图"
7. 打开已有项目，确认数据兼容性

## Component Structure

### HeroImageWorkspace 组件结构
```typescript
<div className="hero-workspace">
  <aside className="config-panel">
    {/* 产品素材选择器 */}
    <section className="product-selector">
      <h3>产品素材</h3>
      <div className="thumbnail-grid">
        {baseAssets.map(asset => <Thumbnail ... />)}
      </div>
    </section>
    
    {/* 生成参数 */}
    <section className="generation-params">
      <label>比例</label>
      <select value={ratio} onChange={...}>
        <option value="1:1">1:1 方形</option>
        <option value="3:4">3:4 竖版</option>
        <option value="16:9">16:9 横版</option>
      </select>
      
      <label>核心卖点</label>
      <input value={sellingPoint} onChange={...} />
      
      <label>模板</label>
      <select value={template} onChange={...}>
        <option>电商主图标准版</option>
        <option>场景化主图</option>
        <option>简约风主图</option>
      </select>
      
      <Button onClick={handleGenerate}>批量生成主图</Button>
    </section>
  </aside>
  
  <main className="result-canvas">
    {/* 虚拟滚动网格 */}
    <VirtualGrid assets={heroAssets} />
  </main>
</div>
```

### SuiteImageWorkspace 组件结构
```typescript
<div className="suite-workspace">
  <aside className="config-panel">
    {/* 模块配置 */}
    <section className="module-config">
      <h3>详情页模块</h3>
      <CheckboxGroup value={modules} onChange={...}>
        <Checkbox value="unbox">开箱展示</Checkbox>
        <Checkbox value="detail">细节特写</Checkbox>
        <Checkbox value="scene">使用场景</Checkbox>
        <Checkbox value="specs">产品参数</Checkbox>
      </CheckboxGroup>
    </section>
    
    {/* 创作指令 */}
    <section className="creation-prompt">
      <label>创作指令 (专业版)</label>
      <textarea 
        value={prompt} 
        onChange={...}
        placeholder="把完整的创作指令写在这里：构图、拍摄风格、配色..."
        maxLength={2000}
      />
      <small>{prompt.length}/2000</small>
    </section>
    
    {/* 营销词库 */}
    <section className="keyword-library">
      <h3>营销词库</h3>
      <div className="keyword-chips">
        <Chip onClick={insertKeyword}>高端质感</Chip>
        <Chip onClick={insertKeyword}>简约设计</Chip>
        ...
      </div>
    </section>
    
    <Button onClick={handleGenerateSuite}>生成详情页规划</Button>
  </aside>
  
  <main className="flow-canvas">
    {/* XYFlow 画板 */}
    <TaskCanvas 
      tasks={suiteTasks}
      onSelect={handleSelectTask}
      onDoubleClick={handleEditTask}
    />
  </main>
</div>
```

### CSS Grid 布局
```css
.hero-workspace,
.suite-workspace {
  display: grid;
  grid-template-columns: 360px 1fr;
  height: 100%;
  gap: 0;
}

.config-panel {
  background: var(--surface-1);
  border-right: 1px solid var(--border);
  padding: 24px;
  overflow-y: auto;
}

.result-canvas,
.flow-canvas {
  background: var(--surface-0);
  overflow: hidden;
}
```
