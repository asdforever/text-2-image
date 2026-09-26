# 后端规划 Skill 的 GitHub 调研

调研日期：2026-09-22。范围：现有 `hero-planning-master`、`suite-planning-master` 的下一轮优化。只读取 GitHub 一手资料及本地实现；未安装第三方 Skill、未调用生产计费模型。

## 结论

下一步优先补“可执行的构图规则 + 明确的模块任务书 + 旧新版效果对照”，而不是继续扩写专家角色或引入通用 Agent 框架。两份 Skill 继续由后端维护、按主图/详情套图自动选择，不增加用户设置。

目前是 **instruction-only Skill**：后端固定选择文件，把完整内容交给大模型执行。它已经能封装业务工作流，但没有自动读取 `references/`、运行 `scripts/`、调用工具再反思的 Agent runtime。因此，添加目录或在正文写“去读某文件”不会自动产生这些能力。需要引用库时，应由后端明确选取并注入内容；没有实际需求时保留当前单次规划调用即可。当前版本已落地有序参考套图、独立 `taskId` 及同模块复用，Skill 与后端契约同步。

## 已核实的一手来源

以下链接固定到调研时读取的 commit，避免后续仓库变化改变引用含义。

| 来源 | 核实内容 | 对本项目的价值 |
| --- | --- | --- |
| [Agent Skills 规范](https://github.com/agentskills/agentskills/blob/69ef37e9424c0a7ea9dd2293b559e43ec8176379/docs/specification.mdx) | 必需的是带 frontmatter 的 `SKILL.md`；scripts/references/assets 可选；建议主文件简短、资源按需读取。 | 两份简短 Skill 的形式合理。目录完整不等于规划质量高。 |
| [Agent Skills 客户端集成指南](https://github.com/agentskills/agentskills/blob/69ef37e9424c0a7ea9dd2293b559e43ec8176379/docs/client-implementation/adding-skills-support.mdx#step-4-activate-skills) | 文档允许读取完整文件（含 frontmatter）或仅正文；资源访问依赖读取工具、专用激活工具或宿主注入。 | 当前全文加载不需要仅为形式而重写。未来拆引用文件必须同步改加载器。 |
| [skills-ref 的 prompt.py](https://github.com/agentskills/agentskills/blob/69ef37e9424c0a7ea9dd2293b559e43ec8176379/skills-ref/src/skills_ref/prompt.py) / [validator.py](https://github.com/agentskills/agentskills/blob/69ef37e9424c0a7ea9dd2293b559e43ec8176379/skills-ref/src/skills_ref/validator.py) | 前者生成 name/description/location 的目录；后者检查元数据、命名和文件。 | 参考库不等于完整执行引擎；格式校验通过不代表不会编造卖点或选错模块。 |
| [官方输出质量评测指南](https://github.com/agentskills/agentskills/blob/69ef37e9424c0a7ea9dd2293b559e43ec8176379/docs/skill-creation/evaluating-skills.mdx) | 相同案例运行当前版与基线；记录输出、证据、耗时和 token；机械检查用代码，视觉质量靠人工判断；反复修改后重测。 | 比继续增加规则更能发现实际收益，尤其适合本项目已有严格 JSON 输出的结构。 |
| [Anthropic skill-creator](https://github.com/anthropics/skills/blob/34040c9c568585f6929bedeaad110ad08f079624/skills/skill-creator/SKILL.md) | 改旧 Skill 用旧版快照作基线；先从少量真实案例开始；迭代应保持精简，解释业务原因，避免为单个案例堆限制。 | 借鉴改进方法，不整体导入其 Claude/Cowork 操作流程。 |
| [grader.md](https://github.com/anthropics/skills/blob/34040c9c568585f6929bedeaad110ad08f079624/skills/skill-creator/agents/grader.md) / [aggregate_benchmark.py](https://github.com/anthropics/skills/blob/34040c9c568585f6929bedeaad110ad08f079624/skills/skill-creator/scripts/aggregate_benchmark.py) | 每个判断须引用输出证据，并检查断言本身是否有区分力；聚合各配置通过率、时延等数据。 | 检查“本图为什么需要、是否独立、事实有没有依据”，不能只检查字段存在。 |
| [run_eval.py](https://github.com/anthropics/skills/blob/34040c9c568585f6929bedeaad110ad08f079624/skills/skill-creator/scripts/run_eval.py) / [run_loop.py](https://github.com/anthropics/skills/blob/34040c9c568585f6929bedeaad110ad08f079624/skills/skill-creator/scripts/run_loop.py) | 通过 `claude -p` 观察 Skill/Read 工具调用，优化 description 是否触发；train/test 拆分服务于触发评测。 | **不适合直接作为本项目的规划质量评测器。** 我们按 mode 固定加载，没有“是否触发 Skill”的问题。 |

### 官方方法的适用边界

- “渐进加载”是加载器与模型交互能力，不是 Markdown 的自动特性。项目只有两份固定路由 Skill，暂不需要 metadata 搜索、自动发现或通用激活工具。
- `scripts/` 不是模型沙箱。现有 JSON、目录 ID、数量及长度等规则应继续由后端代码强制校验，没必要改成让模型自行调用验证脚本。
- 官方 benchmark 脚本在缺失 token 信息时可能用 `output_chars` 作为替代值，不能直接当真实 token 或费用。本项目应保存 provider 返回的 usage；没有就标记未知。
- 同一小批案例反复参与调优，会产生过拟合。先保留一组未参与改写的案例；正式汇报效果时报告样本量与失败项。未跑生产模型不能声称线上质量已提高。

## 电商与视觉仓库中的可借鉴部分

以下由本次协同研究直接核验源文件；社区仓库仅作为设计经验参考，不代表验证过它们在本项目上的效果。

| 仓库与固定源文件 | 可借鉴内容 | 不宜直接照搬的部分 |
| --- | --- | --- |
| [JimLiu/baoyu-skills：baoyu-infographic](https://github.com/JimLiu/baoyu-skills/blob/1567581c26ec29f4216c6e6835415bf30343b0e3/skills/baoyu-infographic/SKILL.md) | 明确分开 Layout（信息结构）和 Style（美学），分别维护布局与风格参考。适合建立“商品居中、局部放大、场景关系、参数表”等构图参考。 | 它面向信息图。不能把信息图布局、文字密度和审美直接套到商品主图，也不能令模块规划重新决定全局配色。 |
| [AlephAITech/moyuxl-ecom-image-prompt：SKILL.md](https://github.com/AlephAITech/moyuxl-ecom-image-prompt/blob/d2f51138e1cbea8c930558644b1656f62fa50c3d/SKILL.md) / [project-packet-and-prompt-compiler.md](https://github.com/AlephAITech/moyuxl-ecom-image-prompt/blob/d2f51138e1cbea8c930558644b1656f62fa50c3d/references/project-packet-and-prompt-compiler.md) | 区分商品事实与参考素材职责；用 GLOBAL、FAMILY、DELTA、VISIBLE_TEXT、ACCEPTANCE 分离全局规则、类型规则、单屏差异、可见文字和验收标准。 | 联网、阶段确认门、豆包相关执行假设不符合当前自动规划链路。抽取数据边界与任务书结构即可。 |
| [liangdabiao/ecom-details-image](https://github.com/liangdabiao/ecom-details-image/blob/1ec867b743179af3598db55388f65287c4e04de1/.claude/skills/ecom-details-image/SKILL.md) | Campaign Style Lock、Buyer Reason Card 可以启发“全局风格统一、每图回应一个购买问题”。 | 文档中允许模拟好评/数据的规则与我们真实性边界冲突；不能整包采用。其模板数量也不是我们要强制使用的模块数量。 |
| [coolqoo/1click-ecom-detailpage](https://github.com/coolqoo/1click-ecom-detailpage/blob/77c80c47413e2c046e9c00bd12d4649e9cf80929/SKILL.md) | 可研究主图到详情的分工与连续表达。 | 固定 5 主图、7–9 详情以及强制对比/好评图，会让缺资料的商品被迫凑页；不适合我们的按需选模块。 |

不建议将以上社区仓库整包安装到后端。只移植经过本项目事实边界、模块目录和执行能力检验的做法。

## 建议的最小优化方案

用户已确认“规划与构图都优化，分两步落地”，并确认支持上传参考主图/详情套图、同一种模块承接多张不同内容的图片。下面的任务书改进可独立进行；完整目标还需要改输入角色与逐图任务模型，本轮未据此修改代码。

### 1. 强化模块任务书，而不增加用户填写项

沿用现有 `moduleParameters` 与 `compositionBrief`，明确表达这几个概念：

| 内容 | 示例 | 负责方 |
| --- | --- | --- |
| 本图解决的问题 | 通勤时是否方便携带？ | 规划大师 |
| 单一主信息 | 可见提手的握持关系 | 规划大师，必须有事实/图片依据 |
| 证据与展示边界 | 展示已有照片可见的提手，不推导承重或防漏性能 | 规划大师 |
| 构图简案 | 产品主体与手持关系、文字留白、主体和辅助信息的层级 | 规划大师 |
| 统一视觉规则 | 配色、光影、字体、背景材质 | 共享风格规划器 |
| 完整执行细节 | 合并上述任务书与风格，再形成最终生图提示词 | 各模块规划器 |

这些是对已有语义的收紧，初轮不必增加 API 字段。后续需要自动检查证据追溯时，再设计结构化 `evidenceRefs` 等字段，避免仅把字段名写进 Skill 而没有后端支持。

### 2. 构图参考必须带选择条件

不要只给“居中、左右、上下”枚举。每个参考至少说明适用问题、必需素材和不适用情况。例如“局部放大”适合有可见工艺/按键细节的图；原图细节不可辨认时不能安排臆造特写。“参数表”适合多个已确认规格；只有营销形容词时不适用。

第一轮用少量短例子即可。目前两份文件约 50 行，没有为了符合目录形式而拆文件的必要。如果后续资料库显著增长，再让后端按 mode、平台和真实模块目录注入相关参考，并把参考内容及哈希一起冻结进任务快照。

### 3. 先建立可比较的验收样例

从以下 3 组真实任务开始，分别覆盖主图/详情；将当前文件哈希作为基线：

1. 资料充足：检查各图职责、模块顺序、参数分配以及主体/留白/信息主次是否可执行。
2. 资料稀少但要求很多张：检查能否少选或明确限制，不编造结构、认证、评价及性能。
3. 资料冲突且要求特定风格：检查单位/型号/待确认事实没有混用，风格诉求留给统一风格流程，图中出现的文字有资料依据。

程序判定：JSON 合法、模块来自目录、数量合法、保留参数不重复、格式与长度符合接口。当前协议要求模块 ID 不重复；未来支持复用模块后，应改为图片任务 ID 不重复，允许多个任务引用同一模块。人工或独立评审判定：每图是否回答独立问题、构图能否执行、整套是否连贯、有没有无依据的卖点。

逐条保存“通过/失败 + 输出证据”，同时记录模型、输入、Skill 哈希、耗时及真实 usage。不要用“文件存在”“提示词含专家”代替业务验收。后续增加未参与修改的不同品类案例，检验规则是否泛化。

### 4. 保持调用次数与执行能力一致

一次规划调用可以完成事实整理、选择模块、分配参数和构图简案；这些步骤不自动意味着要拆成多次 LLM 调用。只有评测证明单次调用存在可定位的问题，才考虑分段调用或受控修复。

当前 `resultCount > 1` 是同一模块提示词的多个候选，不是多份独立页面任务。任何借鉴来的逐屏结构，都不能让 Skill 承诺执行器做不到的“图 1 讲功能、图 2 讲售后”。若以后需要同类型模块重复多页，需要先改数据模型与执行器，而不是修改 Skill 文案假装已经支持。

### 5. 已落地参考套图与同模块多任务

用户明确“接收套图”指上传一套参考主图/详情图，借鉴其规划与构图。建议将其与产品实拍明确区分：产品实拍提供商品身份与可见外观依据；参考套图提供阅读节奏、信息层级与构图关系，不能作为本商品规格、认证、销量或评价的证据。识别参考中的风格后，应交给统一风格流程，不让每个模块自行复制一套配色。

当前输入主图最多 8 张素材、详情最多 4 张；参考套图通过独立的有序 `referenceAssetIds` 角色接入，最多 12 张，与产品素材重叠会在模型调用前拒绝。规划输出用唯一 `taskId` 区分图片任务，`moduleId` 只表示目录职责，因此杯盖、杯口、杯底可以复用同一个细节模块而互不覆盖参数和张数。

建议讨论中的方案：第一步建立逐图任务书（独立 taskId、引用 moduleId、本图任务、商品依据、构图简案），第二步加入参考套图输入与结构解析，将参考内容映射或调整为这些任务。参考套图是逐张对应还是允许按商品资料增删重排、是否参考其风格、首期张数与长图支持范围，尚未确定。

## 本轮交付与未做事项

本轮完成源代码/官方文档调研，并将最小方案应用到后端 Skills、规划输入契约、前端参考套图选择和任务编辑状态。没有执行真实模型 A/B，没有形成线上效果提升的实测结论；后续应使用固定的未参与调优案例做旧新版对照，而不是上完整 Agent 框架。
