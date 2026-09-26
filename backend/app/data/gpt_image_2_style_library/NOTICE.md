# GPT Image 2 Style Library 来源

本目录固定复用 freestylefly/awesome-gpt-image-2 的原始文件，提交：
`0dc09c46c8a30b1fdd89c18cc78a894dac2104e3`。

- 仓库：https://github.com/freestylefly/awesome-gpt-image-2
- `style-library.json` 来自 `data/style-library.json`，保留全部 22 个模板。
- `templates.md` 来自 `docs/templates.md`，保留原文及上游署名链接。
- `SKILL.md` 来自 `agents/skills/gpt-image-2-style-library/SKILL.md`，作为复用依据保留；应用不执行安装、维护命令。
- `LICENSE` 来自根目录，Copyright (c) 2026 freestylefly，MIT。

应用适配层在 `backend/app/application/image_style_library.py`。索引读取中文指导、适用场景和标签；已选模板再附带对应分类原文。原文可能含同类的多个变体，适配规则要求仅使用与任务相符的部分。

案例图未随本目录导入，案例编号仅供溯源。上游引用的第三方案例内容不因仓库 MIT 许可而自动获得所有权；当前运行时不拉取这些图。

更新时从同一个审核后的提交替换这四份原始文件，更新适配层 revision，并运行样式库与规划测试。应用运行期间不访问 GitHub，也不读取开发者的个人 Skill 目录。
