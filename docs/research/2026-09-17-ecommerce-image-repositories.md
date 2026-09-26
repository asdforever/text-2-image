# 电商图片仓库调研：EvoLinkAI 与 Motiful

调研日期：2026-09-17。范围限于两个公开仓库及其 README、源码、配置和许可；本报告不把 README 中的效果示例等同于已实现能力。当前项目对照基线为 `素材分析 -> 提示词编译 -> 批次生成 -> 项目资产/成品库归档`。

## 结论先行

两个仓库都值得作为“提示词资产和平台规则”的参考，不值得整体引入为运行时。EvoLinkAI 的价值在于覆盖面广、以商品保真/本地化为中心的案例库；Motiful 的价值在于把平台、行业、文字叠加和输出规格变成可组合的规则资产。两者都没有替代本项目的队列、快照、审计、资产关系和真实后验质检。

近期优先做四项：

1. 将平台/行业 Visual DNA、负向约束、比例和安全区从散落提示词提升为受版本控制的规则包，并绑定到生成配置与任务快照。
2. 为“图中文字”增加显式路由：文字型详情/广告任务选择已验证文字能力更强的模型，其他任务按成本和保真度路由；把该决定写入快照。
3. 在 Worker 输出入库前增加可执行的质检门：尺寸/比例/文件、OCR 文本、白底/主体占比、重复和商品相似度；失败可重试且不污染成品库。
4. 把多角度、A+ 和平台广告的模块目录补成结构化模板（slot、主图锚点、文案安全区、允许输入、约束），复用现有套图规划和批次槽位，而不是从 prompt 文本临时解析。

## 仓库一：EvoLinkAI/gpt-image-2.5-for-e-commerce

### 实际能力与数据流

仓库定位是 GPT Image 2.5 的电商 prompt cookbook，不是可本地部署的应用：根目录是 `data/`、`e-commerce/`、`images/`、多语言 README 和许可，没有应用依赖清单或服务实现。[根目录](https://github.com/EvoLinkAI/gpt-image-2.5-for-e-commerce) [README](https://github.com/EvoLinkAI/gpt-image-2.5-for-e-commerce/blob/main/README.md)

其实际可复用单元是“输入商品照片 + 带花括号变量的英文提示词 + 输出示例”。场景包含平台图组/多国家图组、A+、白底精修、多角度、材质变体、背景替换、试穿、人货互动及社媒创意；例如“换场景而保持形状、包装、标签不变”和“只使用已提供商品事实”的提示词直接体现了商品保真与事实边界。[README 中工作流与案例](https://github.com/EvoLinkAI/gpt-image-2.5-for-e-commerce/blob/main/README.md)

README 给出的是 Evolink 外部 API 的接入样例，不是本仓库代码：`POST /v1/images/generations` 异步返回任务 id，调用方轮询 `/v1/tasks/{id}` 或传 `callback_url`；请求可带 1--16 张 URL 参考图、比例/分辨率/质量和 `n=1--10`，结果 URL 仅有效 24 小时。[批量 API 段落](https://github.com/EvoLinkAI/gpt-image-2.5-for-e-commerce/blob/main/README.md) 这意味着它没有管理原图上传、持久化、回调验签、失败恢复或长期资产归档。

### 可借鉴与不宜照搬

- 可借鉴：把“不可改变的商品身份”（形状、比例、包装、logo、标签）和“不可编造的事实/声明”作为每个任务的保真约束；本项目已有服务端真实性约束卡和 `visibleFacts/unconfirmedItems`，可将这些案例整理为按任务类型选择的版本化片段。[案例提示词](https://github.com/EvoLinkAI/gpt-image-2.5-for-e-commerce/blob/main/README.md) [本地编译服务](../../backend/app/application/hero_generation_service.py)
- 可借鉴：将多市场语言、平台、商品卖点明确设为变量，并让本地化文案仅来自批准副本，而非让模型推断商品事实。[多国 listing 与 UGC 案例](https://github.com/EvoLinkAI/gpt-image-2.5-for-e-commerce/blob/main/README.md)
- 不宜照搬：直接把“生成一套图”“生成多角度”等自然语言当作可靠编排。该仓库没有可观察的任务拆分、确认、槽位、失败重试或版本资产模型；本项目已在确认时冻结规划、创建批次/槽位并由 Worker 推进，应该保留这一执行边界。[本地套图交付说明](../suite-planning-and-generation-delivery.md)
- 不宜照搬：把临时输出 URL 当成资产库。当前项目生成资产会落对象存储，关联源资产与 generation snapshot，并同步成品档案；这正是外部 API 示例所没有的能力。[本地资产服务](../../backend/app/application/project_asset_service.py) [本地成品档案说明](../project-asset-product-archive-delivery.md)

### 风险、许可与维护

许可为 CC BY 4.0，不是软件 MIT：复用、改编和商用通常可行，但必须保留适当署名、许可链接并说明改动；将提示词正文或示例图分发到产品中前应完成归因与素材来源审查。[LICENSE](https://github.com/EvoLinkAI/gpt-image-2.5-for-e-commerce/blob/main/LICENSE) README 也明确部分社区提示词/图片无法保证原作者归属，属于额外的权利链风险。[致谢段落](https://github.com/EvoLinkAI/gpt-image-2.5-for-e-commerce/blob/main/README.md)

仓库为公开、非归档，主页显示 22 次提交；2026-09-09 有图片加载修复和 cookbook 更新记录，说明仍有维护，但没有版本发布物或可执行测试，不能当作稳定 SDK 依赖。[提交历史](https://github.com/EvoLinkAI/gpt-image-2.5-for-e-commerce/commits/main) [仓库主页](https://github.com/EvoLinkAI/gpt-image-2.5-for-e-commerce)

## 仓库二：motiful/product-shots

### 实际能力与数据流

固定核验版本为 [`063c508`](https://github.com/motiful/product-shots/commit/063c508b0b7f4db5cda89f10bdf20df25026dfc5)。它是七个 Agent Skills 的集合，而非 Web/SaaS：一个路由器、共享 image-gen、主图、详情页、多角度、广告和社媒技能。[README](https://github.com/motiful/product-shots/blob/063c508b0b7f4db5cda89f10bdf20df25026dfc5/README.md) [skills 树](https://github.com/motiful/product-shots/tree/063c508b0b7f4db5cda89f10bdf20df25026dfc5/skills)

数据流为：路由技能最多五轮补全输入（完成度阈值 0.8）-> 注入平台/行业 Visual DNA 与统一负向约束 -> 分发至五类业务技能 -> 通过共享脚本请求图像模型 -> 将文件写到本地。路由器本身不调用图像 API。[路由 SKILL](https://github.com/motiful/product-shots/blob/063c508b0b7f4db5cda89f10bdf20df25026dfc5/skills/product-shots/SKILL.md)

唯一真实执行代码是 `generate.py`：OpenAI 模型用 `/images/generations`，有参考图时改用 `/images/edits` multipart；Gemini 用 `/chat/completions` 与 base64 data URL。它会把参考图压至最大边 1024px/1MB，并对 i2i 的 429、5xx、524 与网络超时最多重试三次（1/4/16 秒）。[生成器](https://github.com/motiful/product-shots/blob/063c508b0b7f4db5cda89f10bdf20df25026dfc5/skills/product-shots-image-gen/scripts/generate.py)

依赖仅为 Python 3.9+、`requests>=2.28`、`Pillow>=10.0`，安装脚本没有锁文件；API key 通过 OmniMaaS 或兼容网关环境变量/本机文件解析。[setup.sh](https://github.com/motiful/product-shots/blob/063c508b0b7f4db5cda89f10bdf20df25026dfc5/skills/product-shots-image-gen/scripts/setup.sh) [参数规范](https://github.com/motiful/product-shots/blob/063c508b0b7f4db5cda89f10bdf20df25026dfc5/skills/product-shots-image-gen/references/parameter-spec.md)

### 可借鉴与不宜照搬

- 可借鉴：Amazon 主图硬约束（纯白 RGB 255、255、255，主体占比 >=85%，居中、无文字/logo/水印）应成为本项目“规则包 + 可执行验证”中的一组，而非单纯 prompt 文字。[主图约束](https://github.com/motiful/product-shots/blob/063c508b0b7f4db5cda89f10bdf20df25026dfc5/skills/product-shots-main-image/references/hard-constraints.md)
- 可借鉴：A+ 的 8 模块、两种画幅和内侧 90% 移动端安全区，以及“主图作为一致性锚点”的关系，契合当前套图的模块/槽位模型。[A+ 模块](https://github.com/motiful/product-shots/blob/063c508b0b7f4db5cda89f10bdf20df25026dfc5/skills/product-shots-detail-page/references/aplus-modules.md)
- 可借鉴：多角度任务将变量与 prompt 分开，并列出人物、服装、饰品、镜头和布光等身份锚点；这能补足现有模块参数的字段模板。[多角度任务](https://github.com/motiful/product-shots/blob/063c508b0b7f4db5cda89f10bdf20df25026dfc5/skills/product-shots-multi-angle/references/task-prompts.md)
- 可借鉴：显式的 `text-overlay -> gpt-image-2` 路由。其资料承认 Gemini 小字不可靠，适合作为模型选择策略的输入，而不是质量保证。[模型选择](https://github.com/motiful/product-shots/blob/063c508b0b7f4db5cda89f10bdf20df25026dfc5/skills/product-shots-image-gen/references/model-selection.md)
- 不宜照搬：平台、广告和社媒“硬约束”大多是 Markdown 流程/pseudo-code；真实 `generate.py` 未实现 OCR、主体占比、白底、商品相似度、平台合规或输出视觉验证。因此 prompt 声称的合规并不构成可执行保证。[生成器](https://github.com/motiful/product-shots/blob/063c508b0b7f4db5cda89f10bdf20df25026dfc5/skills/product-shots-image-gen/scripts/generate.py) [广告约束](https://github.com/motiful/product-shots/blob/063c508b0b7f4db5cda89f10bdf20df25026dfc5/skills/product-shots-ad-creative/references/hard-constraints.md)
- 不宜照搬：脚本直接保存文件、无项目/工作区隔离、无资产 hash/provenance、无数据库任务租约或审计。现有项目的对象检查、幂等、生成关联和 archive link 是应保留的系统能力。[本地资产服务](../../backend/app/application/project_asset_service.py) [本地批次 Worker](../../backend/app/application/batch_generation_worker.py)

### 风险、许可与维护

许可证为 MIT，可复用、修改、分发和商用，保留版权和许可即可；仍按 AS IS 提供。[LICENSE](https://github.com/motiful/product-shots/blob/a2290fbb43e4b0ceda2694a4a748ff477e445fec/LICENSE) 仓库无 release/tag，最新固定提交为 2026-06-08；当日快照显示 70 stars、13 forks、0 open issues。应固定 SHA、将规则移植进本仓库并建立测试，不能让生产运行时依赖随时变化的技能文本。[仓库 API](https://api.github.com/repos/motiful/product-shots) [提交](https://github.com/motiful/product-shots/commit/063c508b0b7f4db5cda89f10bdf20df25026dfc5)

## 与本地架构的事实对照

| 维度 | 本地项目 | EvoLinkAI | Motiful |
| --- | --- | --- | --- |
| 素材分析 | 多模态编译器读取受控项目资产，输出可见事实/无法确认项。 | 以人工填写 placeholder 为主。 | 以澄清问答、平台/行业 DNA 为主。 |
| 提示词编译 | 配置、约束卡、模型/尺寸和提示词版本均写入快照；用户确认后固定最终 prompt。 | 可复制的静态模板。 | Markdown 模板、变量、规则注入。 |
| 批次生成 | 规划确认后有批次、槽位、租约 Worker、恢复和失败单槽重试。 | 外部 API 的异步提交/轮询/webhook 示例。 | 本地同步脚本加有限网络重试。 |
| 资产/成品库 | 对象校验/hash、source/generation 关系、生成快照及项目产品档案自动关联。 | 结果 URL 24 小时有效，未实现归档。 | 本地文件输出，未实现项目资产域。 |
| 合规验证 | 当前保存约束和审计快照；仍需补输出质检。 | 未实现。 | 规则文本丰富，但未实现视觉后验。 |

本地的主图编译服务将商品事实边界、已发布配置、源文件 hash、约束和提示词编译快照写入任务；确认后才调用图片编辑 Provider。[`HeroGenerationService`](../../backend/app/application/hero_generation_service.py) 套图服务在确认前可编辑模块，确认后冻结规划/源图/配置，并交给批次 Worker；生成结果以 `generated` 项目资产进入成品档案。[套图交付说明](../suite-planning-and-generation-delivery.md) [`ProjectAssetService`](../../backend/app/application/project_asset_service.py) [`ProjectArchiveCoordinator`](../../backend/app/application/project_archive_service.py)

因此，外部仓库应被消费为“经许可审查的规则与模板来源”，而不是替代运行时：导入规则时记录来源 URL、固定提交、许可、作者和本地派生版本；在发布配置中绑定版本；生成任务只保存本地冻结副本和 hash。这样既获得它们的领域知识，也不会丢失当前项目的可恢复、可审计和可归档边界。
