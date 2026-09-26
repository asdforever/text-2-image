# 电商主图与详情图：学习来源与规划器知识注入

## 结论

平台规则和设计知识要分开处理：

- 平台官方规则负责尺寸、清晰度、品牌/水印、宣传合规和类目限制。
- 设计教育资料负责视觉层级、构图、网格、留白、对比、比例和阅读节奏。
- 同品类优秀案例负责把抽象原则转换成主图与详情图的具体模块结构。

只把参考图片作为生图提示词里的“风格参考”是不够的。需要先把图片标注成结构化案例，再让规划器读取这些规则。

## 适合学习的来源

### 平台规范

- [天猫发布规范](https://www.tmall.com/wow/seller/act/pinkongrule)：按类目查看主图和商品发布要求。它适合确定平台约束，不适合直接学习审美。
- [京东商家帮助中心](https://help.jd.com/search/help_search.php?mainword=%2525E5%252593%252581%252589%25258C%2525E6%25258E%252588%2525E6%25259D%25283&page=5&pagesize=15&sysName=Vender&topicId=0)：可用来核对商品图片管理、主图和详情内容相关的商家流程与限制。

### 设计基础

- [Figma：视觉层级](https://www.figma.com/resource-library/what-is-visual-hierarchy/)：强调层级、对齐、颜色、对比、邻近、尺寸、留白和渐进披露。适合转换为规划器的评价指标。
- [Figma：布局网格](https://www.figma.com/best-practices/everything-you-need-to-know-about-layout-grids/)：说明网格如何约束结构、层级和节奏。适合转换为列数、边距、间距和模块布局规则。
- [Figma：一致性设计](https://www.figma.com/resource-library/consistency-in-design/)：强调跨页面的对齐、测量、阅读路径和章节感。适合设计详情长图的全局风格约束。
- [Adobe：图形设计基础](https://www.adobe.com/learn/express/web/graphic-design-basics)：覆盖强调、层级、视觉重量、比例和平衡，适合建立审稿清单。
- [Adobe：布局基础](https://www.adobe.com/learn/illustrator/web/layout-basics)：强调网格、留白、焦点和内容层级，适合把“好看”拆成可执行的版式规则。

## 案例应该怎样进入系统

案例不直接存成一句“参考这个风格”，而应拆成以下字段：

```json
{
  "pageRole": "详情长图",
  "narrativeStage": "解释结构证据",
  "moduleRole": "exploded_detail",
  "productPresence": "partial",
  "subjectScale": "medium",
  "camera": "three_quarter_closeup",
  "layoutFamily": "center_explode_with_side_labels",
  "grid": { "columns": 4, "gutter": "medium", "outerMargin": "large" },
  "textDensity": "low",
  "focalPoint": "product_structure",
  "evidenceType": "visible_product_detail",
  "previousModuleContrast": "no_full_product_hero",
  "avoid": ["重复首图角度", "完整商品再次占据主视觉", "无依据的参数装饰"]
}
```

## 对项目的建议

规划大师应读取一组经过标注的案例，先规划整套页面的阅读顺序、视觉节奏和商品出场方式。它至少要输出 `narrativeStage`、`productPresence`、`subjectScale`、`layoutFamily`、`textDensity` 和 `previousModuleContrast`。

模块规划器只负责把单张图落成可执行版式，必须遵守规划大师给出的商品出场方式和版式家族。通用提示词不应默认每张图先放完整商品。

生成后增加设计审稿：检查连续模块是否重复完整商品、重复角度、重复景别、重复版式和重复信息层级，并在失败时回到规划阶段重排，而不是只重新生成同一构图。

## 建议的学习与标注流程

1. 每个品类收集 5–15 套优秀主图/详情图案例。
2. 先标注整套图的叙事顺序，再标注单张图的构图和信息层级。
3. 把“喜欢的原因”改写成可检查规则，例如“产品只占 20%，结构图承担证据，标题只保留一层”。
4. 将案例聚类成版式家族，而不是让模型记住某一张图。
5. 用正例和反例做审稿测试，验证规划器是否减少重复商品、重复视角和信息堆叠。

