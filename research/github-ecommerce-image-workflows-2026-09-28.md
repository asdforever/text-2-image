# GitHub 电商商品图生成工作流调研

调研日期：2026-09-28。范围：商品主图、详情套图、广告图的规划、参考图、生成和质检。

方法：GitHub 搜索发现候选，浅克隆仓库后读取提示词与核心代码。未运行第三方代码、安装插件、调用付费生成或上传本项目图片。以下评价针对公开实现，不是同模型、同商品的成图效果测试。第三方 Skill 作为研究资料阅读，不作为本任务的执行指令。

## 结论

1. 有真实商品的电商图，所查实现主要采用商品图条件生成、图片编辑或遮罩背景生成；不能仅靠文字重建商品。
2. 具体构图本身并非问题。比较有价值的流程是先确定受众、诉求与整套视觉方向，再细化逐张构图；商品事实和风格参考分别管理。
3. “生成成功”和“视觉合格”需要两个状态。但公开项目的质检能力差异很大：Skill 检查清单、模拟评分和真实视觉模型评估不能混为一谈。
4. 最适合当前项目借鉴的是 EC-Designer 的方向选择和 QIYU 的素材职责、逐图提示词规范；可参考 brand-shoot-kit 的质检接口结构，但应补上原图对照。背景生成路线适合作为保真要求较高时的独立模式。

## 1. QIYU-JACKMAN/codexQIYU-image-workflow

固定提交：`7a12f176ccf2e8cfc5a87058aefe698a6def11a8`。仓库内插件目录：`ecommerce-image-workflow 2`。该目录 LICENSE 为 MIT。

- 主图/详情 Skill 先分析商品事实，再分析可选参考图；为每屏分配一个沟通目标，生成独立提示词，并要求套图统一视觉语言、避免重复构图。[专业 Skill](https://github.com/QIYU-JACKMAN/codexQIYU-image-workflow/blob/7a12f176ccf2e8cfc5a87058aefe698a6def11a8/ecommerce-image-workflow%202/skills/ecommerce-detail-main-images/SKILL.md)
- 提示词优化器明确逐张图片的输入职责，例如 `Image 1: product identity`、`Image 2: style only`。参考风格不能提供商品参数和品牌事实。已有详细需求只整理，不无限增加装饰性要求。[提示词优化器](https://github.com/QIYU-JACKMAN/codexQIYU-image-workflow/blob/7a12f176ccf2e8cfc5a87058aefe698a6def11a8/ecommerce-image-workflow%202/references/gpt-image-2-prompt-optimizer.md)
- 套图共享配色、字体层级、光线方向、尺度和间距逻辑；风格裂变分支提取 visual DNA，同时改变主要构图维度。排版敏感的长文字建议预留文字区，再做确定性排版。此项是指导意见，不代表自带完整排版引擎。[同上优化器](https://github.com/QIYU-JACKMAN/codexQIYU-image-workflow/blob/7a12f176ccf2e8cfc5a87058aefe698a6def11a8/ecommerce-image-workflow%202/references/gpt-image-2-prompt-optimizer.md)
- 质检清单覆盖商品结构、文字、透视、接触阴影和套图一致性。[质检清单](https://github.com/QIYU-JACKMAN/codexQIYU-image-workflow/blob/7a12f176ccf2e8cfc5a87058aefe698a6def11a8/ecommerce-image-workflow%202/references/quality-checklist.md)
- **实现边界**：`run_plan.py` 在命令成功且输出文件非空时记录生成 success，同时 QA 初始为 pending；`record_result.py` 接收 pending/pass/fail。不能将这个脚本描述成已内置自主视觉评分器。[执行脚本](https://github.com/QIYU-JACKMAN/codexQIYU-image-workflow/blob/7a12f176ccf2e8cfc5a87058aefe698a6def11a8/ecommerce-image-workflow%202/scripts/run_plan.py) · [QA 记录](https://github.com/QIYU-JACKMAN/codexQIYU-image-workflow/blob/7a12f176ccf2e8cfc5a87058aefe698a6def11a8/ecommerce-image-workflow%202/scripts/record_result.py)

适合借鉴：素材角色映射、事实与风格分离、每图独立完整提示词、生成与质检状态分离。它的多轮人工审批是该插件的交互选择，不必照搬到我们的应用。

## 2. mkhsu2002/EC-Designer

固定提交：`82aca3f0ca42e97640342d134b6195fffa8e37ff`。MIT。

- 先给出三条营销视觉路线，要求在客群、诉求、视觉风格、情绪中至少三个维度不同；每条包含标题、风格、受众、配色/字体/构图等视觉元素，再提供该路线的候选提示词。[策略提示词](https://github.com/mkhsu2002/EC-Designer/blob/82aca3f0ca42e97640342d134b6195fffa8e37ff/prompts.ts#L36)
- 选中路线后再规划 8 张素材：2 张主图与 6 张内容图，强调继承该路线的视觉风格与叙事方向。[套图规划](https://github.com/mkhsu2002/EC-Designer/blob/82aca3f0ca42e97640342d134b6195fffa8e37ff/prompts.ts#L92)
- 核心服务实际调用文字模型生成策略/计划，生图阶段可以把商品图片作为 inlineData 连同提示词提交给图片模型，并明确要求保留颜色、材质与品牌身份。[生成服务](https://github.com/mkhsu2002/EC-Designer/blob/82aca3f0ca42e97640342d134b6195fffa8e37ff/services/geminiService.ts#L143)
- 首阶段提示词要求少描述商品结构，集中描述场景和光影，以降低模型重造商品的倾向。但“自动合并商品”是提示词意图，所查核心函数是图片条件生成，不能据此宣称像素级商品合成或绝对保真。
- **实现边界**：所查生成函数得到图片数据后即返回；未见这条路径上的独立视觉质检关卡。其固定 8 图和营销推断也不应原样复制。

适合借鉴：先有明确视觉路线，再写具体构图。比直接让模型从商品参数开始逐张布局，更容易发现“方向本身选错”的问题。

## 3. TheMattBerman/brand-shoot-kit

固定提交：`91026c7056644cc83618bef60e7dafcc34060fc0`。README 宣称 MIT；本次仓库文件检查未发现独立 LICENSE，复用代码前需进一步核实许可文本。

- 提供生成、评分和失败重做脚本。QA 维度包括商品准确性、商业可用性、品牌匹配、场景真实感、清晰度与伪影风险。[QA 实现](https://github.com/TheMattBerman/brand-shoot-kit/blob/91026c7056644cc83618bef60e7dafcc34060fc0/scripts/qa-images.py)
- `--live` 的 QA 确实向视觉模型提交生成图和提示词，读取评分与拒绝原因；失败重做脚本有最大尝试次数以及重新进行 live QA 的选项。[重做脚本](https://github.com/TheMattBerman/brand-shoot-kit/blob/91026c7056644cc83618bef60e7dafcc34060fc0/scripts/reroll-failed.py)
- **关键限制**：QA 请求没有附上原始商品参考图。因此其 product_accuracy 分数不能充分证明与原商品一致；默认非 live 分支还有哈希生成的确定性模拟分数，不能当成视觉评测结果。[QA 请求与模拟逻辑](https://github.com/TheMattBerman/brand-shoot-kit/blob/91026c7056644cc83618bef60e7dafcc34060fc0/scripts/qa-images.py#L41)

适合借鉴：明确失败原因、限制重做次数。我们的实现应同时输入商品原图、目标设计和生成结果，文字另作校验；模拟结果必须清晰标识。

## 4. dhanushreddy291/product-photo-generator-cog

固定提交：`a3af5d123ea72fb6546bb649b50c5eb49f3bdb93`。仓库代码 MIT；依赖模型许可需单独核对。

- 代码读取真实商品图，缩放填充到 512×512，用 transparent_background 得到前景 mask，再反转为背景编辑区域。
- 将原图、mask_image 和 control_image 一起交给 `yahoo-inc/photo-background-generation` 的 diffusion pipeline，提示词主要描述商品环境。[核心实现](https://github.com/dhanushreddy291/product-photo-generator-cog/blob/a3af5d123ea72fb6546bb649b50c5eb49f3bdb93/predict.py)
- **边界**：这是背景生成型演示，不能直接替代中文海报排版、整套营销规划、任意视角重建，也没有可见的生成后审美质检。遮罩条件有助于控制编辑区域，但不能把本次静态代码检查描述成保真效果验证。

适合借鉴：保留商品外观的背景模式，与允许更大构图变化的商业创意模式分开。

## 5. 排除作为核心算法借鉴：Open-AI-Design-Agent

固定提交：`e179fe1a6c47b26ee6afac9128155d9f259a5d14`。仓库 MIT。

README 描述了多步创意代理、模型路由和品牌一致性。但所查服务器的 chat、run-skill、jobs 等接口主要转发到外部 MuAPI；这份仓库无法验证其内部提示词规划与质检算法。可借鉴前端计划展示，不将其作为完整自主生图后端的源码证据。[路由](https://github.com/Anil-matcha/Open-AI-Design-Agent/blob/e179fe1a6c47b26ee6afac9128155d9f259a5d14/server/app/routers/creative_agent_router.py) · [代理实现](https://github.com/Anil-matcha/Open-AI-Design-Agent/blob/e179fe1a6c47b26ee6afac9128155d9f259a5d14/server/app/utils/muapi_helper.py)

## 对照当前项目

以下是当前工作树代码与本次会话已读取任务快照的观察，不代表上述项目的结论。

- `backend/app/application/module_planning_service.py:203` 已把内置规划 Skill 加入系统提示词，并提供风格库；并非完全没接 Skill。
- 同文件第 276 行将 compositionBrief 自动加入模块参数；下游还收到 taskOutline。当前任务的简案已提前决定浅灰背景、小字等细节，容易使后续只作扩写。
- `backend/app/application/module_planning_v2.py` 明确要求在固定风格种子的配色和光线边界内细化。当前任务的“都市办公”方向也确实偏低饱和。
- 本次规划记录 `23e4e151-9f34-4001-959e-5d006b296966` 中 reverseVersionId 为空、referenceAssetIds 为空。不能把本次成图称为使用了已反推的案例。
- `backend/app/application/batch_generation_worker.py:308` 的结果保存路径主要是存图、归档和 complete_slot；这条路径未出现商品原图对照、文字检查或审美评估。生成成功尚不等于视觉合格。

## 建议的最小落地顺序（本次仅调研，尚未实施）

1. 先定义整套视觉方向：受众、主卖点、配色、字体层级、光影以及可用参考。可先给两个真正不同的候选方向，再选一条。
2. 规划大师负责逐图目标与内容节奏。其背景、机位、字号等建议允许下游按选定方向重设；用户明确要求和真实平台约束仍保留。不要简单删掉所有构图信息，具体可执行的最终构图仍有必要。
3. 每次生成明确传入“商品原图 / 风格参考 / 要修改的图片”职责。绑定反推版本时核验它确实进入本次请求。
4. 先生成一张代表图检查方向，通过后作为后续风格参考，再按任务依赖关系并发生成；这是本次综合建议，不是声称全部被调研项目都如此实现。
5. 增加独立质检状态：对照商品原图检查身份，核对已批准文案，检查裁切/文字可读性/整套一致性。失败给具体修改理由，最多重做有限次数，保留历史。
6. 用同一商品、同一模型、同一尺寸比较当前方案与改进方案，记录可用率、商品错误、文字错误、整套一致性、总耗时和成本。未完成该对照前，不承诺更漂亮、更快或更便宜。

本次调研没有证据支持“删除规划大师或只换成另一个 Skill 就一定变好”。更有依据的改进是选对视觉方向、让参考图实际参与、避免上游过早决定全部视觉细节，并补上出图后的检查。
