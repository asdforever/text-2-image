## Why

当前项目创建流程包含一个无意义的输出目标选择步骤（白底/套图/视频）。工作台硬编码渲染所有标签页，不管创建时选择了什么，使这个选择完全无效。同时，`BaseImageWorkspace` 存在 bug，为填充网格强制创建100个重复素材项，导致上传一张图片显示为多张。

## What Changes

- 简化项目创建流程，移除输出目标选择步骤
- 在白底图工作区添加背景类型选择（白色/透明）
- 修复素材网格重复显示 bug，只显示真实上传的素材
- 清理 `outputTargets` 相关的无用代码和类型定义

## Capabilities

### New Capabilities
- `project-creation/transparent-background`: 项目支持透明背景图片生成，作为白底图工作区的背景类型选项

### Modified Capabilities
- `project-creation/workflow`: 移除输出目标选择步骤，简化为仅需项目名称和产品名称

## Impact

**前端影响**：
- `src/components/ProjectCreateDialog.tsx` - 移除第二步选择界面
- `src/pages/BaseImageWorkspace.tsx` - 修复网格重复 bug，添加背景类型选择
- `src/store/useProjectStore.ts` - 简化 `CreateProjectInput` 接口
- `src/api/contracts.ts` - 可能需要调整 `OutputTarget` 类型

**影响范围**：
- 所有引用 `outputTargets` 的组件和测试
- 项目创建用户流程
- 白底图工作区的生成功能
