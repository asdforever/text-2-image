## Context

当前系统存在两个问题需要解决：

1. **项目创建流程冗余**：`ProjectCreateDialog` 包含两步流程，第一步让用户选择输出目标（白底/套图/视频），但 `ProjectWorkbench.tsx:59` 硬编码渲染所有标签页，不使用存储的 `outputTargets` 字段进行过滤。

2. **素材网格重复Bug**：`BaseImageWorkspace.tsx:32-38, 58-62` 为了填充网格视图，强制创建至少100个虚拟资产项，通过 `Array.from({ length: Math.max(100, sourceAssets.length) })` 和取模运算 `sourceAssets[index % sourceAssets.length]` 重复真实素材。

现有架构：
- **Frontend**: React + TanStack Router + Zustand store
- **Project Model**: `{ id, name, productName, outputTargets: OutputTarget[], assets: Asset[] }`
- **OutputTarget Type**: `"base" | "suite" | "video"`
- **Asset Types**: `"source" | "base" | "suite" | "video"`

## Goals / Non-Goals

**Goals:**
- 简化项目创建为单步流程，只需项目名称和商品名称
- 移除无意义的输出目标选择界面
- 在白底图工作区添加背景类型选择（白色/透明）
- 修复素材网格重复显示bug，只显示真实上传的素材

**Non-Goals:**
- 不改变项目工作台的标签页结构（仍保持三个标签）
- 不影响现有项目的数据模型（向后兼容）
- 不实现透明背景的实际图像生成逻辑（只添加UI选择器）
- 不添加除透明背景外的其他新功能

## Decisions

### Decision 1: 保留 outputTargets 字段，但不在创建时选择

**Rationale**: 
- 现有项目数据已包含 `outputTargets` 字段
- 为了向后兼容，保留该字段但在创建时默认设置为所有目标
- 避免数据库迁移和类型定义的大量修改

**Alternative Considered**: 
- 完全删除 `outputTargets` 字段 → 需要修改大量现有代码和数据结构
- 使用该字段控制标签显示 → 与工作台硬编码行为冲突，需要更大范围重构

**Implementation**:
```typescript
// ProjectCreateDialog.tsx
const submit = () => {
  // 自动设置所有输出目标，不需要用户选择
  const project = createProject({
    name: trimmedName,
    productName: trimmedProductName,
    outputTargets: ["base", "suite", "video"], // 固定值
    sourceCount: 0,
    sourceFiles: []
  });
};
```

### Decision 2: 背景类型作为工作区内状态，不存储在项目模型

**Rationale**:
- 背景类型（白色/透明）是生成时的参数选择，不是项目属性
- 与生成参数（size, quality, style）类似，应在执行时选择
- 使用 Zustand store 的会话状态保持用户选择

**Alternative Considered**:
- 存储在项目模型 → 过度持久化运行时参数
- 存储在 localStorage → 跨项目共享，不符合每个工作区独立选择的语义

**Implementation**:
```typescript
// 在 BaseImageWorkspace 组件内
const [backgroundType, setBackgroundType] = useState<"white" | "transparent">("white");

// UI 选择器
<select value={backgroundType} onChange={(e) => setBackgroundType(e.target.value)}>
  <option value="white">白色背景</option>
  <option value="transparent">透明背景</option>
</select>
```

### Decision 3: 直接使用真实素材数组，移除虚拟填充逻辑

**Rationale**:
- 虚拟填充逻辑的目的是展示网格效果，但会误导用户
- `@tanstack/react-virtual` 虚拟滚动已优化大列表性能
- 空状态应明确显示"请上传素材"，而非显示重复的虚拟项

**Alternative Considered**:
- 保留虚拟填充但添加视觉区分 → 仍会混淆用户
- 使用占位符卡片填充 → 增加复杂度，用户可能误操作

**Implementation**:
```typescript
// BaseImageWorkspace.tsx - 移除 Array.from 和取模逻辑
const [assets, setAssets] = useState<Asset[]>(() => {
  return project.assets.filter((asset) => asset.type === "source" || asset.type === "base");
});

useEffect(() => {
  const sourceAssets = project.assets.filter((asset) => asset.type === "source" || asset.type === "base");
  setAssets(sourceAssets);
}, [project.id, project.assets]);
```

## Risks / Trade-offs

### Risk: 移除输出目标选择可能让用户困惑项目类型
**Mitigation**: 
- 工作台标签页清晰标注各工作区用途
- 在项目列表显示项目包含的素材类型统计
- 文档说明一个项目是对一款产品的完整工作区集合

### Risk: 背景类型不持久化，刷新后丢失选择
**Mitigation**:
- 大多数用户在单次会话内完成批量生成
- 如后续发现需要持久化，可添加到项目的工作区配置中
- 当前设计保持简单，避免过早优化

### Trade-off: 保留 outputTargets 字段但不使用
**Impact**: 
- 代码中存在未使用的字段，略微增加认知负担
- 好处是避免大范围重构和数据迁移
- 未来如需真正控制标签显示，该字段已就位

### Risk: 移除虚拟填充后，空项目显示空白网格
**Mitigation**:
- 添加空状态提示："暂无素材，请上传原图或从素材库导入"
- 显示上传按钮和素材库导入按钮作为引导

## Migration Plan

**Phase 1: 修复素材网格Bug**
1. 修改 `BaseImageWorkspace.tsx`，移除虚拟填充逻辑
2. 添加空状态UI组件
3. 验证现有项目的素材正确显示

**Phase 2: 简化项目创建流程**
1. 修改 `ProjectCreateDialog.tsx`，移除第一步选择界面
2. 更新 `createProject` 调用，固定传入所有输出目标
3. 更新 stepper 显示（如果保留 stepper，调整步骤标签）

**Phase 3: 添加背景类型选择**
1. 在 `BaseImageWorkspace.tsx` 添加背景类型状态和选择器UI
2. 位置：工具栏区域，批量操作按钮附近
3. 当前版本仅UI，实际生成逻辑保持不变（待后续prompt模板对接）

**Rollback Strategy**:
- 所有改动仅在前端组件，无数据库schema变更
- 出现问题可直接回退代码提交
- 现有项目数据不受影响

## Open Questions

None - 所有技术决策已明确，可直接实施。
