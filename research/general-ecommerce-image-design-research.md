# 通用电商主图与详情图设计研究

> 范围：适用于多数商品类目的主图、商品图集与详情长图；不针对某个具体品类。来源优先采用一手平台规范、设计工具文档、可追溯的可用性研究与无障碍标准。平台硬性规格会变化，落地时应再次核对目标平台的最新页面。

## 1. 核心结论

1. **主图的第一任务是识别和建立信任，详情图的第一任务是减少购买不确定性。** 主图应让商品在缩略图、搜索结果和首屏中立即可辨；详情图按“整体认识 → 关键特征 → 使用/尺度 → 证据与规格 → 风险消除”的顺序组织，而不是把每张图都当成海报。
2. **视觉层级必须只有一个首要焦点。** 用尺寸、位置、对比、色彩、留白、对齐和邻近关系建立阅读路径；标题、卖点、商品和装饰不能同时争夺最大权重。Figma 将这些关系列为建立视觉层级的基础方法（[Visual hierarchy](https://www.figma.com/resource-library/what-is-visual-hierarchy/)）。
3. **网格和间距是可复用的约束，不是装饰线。** 用列、行、外边距、内边距和间距锁定文本、商品和标注的对齐；Figma 的布局指南明确把网格用于跨平台一致性、页面结构和图库等布局（[Layout guides](https://help.figma.com/hc/en-us/articles/360040450513-Create-layout-guides)）。
4. **留白承担分组和焦点功能。** 留白应围绕焦点、模块边界和阅读节奏分配；不要为了“填满”画面而堆图标、渐变、纹理或无证据的参数。
5. **商品信息的可信度优先于视觉冲击。** 正面/三分之四视图、细节特写、背面/接口、包装清单、使用场景和至少一张能判断尺度的图，分别回答不同问题。Baymard 观察到 56% 的受试者到达详情页后的第一动作是探索商品图，并指出商品需要至少一张 `in-scale`（有尺度参照）图片（[image resolution and zoom](https://baymard.com/research-articles/ensure-sufficient-image-resolution-and-zoom)、[in-scale image](https://baymard.com/research-articles/in-scale-product-images)）。
6. **移动端要按“拇指可操作、单列可扫读、可放大检查”设计。** Baymard 的测试显示，缩略图比点状指示器更能说明还有哪些图；商品图还应支持双击/捏合放大并提供足够分辨率（[thumbnails](https://baymard.com/research-articles/always-use-thumbnails-additional-images)、[mobile image gestures](https://baymard.com/research-articles/mobile-image-gestures)）。

## 2. 主图设计规则

### 2.1 角色与信息优先级

- `P0 识别`：商品主体、品名/品类线索、颜色或关键形态。缩小到搜索卡片后仍应可辨。
- `P1 差异`：一个最有说服力的差异点，例如结构、材质、尺寸、容量或使用结果；只选一个主卖点。
- `P2 信任`：真实纹理、边缘、阴影、比例和不夸张的修图；避免让背景、道具或特效抢走主体。
- `P3 装饰`：品牌色、场景道具、氛围元素。装饰不能遮挡商品、关键文字或导致主体轮廓消失。

主图通常采用单主体、干净背景和稳定视角；若平台要求纯白背景或禁止文字/水印，以平台规则为最高优先级。Shopify 的官方产品摄影建议用白色背景减少干扰、让商品成为焦点，并用多角度照片展示顾客可能关心的不同视角（[Taking product photographs](https://help.shopify.com/en/manual/products/product-media/product-photography)）。

### 2.2 构图、比例与留白

- 先定义安全框：商品边界、裁切容错区、平台叠加 UI 区和文字区；再决定商品占画布比例。
- 主体应在小尺寸下保留轮廓和关键操作/接口；不要把商品缩得过小，也不要贴边到无法判断比例。
- 如果主图需要文字，文字只承担一个承诺，放在与商品轮廓分离的负空间内；避免把小字压在复杂纹理或高光上。
- 以三分法、中心对齐或稳定的左右分区作为起点，选择依据是信息关系而不是套模板。需要为后续详情图保留可重复的对齐线和品牌边距。
- 同一套图片使用一致的比例和主体尺度。Shopify 指出，集合页并排展示时，统一宽高比有助于图片显示一致；方形商品图通常以 2048×2048 px 显示效果较好（[Product media types](https://help.shopify.com/en/manual/products/product-media/product-media-types)）。这不是所有平台的硬性尺寸，应作为高分辨率起始值而非强制规则。

### 2.3 光线、色彩与真实性

- 光线先服务于轮廓、材质和颜色辨识，再服务于氛围；避免过度高光、色偏、锐化和阴影遮蔽真实细节。
- 主色用于品牌/卖点，强调色用于一个 CTA 或一个关键标签，背景色用于衬托；控制色相数量，确保非色彩线索也能传达信息。
- 不能只靠颜色区分状态、规格或差异；加入文字、形状、位置、图标或纹理。W3C 的 WCAG 说明色相和饱和度对低视力/色觉差异用户并不可靠，文本与背景应有至少 4.5:1 对比度（大字号 3:1）（[WCAG 1.4.3](https://www.w3.org/WAI/WCAG21/Understanding/contrast-minimum)）。
- 对照片上的文字提供纯色底、渐变遮罩或独立文本区，并在实际最复杂背景上检查对比度；不要只在设计软件的纯色样本上验收。

## 3. 详情图/详情长图的阅读节奏

### 3.1 推荐叙事骨架

可按商品实际问题删减，但顺序应让用户逐步降低风险：

1. **Hero/总览**：一句价值主张 + 清晰的完整商品；不重复主图的所有装饰。
2. **差异点**：一张图只证明一个关键卖点，用局部放大、剖面、结构拆解或对比说明。
3. **使用场景**：展示真实使用动作、环境和人与商品的关系；场景应提供功能证据，不只是情绪背景。
4. **尺度与兼容**：实物参照、尺寸线、容量、接口、适配范围或包装内物品；明确测量口径。
5. **细节证据**：材质、工艺、边缘、开合、连接、按钮、纹理等近景。
6. **规格与清单**：表格/短行列出参数、包装内容、限制和售后要点，避免把关键事实藏在图片小字里。
7. **收束**：用一张简洁图复述核心利益或下一步；不新增未经前文解释的承诺。

每个模块只回答一个问题，并在相邻模块之间改变至少一个维度（景别、视角、背景明度、版式、信息密度或商品出场方式）。避免连续多张完整商品、同一角度和同一标题模板造成“滚动疲劳”。

### 3.2 版式、网格与分组

- 详情长图采用单一主网格：例如 4/6/8 列中的一种，所有标题、图像、尺寸线和卡片边缘吸附到列线；移动端折叠为单列或两列。
- 定义 `outerMargin`、`columnCount`、`gutter`、`sectionGap`、`cardPadding` 五个基础参数；用间距区分模块，用边框/背景只强化必要分组。
- Figma 的 Auto Layout 文档把 padding 定义为容器边缘与子对象之间的空白，把 gap 定义为对象之间的距离，可将这两类值直接映射为可执行的布局 tokens（[Auto layout spacing](https://help.figma.com/hc/en-us/articles/360040451373-Guide-to-auto-layout)）。
- 同级标题使用同一字号/字重/基线规则，正文行长适中，列表和表格保持重复的列对齐；不要用不同字体、描边、阴影来伪造层级。

### 3.3 字体与文字密度

- 设定最多两套字体角色：品牌展示字体（可选）+ 正文/参数字体；同一张图不要混用过多字体。
- 用大小、字重、颜色和间距建立 `title > subtitle > body > caption` 层级；关键规格优先于修饰性 slogan。
- 避免超细字重、全大写长句、低对比灰字和图片内过小的参数。Apple 的设计建议强调避免文字重叠、增加行高/字距提升可读性，并要求移动界面不应依赖缩放或横向滚动才能看到主要内容（[UI Design Dos and Don’ts](https://developer.apple.com/design/tips/)）。
- 文字放进图片后，仍需保留可读的实际字号、对比度和安全边距；重要信息不要只存在于不可复制/不可放大的装饰字中。

## 4. 移动端与图集规则

- 默认按窄屏首屏检查：主体、标题和最重要的差异点在不缩放时可理解；详情长图每个模块先给结论，再给细节。
- 商品图集使用可见缩略图或明确的横向溢出提示，不只使用小圆点；Baymard 发现点状指示器容易让用户漏掉图片，而缩略图同时提供数量和内容线索（[Always use thumbnails](https://baymard.com/research-articles/always-use-thumbnails-additional-images)）。
- 支持点击、滑动、双击和捏合放大；放大时加载高分辨率源图。不能把关键文字、接口标签或材质证据放在无法放大的低分辨率图上（[Mobile gestures](https://baymard.com/research-articles/mobile-image-gestures)）。
- 触控目标和相邻可点击区域要有足够间隔；Apple 的通用建议是触控控件至少 44×44 pt，同时保持高分辨率资源、原始宽高比和与内容对应的对齐（[UI Design Dos and Don’ts](https://developer.apple.com/design/tips/)）。
- 使用响应式裁切时定义 focal point 和最小可见主体面积；不能在窄屏裁掉商品关键部件或尺寸标注。图片应保留原始比例，避免拉伸变形。
- 性能与清晰度要一起验收。Shopify 建议上传高质量原图、由 CDN/主题选择合适格式与尺寸，并提醒过大的图片会拖慢页面；不要为了文件小而产生明显块状压缩（[Uploading images](https://help.shopify.com/en/manual/online-store/images/theme-images)、[Taking product photographs](https://help.shopify.com/en/manual/products/product-media/product-photography)）。

## 5. 可转成 AI 规划规则的字段

建议规划器先输出套图级字段，再输出每张图字段；字段应可比较、可审稿，而不是只写审美形容词。

```json
{
  "set": {
    "channel": "marketplace|brand_store|social_ad",
    "viewportTargets": ["desktop", "mobile"],
    "primaryGoal": "identify|differentiate|explain|reassure|convert",
    "narrativeStages": ["overview", "feature", "scenario", "scale", "detail", "spec", "close"],
    "platformConstraints": {"background": "white|brand|contextual", "maxTextDensity": "low"},
    "visualSystem": {"grid": {"columns": 6, "gutter": 24, "outerMargin": 48}, "spacingScale": "4-based", "fontRoles": 2, "accentColors": 1},
    "mobilePolicy": {"singleColumn": true, "zoom": true, "thumbnailMode": "visible_thumbnails", "safeCrop": true}
  },
  "image": {
    "sequence": 3,
    "pageRole": "main|detail|longform",
    "narrativeStage": "scale",
    "informationQuestion": "How large is it in real use?",
    "productPresence": "full|partial|detail|none",
    "subjectScale": "large|medium|small",
    "camera": "front|three_quarter|side|top|macro|exploded",
    "layoutFamily": "centered_hero|split_copy_product|grid_callout|comparison|spec_table",
    "focalPoint": "product|feature|text|diagram",
    "gridBinding": {"columns": [1, 4], "safeMargin": 48},
    "text": {"headlineMaxChars": 18, "bodyMaxLines": 4, "density": "low|medium|high", "contrastMin": 4.5},
    "evidence": ["in_scale_reference", "dimension_line"],
    "assetRequirements": {"minResolution": "zoom_safe", "aspectRatio": "1:1", "altText": true},
    "avoid": ["repeat_previous_angle", "unsupported_claim", "tiny_spec_text", "decorative_clutter"]
  }
}
```

字段解释：`informationQuestion` 防止一张图承担多个任务；`narrativeStage` 和 `sequence` 控制阅读节奏；`productPresence`/`subjectScale` 让整套图不连续重复完整商品；`layoutFamily`/`gridBinding` 把版式变成可生成约束；`evidence` 要求每个卖点有可见依据；`text.density`、`contrastMin`、`mobilePolicy` 负责移动可读性；`avoid` 为负向审稿规则。

## 6. AI 生成后的审稿清单

### 硬性失败（任一项即返工）

- 商品被裁切、变形、遮挡，或颜色/纹理与真实资产不一致。
- 主图在缩略图尺寸下无法识别；详情图关键证据在移动端不可见或无法放大。
- 文字与背景对比不足（普通文字低于 4.5:1；大字低于 3:1），或仅靠颜色传达关键状态。
- 平台要求的背景、比例、禁用元素、文件格式/大小不满足；以目标平台最新官方规则复核。
- 关键参数、包装清单、兼容性或承诺没有来源/商品资产依据。

### 质量评分（每项 0–2 分）

1. **识别**：商品和品类是否一眼可辨？
2. **层级**：是否只有一个焦点，标题/卖点/商品权重是否明确？
3. **构图**：主体、文字、道具是否按网格对齐，留白是否支持阅读？
4. **差异**：相邻图片是否改变景别、视角或信息任务，是否避免重复？
5. **证据**：每个卖点是否有可见的结构、场景、尺度或规格证据？
6. **真实性**：光线、阴影、比例、颜色、边缘和文字是否可信？
7. **可读性**：字体、行长、行高、对比、文字密度在手机截图上是否清楚？
8. **移动交互**：图集是否有缩略图/溢出提示、放大手势和高分辨率源图？
9. **套图节奏**：是否从总览逐步深入，是否在收束时复述而非引入新信息？
10. **系统一致性**：网格、字体角色、色彩 tokens、圆角/阴影和品牌边距是否跨图一致？

建议阈值：硬性失败为 0；总分至少 16/20；“识别、层级、证据、可读性”四项任何一项低于 2 分都需要人工复核。审稿时至少查看桌面原图、移动端首屏缩略图、图集缩略图和放大态四种状态。

## 来源索引

- Figma，[Visual hierarchy](https://www.figma.com/resource-library/what-is-visual-hierarchy/)
- Figma，[Create layout guides](https://help.figma.com/hc/en-us/articles/360040450513-Create-layout-guides)
- Figma，[Guide to auto layout](https://help.figma.com/hc/en-us/articles/360040451373-Guide-to-auto-layout)
- Shopify，[Product media types](https://help.shopify.com/en/manual/products/product-media/product-media-types)
- Shopify，[Taking product photographs](https://help.shopify.com/en/manual/products/product-media/product-photography)
- Shopify，[Uploading images](https://help.shopify.com/en/manual/online-store/images/theme-images)
- Baymard，[Ensure sufficient image resolution and zoom](https://baymard.com/research-articles/ensure-sufficient-image-resolution-and-zoom)
- Baymard，[All products need at least one in-scale image](https://baymard.com/research-articles/in-scale-product-images)
- Baymard，[Always use thumbnails for additional images](https://baymard.com/research-articles/always-use-thumbnails-additional-images)
- Baymard，[Mobile image gestures](https://baymard.com/research-articles/mobile-image-gestures)
- W3C，[WCAG 1.4.3 Contrast (Minimum)](https://www.w3.org/WAI/WCAG21/Understanding/contrast-minimum)
- Apple，[UI Design Dos and Don’ts](https://developer.apple.com/design/tips/)

