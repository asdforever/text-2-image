# 普通模式技能接入核实

2026-09-28；只读一手文件，未执行第三方代码或修改生产代码。

## 结论

EvoLink 是“商品图＋配方＋示例”的案例库，没有独立 Skill/规划器。product-shots 是入口 Hub、五个领域 Skill 和生图后端；不应把两个仓库的完整提示词叠加。[E1][P1]

## 原生边界

| 模块 | 核实结果 |
| --- | --- |
| Hub | 四阶段、0–5 轮澄清，再注入平台/行业 DNA；普通模式不必启动。 |
| main-image | Amazon 专用；明确主图可只出 1 张，“产品图/套图”默认 7 张。 |
| detail-page | Amazon A+ 默认 8 模块，允许指定子集；要求主图锚点。 |
| ad-creative | 六步设计；缺字段会回 Hub。brand_kit 在必需字段伪代码与“可选”正文间存在矛盾。 |
| social-post | 有单图默认格式，也有轮播、自检流程；可直接使用领域模块。 |
| multi-angle | 人物九连拍；强制参考图、14 变量、风格选择，默认 9 张。不能等同普通商品多角度。 |

来源：[P1–P6]。完整照搬领域 Skill 仍会带入数量、流程、自检和 image-gen 依赖；精简接入应标注为本地改编。

## 推荐路由

1. 换背景、手持互动、试穿、商品多角度、本地化、自由创意图：选一个 EvoLink 配方。
2. 明确 Amazon 主副图/A+、平台广告/社媒、人物九连拍：选一个 product-shots 领域模块。
3. 单次编译只含用户事实、一个来源、批准文案、数量比例和必要约束；绑定真实参考图角色。保留现有模型供应商。
4. 普通模式使用独立轻量 builder，绕过完整 V2 规划协议；来源并列索引，不串联完整流程。

数量服从用户，不继承 3/7/8/9 默认；“主图”不自动等于 Amazon 白底。EvoLink JSON 硬编码的 yellow packaging/skincare 要替换；不得带入示例商品色和品类。用户没给的品牌资产、优惠和功效不能编造。[E2]

验收：每次只有一个 source_id；无未填占位符；请求单张不生成拼贴；参考图实际传入；不把具体场景、图文遮挡压成“高级简洁”。这些仓库未证明稳定质量提升，需同商品同模型小样对比。

## 固定来源

EvoLink：`963b1f40bfbe5ff81f0c9684587face6a500bc9a`，CC BY 4.0；product-shots：`063c508b0b7f4db5cda89f10bdf20df25026dfc5`，MIT。改编保留归属、许可和修改说明。

- [E1 使用说明](https://github.com/EvoLinkAI/gpt-image-2.5-for-e-commerce/blob/963b1f40bfbe5ff81f0c9684587face6a500bc9a/README_zh-CN.md#L30)
- [E2 自制配方](https://github.com/EvoLinkAI/gpt-image-2.5-for-e-commerce/blob/963b1f40bfbe5ff81f0c9684587face6a500bc9a/data/gpt-image-2.5-cases.json)
- [P1 Hub](https://github.com/motiful/product-shots/blob/063c508b0b7f4db5cda89f10bdf20df25026dfc5/skills/product-shots/SKILL.md)
- [P2 主副图](https://github.com/motiful/product-shots/blob/063c508b0b7f4db5cda89f10bdf20df25026dfc5/skills/product-shots-main-image/SKILL.md)
- [P3 A+](https://github.com/motiful/product-shots/blob/063c508b0b7f4db5cda89f10bdf20df25026dfc5/skills/product-shots-detail-page/SKILL.md)
- [P4 广告字段](https://github.com/motiful/product-shots/blob/063c508b0b7f4db5cda89f10bdf20df25026dfc5/skills/product-shots-ad-creative/references/quick-start-and-fidelity.md)
- [P5 社媒](https://github.com/motiful/product-shots/blob/063c508b0b7f4db5cda89f10bdf20df25026dfc5/skills/product-shots-social-post/SKILL.md)
- [P6 人物九连拍](https://github.com/motiful/product-shots/blob/063c508b0b7f4db5cda89f10bdf20df25026dfc5/skills/product-shots-multi-angle/SKILL.md)
