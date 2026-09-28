# 规划大师的设计 Skill 候选调研

调研日期：2026-09-28。读取 GitHub API、浅克隆源码及许可证；未安装、运行候选 Skill，未修改应用。Stars 是当日仓库级数据，不是单个 Skill 的星数，也不是电商生图质量评测。

## 结论

适合借鉴高星项目，但不适合把几个完整 SKILL.md 拼进规划大师。首批建议保留三层：自有电商内容策略、按需设计指导、已有 GPT Image 风格模板。设计指导优先提炼 Impeccable 的目标与层级判断、UI UX Pro Max 的 banner-design 创意流程；canvas-design 仅借鉴空间、节奏和系列变化。

“绑定”应指应用在实际模型请求中注入经过适配、带版本的知识；在开发者电脑安装 Skill 不会让服务器上的规划大师自动获得它。也不是训练或永久修改模型权重。

## 已核对候选

| 项目 / 内容 | 仓库 Stars | 已读取版本 | 许可 | 适合借鉴 / 限制 |
|---|---:|---|---|---|
| anthropics/skills：canvas-design、frontend-design | 178,682 | `33375500bcea98d610eb30ce10ac4e59b89c390d` | 两个 Skill 各自 LICENSE.txt 均为 Apache-2.0；根 API license 为 null，不能据此判定整个集合许可证 | 有意识的视觉方向、层级、排版、空间、反模板化；并非电商图专用 |
| nextlevelbuilder/ui-ux-pro-max-skill：banner-design | 131,046 | `09170eec67eefd46a7ae85de61b40c194020f997` | 根 MIT；banner-design 元数据亦为 MIT | 广告目的、2–3 视觉方向、构图层级、画布尺寸；原流程采用 HTML/CSS 叠字截图 |
| pbakaus/impeccable | 71,840 | `9d715cc4f5564a990ca8345abfdd5df6dc9b41c8` | Apache-2.0；另有第三方 NOTICE | Persuade/Read 目标、信息层级、品牌一致性、去模板化和自检；主要是前端 UI 设计系统，不能整包当成生图规划器 |
| freestylefly/awesome-gpt-image-2 | 33,612 | 本应用已固定 `0dc09c46c8a30b1fdd89c18cc78a894dac2104e3` | MIT | 已有模板与表现方式素材库；应继续使用并改善选择逻辑，不必重复安装 |

Stars 来源：[Anthropic API](https://api.github.com/repos/anthropics/skills)、[UI Pro API](https://api.github.com/repos/nextlevelbuilder/ui-ux-pro-max-skill)、[Impeccable API](https://api.github.com/repos/pbakaus/impeccable)、[风格库 API](https://api.github.com/repos/freestylefly/awesome-gpt-image-2)。前三项由本次研究直接获取，风格库计数由同任务主研究获取。

## 具体内容与适配边界

### Anthropic：借鉴设计思考，避免引入新的审美限制

[canvas-design 源码](https://github.com/anthropics/skills/blob/33375500bcea98d610eb30ce10ac4e59b89c390d/skills/canvas-design/SKILL.md)先创建视觉哲学，再输出 PNG/PDF；覆盖色彩材料、比例节奏、构图平衡与视觉层级，也要求多页保持方向一致但各有变化。然而原文强调“90% visual design, 10% essential text”、稀疏文字、艺术品、细字以及艺术概念的隐含表达。整篇绑定可能再次压制电商参数页的大字、清晰说明和直接卖点表达。

[frontend-design 源码](https://github.com/anthropics/skills/blob/33375500bcea98d610eb30ce10ac4e59b89c390d/skills/frontend-design/SKILL.md)更适合提炼“基于真实产品与受众形成方向”“结构必须传达信息”“一个主要记忆点”“先规划、对照简报、自评再实现”。其中 CSS、交互、无障碍、响应式等内容不属于图片规划器职责；也不应把反对通用大数字布局误变成禁止电商参数大字。

许可证：[canvas-design LICENSE](https://github.com/anthropics/skills/blob/33375500bcea98d610eb30ce10ac4e59b89c390d/skills/canvas-design/LICENSE.txt)、[frontend-design LICENSE](https://github.com/anthropics/skills/blob/33375500bcea98d610eb30ce10ac4e59b89c390d/skills/frontend-design/LICENSE.txt)。

### UI UX Pro Max：banner-design 比整套 UI 规则更贴近本任务

[banner-design 源码](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill/blob/09170eec67eefd46a7ae85de61b40c194020f997/cli/assets/skills/banner-design/SKILL.md)明确针对广告、社媒创意、封面，先收集目的、平台、内容、品牌，再选择 2–3 个方向并解释其如何服务目的。适合提炼标题与画面的主次、视觉来源选择、准确画幅、裁切安全区和品牌约束。

但其真实执行方式是生成 HTML/CSS，把文案覆盖在无字背景上，再截图导出 PNG；直接粘贴进当前模型会产生错误的工具/输出预期。此外固定 CTA 位置、44px 触控高度、广告文字低于 20% 等规则，不应成为商品详情图通用约束；本研究未核实其平台政策陈述的时效性。

仓库也包含 `styles.csv`、`colors.csv`、`typography.csv` 等可检索数据，适合作为候选参考，不应让“行业→固定风格”规则重新把每个科技产品锁定成同一种背景。

证据：[MIT LICENSE](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill/blob/09170eec67eefd46a7ae85de61b40c194020f997/LICENSE)、[设计数据目录](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill/tree/09170eec67eefd46a7ae85de61b40c194020f997/src/ui-ux-pro-max/data)。

### Impeccable：最值得借鉴的是“这张图要改变什么理解”与设计自检

[Skill 源码](https://github.com/pbakaus/impeccable/blob/9d715cc4f5564a990ca8345abfdd5df6dc9b41c8/plugin/skills/impeccable/SKILL.md)区分 Persuade（决定并行动）、Read（理解）、Operate、Experience；这种区分比“必须拍完整商品”更适合规划不同购买问题。其原则尊重用户已指定的风格，不以反模板化之名覆盖真实简报。

[new-work](https://github.com/pbakaus/impeccable/blob/9d715cc4f5564a990ca8345abfdd5df6dc9b41c8/plugin/skills/impeccable/reference/new-work.md)要求明确受众、应相信什么、哪些真实证据支持、视觉方向和阅读叙事；[bolder](https://github.com/pbakaus/impeccable/blob/9d715cc4f5564a990ca8345abfdd5df6dc9b41c8/plugin/skills/impeccable/reference/bolder.md)强调一个明确强化点、周围克制、事实不变以及结构本身能否传达信息。可改写成简短的电商构图与自检规则。

整包则包含 CLI 下载/执行、PRODUCT.md / DESIGN.md、DOM/CSS 检测、前端修改、独立评审代理等协议。[critique](https://github.com/pbakaus/impeccable/blob/9d715cc4f5564a990ca8345abfdd5df6dc9b41c8/plugin/skills/impeccable/reference/critique.md)是界面审查，不是已验证的商品生图自动质量评分器。不得因为读到它的运行指令就执行工具或安装依赖。

许可证：[LICENSE](https://github.com/pbakaus/impeccable/blob/9d715cc4f5564a990ca8345abfdd5df6dc9b41c8/LICENSE)、[NOTICE](https://github.com/pbakaus/impeccable/blob/9d715cc4f5564a990ca8345abfdd5df6dc9b41c8/NOTICE.md)。

## 本地接线证据

- `backend/app/application/module_planning_service.py:203–219`：规划大师实际 system 是自有规划 Skill + `STYLE_LIBRARY_PLANNING_RULES`，user context 包含 `styleLibrary`、模块目录、约束、可选反推资料。
- 同文件 `:224`：`designKnowledge` 只写入 snapshot，当前并未加入上述 system/user。这意味着“记录了设计知识快照”和“大师真正读到了设计知识”是两回事。
- `backend/app/application/module_planning_v2.py:378`：单图编译器实际 context 则包含 `designKnowledge`。需要统一职责和实际注入位置，不应只增加一份配置标记。
- `backend/app/application/image_style_library.py:12–15`：现有 GPT Image 风格库已固定来源、revision 和版本，可沿用这种可追溯结构。

## 建议落地设计（未实现）

1. 自有电商核心规则常驻：购买问题→真实卖点/证据→视觉解释→产品出场方式；保留主图/套图用途及平台硬约束。
2. 单独维护带来源、license、revision、内容 hash 的设计知识包；提炼上述参考中的通用规则，删除脚本调用、HTML 输出、网页控件和平台过时断言。
3. 每次只选择与本任务相关的少量知识：参数解释加载图解/信息层级，场景页加载需求与动作表达，产品主视觉加载摄影/材质。已有 GPT Image 模板服务最终可执行提示词。
4. 将实际加载的内容与选择理由传入大师请求并留存快照。大师产出每张的信息目标、事实依据、表达方式、产品出场、主次关系、系列共性与差异；单图编译器再展开细节。
5. 用同产品/模型/尺寸验证新旧规划与成图，检查事实准确、表达多样、商品出场合理、文字可读和系列一致性；Stars 不能替代结果对比。

第一批无需安装整套插件，也无需加多轮自动审图。先让现有大师真正读到适合电商的设计指导，同时解除模块和构图简案的过度约束。
