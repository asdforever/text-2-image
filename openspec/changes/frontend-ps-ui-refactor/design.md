## Context

现有前端采用 React 19 + Vite 8，手写 History API 路由，页面组件单文件实现（`StartPage.tsx` 513 行、`WorkbenchBoardPage.tsx` 380 行），样式分散在 `public/assets/*.css`，API 调用通过 `src/api/client.ts` 手写 fetch。

本次重构为**纯前端 UI 构建**，不涉及后端 API 改动，所有数据交互使用 `src/api/fixtures.ts` mock。现有后端（Node + tsx + PostgreSQL + MinIO）保持运行，但前端暂不调用，待后续独立 change 对接 FastAPI 新后端。

关键约束：
- 必须保持 React 生态（团队技能栈）
- 三栏布局需要支持面板收起/展开、拖拽调整
- XYFlow 画布已在现有 `WorkbenchBoardPage` 中使用，需复用其节点/连线逻辑
- Konva 图片编辑器已实现，需嵌入新 UI

## Goals / Non-Goals

**Goals:**
- 构建完整的 PS 风格三栏布局 UI 壳（工具栏 + 工作区 + 侧边面板）
- 实现三个工作区的视觉和交互（白底图网格、套图配置+画布、视频占位）
- 使用 mock 数据验证所有交互流程（项目创建、tab 切换、批量操作、节点点击）
- 产出可独立运行的前端 demo，能在浏览器中完整演示用户旅程

**Non-Goals:**
- 真实后端 API 集成（留待 `backend-fastapi-migration` 和 `frontend-backend-integration` change）
- 真实图片生成（mock 数据返回预设图片 URL）
- 数据持久化（刷新页面丢失状态，localStorage 可选）
- 移动端适配（明确桌面端产品）
- 完整的错误边界和生产级优化（demo 阶段）

## Decisions

### 决策 1：组件库选择 - shadcn/ui

**选择：** 使用 shadcn/ui（基于 Radix UI + Tailwind CSS）

**理由：**
- **复制粘贴式组件**：代码直接进 `src/components/ui/`，完全可控，不像 Ant Design 打包体积大且样式难覆盖
- **Headless 架构**：Radix UI 提供无样式的可访问性组件（Dialog、Dropdown、Tabs），我们用 Tailwind 自定义视觉
- **PS 风格适配性强**：暗色主题、扁平化图标、紧凑间距都可以通过 Tailwind 配置实现
- **React 19 兼容**：shadcn/ui 已支持 React 19

**替代方案：**
- Ant Design：过于"企业后台"风格，与 PS 视觉不符，且 CSS-in-JS 与我们想要的 Tailwind 冲突
- MUI：同样偏企业风格，定制成本高
- 纯手写：开发周期长，可访问性需自行实现

**Trade-off：** Tailwind 会增加 HTML class 数量，但换来样式的可预测性和快速迭代。

---

### 决策 2：路由方案 - TanStack Router

**选择：** 使用 TanStack Router 替代手写 History API

**理由：**
- **类型安全**：路由参数自动推导 TS 类型（`/projects/:id?tab=base` 的 `id` 和 `tab` 参数有类型）
- **嵌套路由**：工作台三栏布局是 layout route，各 tab 是 child route，代码组织清晰
- **搜索参数管理**：`?tab=base|suite|video` 用 `useSearch()` hook 管理，比手写 URLSearchParams 简洁
- **代码分割**：天然支持路由级 lazy loading

**替代方案：**
- React Router v6：功能相似，但类型安全不如 TanStack Router
- 继续手写：现有 `App.tsx` 28 行已难以扩展，新增 tab 需手动同步多处

**Trade-off：** 增加一个新依赖（~50KB gzipped），但换来类型安全和可维护性。

---

### 决策 3：状态管理 - Zustand + 本地 mock store

**选择：** Zustand 管理全局状态（当前项目、选中资产、UI 状态），mock 数据存 Zustand store

**理由：**
- **轻量**：Zustand 核心只有 1KB，API 极简（`create()` + `useStore()`）
- **无 Context 层级**：不像 Redux 需要 Provider 包裹，直接 `import useStore`
- **适合 mock 场景**：`actions` 里写 mock 逻辑（如 `generateBaseImage()` 返回预设 fixture），后续替换成真实 API 调用时只改 actions 内部实现

**替代方案：**
- Redux Toolkit：过于重型，demo 阶段不需要 middleware、devtools、时间旅行
- Jotai/Recoil：原子化状态适合细粒度共享，但我们的状态本来就是粗粒度（整个 Project 对象）
- React Context：跨多个 tab 传递状态会导致 Provider 嵌套地狱

**数据流设计：**
```
Zustand Store
  ├─ projects: Project[]           // 所有项目
  ├─ currentProjectId: string      // 当前打开的项目
  ├─ selectedAssetId: string       // 右侧面板选中的资产
  └─ actions:
      ├─ createProject(...)        // mock: 生成 ID，添加到 projects
      ├─ generateBaseImage(...)    // mock: 返回预设白底图 URL
      └─ generateSuite(...)        // mock: 返回预设任务卡数据
```

---

### 决策 4：三栏布局实现 - CSS Grid + Resizable Panels

**选择：** 主布局用 CSS Grid（`grid-template-columns: 60px 1fr 280px`），右侧面板用 `react-resizable-panels`

**理由：**
- **CSS Grid 天然三栏**：`grid-template-columns` 定义三列宽度，中间 `1fr` 自适应
- **react-resizable-panels 处理交互**：提供拖拽手柄、收起/展开动画、最小宽度约束
- **性能**：纯 CSS 变换，无 JS 计算布局

**左侧工具栏：** 固定 60px 宽度，图标按钮垂直排列
**中间工作区：** `1fr` 占满剩余空间，内容由当前 tab 的工作区组件填充
**右侧面板：** 默认 280px，可拖拽调整到 200-400px，可收起为 0px

**替代方案：**
- Flexbox：需要手动计算拖拽后的宽度百分比，不如 Grid 直观
- 纯 CSS `resize`：浏览器原生 resize 手柄样式丑陋且功能受限

---

### 决策 5：白底图工作区 - Virtualized Grid

**选择：** 使用 `react-window` 或 `@tanstack/react-virtual` 实现虚拟滚动网格

**理由：**
- **性能**：当项目有 100+ 张图片时，只渲染可视区域的卡片（~20 张），避免 DOM 节点过多
- **平滑滚动**：虚拟滚动保持 60fps 滚动体验

**网格布局：** 固定卡片宽度 200px，间距 16px，响应式列数（容器宽度 / 216px）

**替代方案：**
- 不虚拟化：100 张图片 = 100 个 DOM 节点，滚动卡顿
- CSS `content-visibility: auto`：浏览器原生优化，但兼容性和控制力不如虚拟滚动库

---

### 决策 6：套图工作区状态切换 - 状态机 + 条件渲染

**选择：** 套图工作区内部用 `state` 控制 `'config' | 'canvas'` 两种模式，条件渲染不同组件

```tsx
function SuiteWorkspace() {
  const [mode, setMode] = useState<'config' | 'canvas'>('config');
  
  return mode === 'config' 
    ? <SuiteConfigPanel onConfirm={() => setMode('canvas')} />
    : <SuiteCanvasView onRePlan={() => setMode('config')} />;
}
```

**理由：**
- **简单直接**：两个状态，一个 flag，无需引入状态机库
- **保留现有画布**：`SuiteCanvasView` 复用现有 `WorkbenchBoardPage` 的 XYFlow 逻辑

**Trade-off：** 状态切换时会卸载组件，画布布局会重置。解决方案：在 Zustand store 中缓存画布布局（`canvasLayout: { nodes, edges }`），切换回来时恢复。

---

### 决策 7：XYFlow 画布复用 - 提取为独立组件

**选择：** 将现有 `WorkbenchBoardPage` 的画布逻辑提取为 `<TaskCanvas />` 组件，嵌入 `SuiteCanvasView`

**保留的逻辑：**
- 节点类型定义（原图节点、白底图节点、任务卡节点、生成结果节点）
- 连线规则（白底图 → 任务卡，任务卡 → 生成结果）
- 节点点击事件（更新右侧面板选中状态）

**新增的逻辑：**
- 顶部工具栏（批量生成、调整布局、重新规划按钮）
- 节点数据来自 Zustand store 而非 API

---

### 决策 8：Mock 数据策略 - Fixtures + 延迟模拟

**选择：** `src/api/fixtures.ts` 扩展为完整 mock 数据源，所有异步操作用 `setTimeout` 模拟延迟

**Fixtures 结构：**
```typescript
export const mockProjects: Project[] = [
  { id: 'proj-1', name: '充电宝套图', outputTargets: ['base', 'suite'], ... },
  { id: 'proj-2', name: '耳机主图', outputTargets: ['base'], ... }
];

export const mockBaseImages: Record<string, BaseImageVersion[]> = {
  'img-1': [{ id: 'base-v1', url: '/mock-assets/base-1.png', version: 1, ... }]
};

// Mock 操作
export async function mockGenerateBaseImage(imageId: string): Promise<BaseImageVersion> {
  await new Promise(resolve => setTimeout(resolve, 2000)); // 模拟 2s 延迟
  return { id: randomId(), url: '/mock-assets/base-new.png', version: 2, ... };
}
```

**Mock 图片资源：** 在 `public/mock-assets/` 放置预设图片（白底图、套图样例），fixture 返回这些 URL。

**Trade-off：** Mock 数据需要手动维护一致性（如删除项目后 fixtures 要同步），但换来独立可演示的 UI。

---

### 决策 9：样式方案 - Tailwind CSS + CSS Modules（局部）

**选择：** 主要用 Tailwind utility classes，复杂组件（如画布节点）用 CSS Modules

**理由：**
- **Tailwind 覆盖 90% 场景**：布局、间距、颜色、响应式都用 utility classes
- **CSS Modules 处理特殊情况**：XYFlow 节点样式、Konva 编辑器浮层需要精确控制，用 `.module.css` 避免全局污染

**Tailwind 配置：**
- 暗色主题作为默认（`darkMode: 'class'`，在 `<html class="dark">` 上启用）
- 自定义调色板（PS 风格灰色系：`bg-gray-900`、`bg-gray-800`）
- 紧凑间距（`spacing` 缩放 0.8 倍）

---

### 决策 10：键盘快捷键 - react-hotkeys-hook

**选择：** 使用 `react-hotkeys-hook` 库统一管理快捷键

**快捷键定义：**
- `Ctrl+Tab` / `Ctrl+Shift+Tab`：切换 tab
- `Ctrl+S`：保存当前工作（mock：显示 toast "已保存"）
- `Ctrl+Z` / `Ctrl+Y`：撤销/重做（暂不实现真实逻辑，占位）
- `Escape`：关闭对话框/取消选择

**理由：** 统一管理避免快捷键冲突，且库已处理跨浏览器兼容性。

## Risks / Trade-offs

### Risk 1：Mock 数据与真实 API 响应结构不一致

**风险：** 后续对接 FastAPI 时，发现 API 返回的字段名/结构与 mock fixtures 不同，导致大量组件需要改。

**缓解：**
- 在 design 阶段就参考现有 `src/api/contracts.ts` 的类型定义
- Fixtures 严格遵循 `contracts.ts` 的接口
- 后端对接时，先写 adapter 层转换 API 响应为 `contracts.ts` 类型，组件无需改动

---

### Risk 2：XYFlow 画布性能问题

**风险：** 当套图任务卡数量 > 50 张时，画布节点过多导致拖拽卡顿。

**缓解：**
- XYFlow 本身已做性能优化（虚拟化渲染可视区域节点）
- 如果仍卡顿，考虑分页展示任务卡（按类别折叠，默认只展开主图）
- 或引入"简化视图"模式（只显示任务卡标题，不显示缩略图）

---

### Risk 3：三栏布局在小屏幕（1366x768）下空间不足

**风险：** 左侧 60px + 右侧 280px 占据 340px，中间工作区在 1366px 屏幕上只剩 1026px，网格视图或画布可能拥挤。

**缓解：**
- 右侧面板默认收起状态（用户需要时再展开）
- 提供"聚焦模式"快捷键（`F11`），隐藏左右两侧，中间工作区全屏
- 最小支持分辨率定为 1440x900

---

### Risk 4：状态切换（配置 ↔ 画布）丢失表单输入

**风险：** 用户在配置界面填了一半表单，切到画布看了一眼，回来时表单被清空。

**缓解：**
- 配置表单的值存到 Zustand store（`suiteConfigDraft`），不是组件 local state
- 状态切换时不清空 draft，只在用户点击"重新规划"时才重置

---

### Risk 5：Fixtures 维护成本高

**风险：** 随着 spec 细化，需要 mock 的数据越来越多（版本历史、失败记录、编辑操作），fixtures 文件膨胀到 1000+ 行。

**缓解：**
- 使用 fixture 生成函数（`createMockProject()`、`createMockBaseImage()`）而非手写每条数据
- 引入 `faker.js` 或 `@faker-js/faker` 生成随机但合理的 mock 数据
- 按 capability 拆分 fixtures（`fixtures/projects.ts`、`fixtures/base-images.ts`）

## Open Questions

1. **是否需要 localStorage 持久化 mock 数据？**  
   当前设计刷新页面丢失状态。如果 demo 演示需要持久化（如给客户展示），可以加 Zustand persist middleware，但会增加复杂度。可以在实现时根据需要决定。

2. **右侧面板的默认宽度和最小/最大宽度？**  
   当前设计默认 280px，可拖拽到 200-400px。实际实现时可以根据内容密度微调（如资产缩略图显示 2 列还是 3 列）。

3. **顶部 tab 栏是否需要显示未保存标记（*）？**  
   如果后续要加"自动保存"功能，tab 标题可以加 `*` 标记表示有未保存修改。当前 demo 阶段可以省略。
