## Why

提示词商城目前只有「信息 / 测试 / 对比 / 版本历史」四个只读标签页，没有任何写入入口。模板只能靠手填 API 创建，`package.json` 里遗留的 `npm run prompt-import` 因为 `backend/cli.py` 已移除该子命令而不可用。结果是商城内容长期停留在 3 个分类、10 个模板，其中 4 个是测试残留，与实际生成需求不匹配。

同时，项目里已经存在一份完整的「爆品图反推」前端原型（`src/pages/ReversePage.tsx`），它挂在未被引用的 `src/app/App.tsx` 上，后端也没有任何 `/api/reverse-plans` 实现。原型的设计意图是让用户上传爆品参考图、逐图反推出提示词，并归档为资产——这条能力至今缺失。

本变更把两者合并为一件事：建立一个提示词的生产与沉淀闭环。三种输入（描述创作、爆品图反推、基于已有模板改写）都产出可复用模板并写入提示词商城；反推自身又消费商城里 `stage=reverse_prompt` 的模板，使生产者与消费者共用同一个池子。

## What Changes

- 新增独立一级导航「提示词工坊」，提供三种生成模式：描述创作、爆品图反推、改写生成。
- 生成结果必须是**结构化草稿**，直接填满商城模板字段（body、user_prompt_template、input_schema、output_schema、applicability、generation_params），而不是一段自由文本。
- 定义标准变量集（平台、市场、语言、品类、卖点、风格、模块），所有生成结果必须使用该变量集，避免模板各自为政。
- 生成时注入平台合规规则，使模板天生符合目标平台要求，而不是在生成阶段事后补救。
- 生成动作本身不落库；只有用户显式确认保存时才写入 `prompt_templates` 与 `prompt_versions`，并以 `source=generated` 标记来源。
- 新增爆品图反推能力：支持主图反推与详情图反推两种类型，单方案最多 16 张参考图，每张独立选择反推模板、独立反推、可重跑。
- 详情图反推支持指定系列色彩基准图，用于约束同一系列多图的色彩一致性。
- 反推会话、参考图与逐图尝试为浏览器会话态，不持久化；刷新后需重新上传。这是本变更明确接受的边界。
- 驱动生成的元提示词本身也作为提示词模板存储（独立分类），使生成质量可版本化、可复现。
- 修复 `npm run prompt-import` 失效的遗留脚本。

## Capabilities

### New Capabilities

- `prompt-authoring-studio`: 提示词工坊的三种生成模式、结构化草稿、标准变量集、平台规则注入和确认后落库。
- `reverse-prompt-authoring`: 爆品图反推的上传、逐图反推、批量执行、系列色彩基准和结果归档边界。

### Modified Capabilities

无。

## Impact

- 后端：新增提示词工坊应用服务与路由；复用 `prompt_library` 既有模板与版本表，不新增业务表；新增平台规则读取模块，供本变更与生成约束卡共用。
- 前端：新增一级导航与页面，接入三种生成模式；反推部分按原型意图重建为 TanStack Router 路由与现有设计系统，不复用废弃的 `src/app/App.tsx` 路由。
- 数据库：本变更不新增业务表。若后续需要持久化反推会话，再单独评估 `prompt_authoring_sessions`。
- Provider：复用现有 `context_model`（多模态）驱动生成；反推与创作都不调用图片生成 Provider，因此本变更不产生图片计费调用。
- 清理：`src/app/App.tsx`、`src/pages/ReversePage.tsx`、`src/pages/StartPage.tsx`、`src/pages/StyleLibraryPage.tsx`、`src/product-reverse.css` 属于未被引用的早期原型。为避免误导，反推能力重建完成后再统一删除，本变更只标注不删除。
- 验收：覆盖三种模式的结构化产出、变量集校验、平台规则注入、确认前不落库、反推逐图独立性与批量执行、系列色彩基准、以及不产生图片 Provider 调用。
