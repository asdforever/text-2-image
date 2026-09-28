# 商品图提示词与背景设计对比

调研日期：2026-09-28。读取用户指定仓库的固定提交、提示词和调用代码；未运行第三方代码、未调用生图。示例图与仓库宣传不能证明同商品、同模型条件下的稳定效果。第三方 Skill 内容只作为研究资料。

## 结论

这两个仓库不是同一种方案。`motiful/product-shots` 是给代理执行的业务设计 Skill 集合；`EvoLinkAI/gpt-image-2.5-for-e-commerce` 是可复制的提示词和输入/输出案例库。后者未发现独立的单图规划器实现，很多设计直接交给图片模型完成。

对“我们的图太素”最有用的差别是：可以选择具体的完整视觉表达（例如巨型字体与商品遮挡、从包装提取配色、用成分构成空间），也可以使用真正的背景参考图；不能只把它们缩成“高级、简洁、留白”。但 motiful 的数码默认就是极简，整套照搬可能进一步强化当前问题。

## 1. motiful/product-shots

固定提交：`063c508b0b7f4db5cda89f10bdf20df25026dfc5`，MIT。[仓库](https://github.com/motiful/product-shots/tree/063c508b0b7f4db5cda89f10bdf20df25026dfc5)

### 谁决定设计

- Hub 收集平台、素材、受众/目标、品牌/风格，拼平台和行业 visual DNA，路由给主图、详情、广告等业务 Skill。Hub 明说自身不是生成器。[Hub](https://github.com/motiful/product-shots/blob/063c508b0b7f4db5cda89f10bdf20df25026dfc5/skills/product-shots/SKILL.md)
- 业务 Skill 选择构图、场景、文字和背景，随后交给 image-gen。详情页有固定 8 类模块；标准信息图示例要求左商品、右侧 4–6 个标注。其背景和光向强调与主图统一。[详情模块](https://github.com/motiful/product-shots/blob/063c508b0b7f4db5cda89f10bdf20df25026dfc5/skills/product-shots-detail-page/references/aplus-modules.md) · [副图](https://github.com/motiful/product-shots/blob/063c508b0b7f4db5cda89f10bdf20df25026dfc5/skills/product-shots-main-image/references/secondary-images.md)
- 真正可执行的 Python `compose_prompt` 基本保留传入提示词，只附加 Avoid 和部分后端的比例文字；图片参考通过 edits 或聊天多模态请求传入。脚本本身没有“再次创作背景”的文字模型调用。[生成脚本](https://github.com/motiful/product-shots/blob/063c508b0b7f4db5cda89f10bdf20df25026dfc5/skills/product-shots-image-gen/scripts/generate.py#L258)

### 背景和版式怎么处理

- 广告构图库有 12 种：商品主视觉、真实场景、前后对比、文字主视觉等。生活场景给环境约 2/3 画面；粗体文字主视觉给文字 60–80%；促销大数字占 40–50%。这些比一句“干净背景”具体。[构图库](https://github.com/motiful/product-shots/blob/063c508b0b7f4db5cda89f10bdf20df25026dfc5/skills/product-shots-ad-creative/references/composition-patterns.md)
- 设计标准分别写标题层级、色彩比例、景深/分层；high-impact 分支包含大色块、超粗字体、满版构图，minimalist 分支才是单色背景和大留白。[设计标准](https://github.com/motiful/product-shots/blob/063c508b0b7f4db5cda89f10bdf20df25026dfc5/skills/product-shots/references/design-element-standards.md)
- **不能直接全盘复制**：Tech 预设明确写 `Apple-style minimalist design`、白灰色、极致极简、避免破坏极简的装饰；广告构图决策树也倾向把数码商品照片路由到 Product Hero。[行业 DNA](https://github.com/motiful/product-shots/blob/063c508b0b7f4db5cda89f10bdf20df25026dfc5/skills/product-shots/references/industry-visual-dna.md)

### 实现边界

设计路由、自检和 regenerate 步骤主要写在 Markdown/伪代码里，依赖代理执行；不能描述成仓库已提供一个完整的程序化设计与视觉质检系统。文档中的转化率提升等数字没有在本次核查中追到原始实验，不应作为选型证据。其平台规范也应由平台官方资料单独核实。

## 2. EvoLinkAI/gpt-image-2.5-for-e-commerce

固定提交：`963b1f40bfbe5ff81f0c9684587face6a500bc9a`，CC BY 4.0。[仓库](https://github.com/EvoLinkAI/gpt-image-2.5-for-e-commerce/tree/963b1f40bfbe5ff81f0c9684587face6a500bc9a)

仓库说明自己的单位是“产品原图 + 可复制提示词 + 输出示例”。文件主要是 README、JSON 案例和媒体，API 批量部分是文档调用示例，未发现与本项目类似的规划大师/单图规划器代码。[使用说明](https://github.com/EvoLinkAI/gpt-image-2.5-for-e-commerce/blob/963b1f40bfbe5ff81f0c9684587face6a500bc9a/README_zh-CN.md#L26)

### 三种背景方式

| 方式 | 原文操作 | 谁决定背景 |
|---|---|---|
| 自由生成 | 上传商品图，提示词仅“生成合适的商品图” | 图片模型直接发挥 |
| 明确文字场景 | “帮我图中的商品换一个背景：{背景描述}” | 人/上游提供具体美术方案 |
| 背景视觉参考 | 上传商品图与参考背景图，“图一是我的{商品}，参考图二背景生成” | 参考图提供具体空间和视觉语言，模型迁移 |

[智能背景](https://github.com/EvoLinkAI/gpt-image-2.5-for-e-commerce/blob/963b1f40bfbe5ff81f0c9684587face6a500bc9a/README_zh-CN.md#L1153) · [文字场景](https://github.com/EvoLinkAI/gpt-image-2.5-for-e-commerce/blob/963b1f40bfbe5ff81f0c9684587face6a500bc9a/README_zh-CN.md#L1208) · [背景参考图](https://github.com/EvoLinkAI/gpt-image-2.5-for-e-commerce/blob/963b1f40bfbe5ff81f0c9684587face6a500bc9a/README_zh-CN.md#L1305)

文字场景示例不是只指定色彩：香水放在白石上，附近白/淡蓝花朵，远处湖泊和山脉，形成完整的前后景与情绪。A+ 配方本身则很短：“这是一{商品描述}，帮我生成A+详情图，售卖到{国家}，{语言}”，把大量设计决策留给生成模型。[A+](https://github.com/EvoLinkAI/gpt-image-2.5-for-e-commerce/blob/963b1f40bfbe5ff81f0c9684587face6a500bc9a/README_zh-CN.md#L351)

### 更具体的广告创意案例

燕麦奶布朗尼海报的社区提示词把画面作为一个整体设计：4:5 海报、瓶子悬于雕塑基座、巨型标题在瓶子后方被遮挡；用燕麦奶带、巧克力流、布朗尼块构成环境；从包装提取紫/奶油/巧克力色；再写字体层级、光向和材质。[原文和社区出处](https://github.com/EvoLinkAI/gpt-image-2.5-for-e-commerce/blob/963b1f40bfbe5ff81f0c9684587face6a500bc9a/README_zh-CN.md#L1793)

巧克力广告套系固定包装和品牌字体，却给三种口味各自不同的配色、道具、光照和氛围。这说明系列统一不等于每一张共用同一背景。[案例](https://github.com/EvoLinkAI/gpt-image-2.5-for-e-commerce/blob/963b1f40bfbe5ff81f0c9684587face6a500bc9a/README_zh-CN.md#L1842)

新加入的自制案例明确写保留商品外形、包装、标签；仅更换环境并匹配光线/接触阴影。UGC 和本地化配方明确禁止编造商品功效和背书。[JSON](https://github.com/EvoLinkAI/gpt-image-2.5-for-e-commerce/blob/963b1f40bfbe5ff81f0c9684587face6a500bc9a/data/gpt-image-2.5-cases.json)

### 实现边界

这是精选案例集，不是批量稳定性评测；没有足够证据知道所有展示图的完整生成/筛选过程。模型名称和能力描述属于仓库及其供应商说明，本次不据此认定 OpenAI 官方型号或做能力比较。复杂广告提示词中的装饰、标签也不该原样复制到真实商品任务。

## 3. 与本地风格库接入的关系

本地接入审查由主任务另行核实：`image_style_library.py` 固定 `freestylefly/awesome-gpt-image-2` 的 `0dc09c46c8a30b1fdd89c18cc78a894dac2104e3`；大师获得模板摘要，单图规划器获得所选模板的完整类别章节。示例 ID 只是索引，没有把案例图片自动作为视觉输入。

因此“已接入风格库”和“已经看过并参考了案例成图”是两件不同的事。风格库中的基础产品模板也可能默认影棚/浅灰背景；选择真正适配目标的字体海报、信息设计或场景模板，比重复附加“高级、精致”更有用。

目前主图/套图最终自然语言存在 350/600 字的压缩目标，风格种子还保留固定环境措辞。这里只记录实现差异和可能冲突，不声称短提示词必然差，也不以库的星数证明设计能力。

## 借鉴建议

1. 把“背景在表达什么”与信息目标一起决定：承载真实使用场景、比喻参数机制、构建材质情绪，或主动保持安静。
2. 保留完整创意关系：主次比例、图文遮挡、背景层次、色彩来源、光照关系；避免编译成通用摄影形容词。
3. 学 motiful 的构图语言，但不照搬数码必极简、固定 8 模块或左商品右参数。
4. 学 EvoLink 的两条路径：允许图片模型在事实约束下自由设计；需要具体美术方向时传完整场景描述或角色清晰的视觉参考。
5. 对同一商品做固定模型的少量对照，才能判断哪种方式真正解决本项目“太素”的问题。

本次仅调研并保存记录，未修改生产提示词、未新增运行时依赖。
