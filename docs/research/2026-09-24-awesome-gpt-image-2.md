# awesome-gpt-image-2 调研

调研日期：2026-09-24

## 范围与仓库辨识

GitHub 上存在多个同名仓库。本次主调研对象是 [freestylefly/awesome-gpt-image-2](https://github.com/freestylefly/awesome-gpt-image-2)，因为它包含可安装的 Agent Skill、模板文档、结构化 style library 和商品/电商分类；同时记录 [YouMind-OpenLab/awesome-gpt-image-2](https://github.com/YouMind-OpenLab/awesome-gpt-image-2) 作为另一个同名候选。后者更像大规模提示词和预览图集合，主页声明有 2000+ 条提示词、16 种语言，但没有足够证据表明它能直接替代本项目的规划和执行链路。

## 关键发现

### 1. 它把提示词当作可组合资产，而不是一段长文本

freestylefly 的项目愿景是把散落案例压缩成可复用的 Prompt-as-Code；README 明确强调把主体、光线、材质、布局和视觉细节拆成原子部分，并服务于代理、脚本和自动化工作流。

来源：[README](https://github.com/freestylefly/awesome-gpt-image-2#project-vision)

它的 Skill 要求按以下顺序选型：

1. 模板类别；
2. 视觉风格标签；
3. 场景标签；
4. 最近的案例；
5. 输出由主体任务、构图布局、风格材质、文字要求、比例和约束组成。

来源：[gpt-image-2-style-library/SKILL.md](https://github.com/freestylefly/awesome-gpt-image-2/blob/main/agents/skills/gpt-image-2-style-library/SKILL.md)

### 2. 对我们最有价值的是“模板 + 标签 + 案例”三层结构

其 data/style-library.json 不是简单的 prompt 列表，而是保存类别、模板锚点、风格标签、场景标签、封面和示例案例。与商品详情图最相关的是：

- product-commerce-visual
- infographic-engine
- poster-layout-system
- sports-campaign-poster
- scientific-scale-diagram

来源：[style-library.json](https://github.com/freestylefly/awesome-gpt-image-2/blob/main/data/style-library.json)、[生成的 style-library 参考](https://github.com/freestylefly/awesome-gpt-image-2/blob/main/agents/skills/gpt-image-2-style-library/references/style-library.md)

### 3. 商品模板本身不够“有创意”，但它指出了缺失的输入

商品模板要求明确：

- 商品是什么；
- 卖点是什么；
- 材质；
- 场景；
- 镜头；
- 光线；
- 附加元素；
- 输出格式。

JSON 模板还把 product、setting、copywriting、constraints 分开。

来源：[商品与电商模板](https://github.com/freestylefly/awesome-gpt-image-2/blob/main/docs/templates.md#tpl-product)

它的避坑规则里有两条正好击中我们当前问题：

- 材质和光影必须具体，否则容易变成廉价商品图；
- 促销文字只保留 1–2 条，不能把画面塞满。

但这个模板仍然主要是“商品 + 场景 + 卖点 + 文字”，没有独立的“大创意/主动作”字段。所以直接照搬，仍可能生成漂亮但普通的产品渲染图。

### 4. 它对“创意”的处理方式比我们当前更接近广告设计

在海报、运动 Campaign 和概念字体模板中，它反复要求：

- 只做一张完成稿，不要 moodboard 或过程展示；
- 让标题成为视觉结构，而不是普通说明文字；
- 明确主体姿态、核心道具、版式、品牌色和数据层；
- 使用强层级、少元素、留白和视觉张力；
- 避免随机图标、通用字效、杂乱拼贴和无关装饰。

来源：[海报与排版模板](https://github.com/freestylefly/awesome-gpt-image-2/blob/main/docs/templates.md#tpl-poster)

这说明它的有效部分不是某几个“高级感”形容词，而是把视觉结果写成结构和关系。

## 与当前项目的对照

当前项目的 V2 已经有：

- informationQuestion
- productPresence
- subjectScale
- layoutFamily
- evidence
- previousModuleContrast
- avoid

这些字段能控制“这张图要证明什么、商品出现多少、版式怎么变化”，但仍缺少：

- bigIdea：一句话大创意；
- visualMechanism：卖点如何在画面里发生；
- graphicSystem：圆盘、波形、刻度、轨迹等视觉证据的组合；
- textPlan：标题、数据和说明的层级；
- referenceCases：采用哪类成熟案例的结构；
- genericTropesToAvoid：明确禁止泛化科技光效。

因此我们现在的规划比普通 prompt 已经更结构化，但还没有真正的“创意导演层”。

## 对当前鼠标项目的落地建议

不建议安装整个仓库，也不建议把它的提示词原文直接复制进生产配置。建议只吸收三件事：

### A. 增加一个本地模板路由层

针对鼠标详情页，可以先固定三类模板：

- product-commerce-visual：主视觉和产品卖点；
- infographic-engine：DPI、回报率、尺寸、结构；
- poster-layout-system 或 sports-campaign-poster：品牌 Campaign 视觉。

每个模板只提供结构骨架，不提供固定产品内容。

### B. 给规划器增加“创意卡”

建议在 PlannedModule 和最终提示词编译之间增加：

    {
      "bigIdea": "鼠标正在精密控制台上完成一次校准",
      "visualMechanism": "产品压住校准圆盘，波形从传感器位置延伸出来",
      "compositionGeometry": "偏心主体 + 背后大型圆盘 + 底部数据条",
      "graphicSystem": ["校准圆盘", "波形", "测量标记"],
      "textPlan": ["主标题", "核心参数", "短说明"],
      "referenceCases": ["scientific-scale-diagram", "infographic-engine"],
      "genericTropesToAvoid": ["泛蓝渐变", "随机光环", "粒子填空"]
    }

### C. 用后验评审筛掉“风格对但创意弱”的图

在生成结果入库前，增加人工或模型评审项：

- 不看文字时，是否仍有一个明确主动作；
- 产品是否是画面主角；
- 画面中的辅助物是否在证明卖点；
- 把产品替换成普通鼠标后，概念是否仍然成立；
- 是否只是蓝色背景、光带、粒子和几何线的组合；
- 是否有足够的版式层级和留白。

## 不建议照搬的部分

- 不把这个仓库当作生产运行时依赖；
- 不把案例图和提示词自动导入为用户可用素材；
- 不把“文字必须清晰”当作后验质量保证；
- 不把商品模板中的价格角标、促销徽章等默认元素直接带进我们的模块；
- 不用它的案例替代真实商品事实和当前项目的资产快照。

## 许可与使用边界

freestylefly 仓库标注为 MIT，可复用代码和模板，但仍应保留版权与许可声明。[LICENSE](https://github.com/freestylefly/awesome-gpt-image-2/blob/main/LICENSE)

YouMind 仓库的主页标注为开源，但本次没有把其提示词和示例内容导入项目，原因是同名仓库之间的内容来源、示例图权利链和具体许可范围需要逐项核验。

## 结论

这个项目值得借鉴的不是“提示词商城”，而是它的组织方式：

> 先从模板类别和案例中选视觉结构，再填入商品事实，最后生成一份有明确构图、文字层级和负向约束的提示词。

对我们最重要的改动是给 V2 增加“大创意”和“视觉机制”两层。否则即使接入更多 prompt，也只会把现在的普通蓝色产品图生成得更稳定。

