# 添加主图工作区

## Why

当前项目工作台缺少专门的电商主图生成能力。用户需要基于白底图快速生成突出卖点、适配平台规格的主图，这是电商转化的关键环节。白底图工作区专注于素材准备，套图工作区处理详情页叙事，但电商首屏主图（1-6张）的生成场景没有独立工作空间支持。

## What Changes

- 新增 `hero` 作为 OutputTarget 类型，与 `base`、`suite`、`video` 并列
- 在项目工作台添加"主图"标签页，位于白底图和详情套图之间
- 将现有"套图"标签重命名为"详情套图"，明确其详情页场景定位
- 新建 `HeroImageWorkspace` 组件，支持主图生成、多比例输出、卖点配置
- 更新项目创建流程，默认包含 `hero` 输出目标
- 工作台标签顺序调整为：白底图 → 主图 → 详情套图 → 视频

## Capabilities

### New Capabilities

- `workspaces/hero-image`: 主图工作区 - 基于白底素材生成电商主图，支持比例选择、卖点配置、模板应用

### Modified Capabilities

- `workspaces/suite`: 套图工作区重命名为"详情套图"，明确其详情页场景定位

## Impact

**类型定义**
- `src/api/contracts.ts` - 添加 `"hero"` 到 OutputTarget 类型
- `src/api/contracts.ts` - 添加 `"hero"` 到 AssetType 类型

**工作台布局**
- `src/pages/ProjectWorkbench.tsx` - 更新标签页列表为 `["base", "hero", "suite", "video"]`
- `src/pages/ProjectWorkbench.tsx` - 标签显示文本："Base images" → "白底图", "Hero" → "主图", "Suite" → "详情套图"

**新组件**
- `src/pages/HeroImageWorkspace.tsx` - 新建主图工作区组件

**项目创建**
- `src/store/useProjectStore.ts` - 项目创建时默认 outputTargets 包含 `["base", "hero", "suite", "video"]`

**兼容性**
- 现有项目数据中的 `suite` 类型素材和工作流保持不变
- 标签文本变更不影响数据结构
