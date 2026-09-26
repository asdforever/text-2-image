# OpenSpec 变更路线图

OpenSpec 会记录单个 change 内部的 artifact 依赖，但不会自动推断多个 change 之间的执行顺序。本文件记录项目级别的执行顺序、依赖关系和维护规则。

后端架构阶段总表见：[docs/backend-architecture-roadmap.md](../docs/backend-architecture-roadmap.md)。后端实施、阶段状态和真实生图里程碑以该文档为准。

## 执行顺序

| 顺序 | Change | 状态 | 依赖与原因 |
| --- | --- | --- | --- |
| 1 | `frontend-ps-ui-refactor` | 已完成 | 建立项目管理、资产库和工作台布局的基础能力。 |
| 2 | `project-assets-and-theme` | 实现完成，待归档 | 素材后置提交、亮暗主题和右侧面板布局已实现并验证；规划 artifact 已全部完成。 |
| 3 | `global-navigation-v2` | 实现完成，待归档 | 已接入统一左侧导航、项目管理、提示词商城、任务中心，并移除创建页素材步骤。 |
| 4 | `backend-runtime-baseline` | 本地实现完成，待环境验收 | 后端分层、身份上下文、幂等与迁移边界已建立；专用 PostgreSQL 演练待执行。 |
| 5 | `project-asset-domain` | 实现完成，待环境验收 | 已新增项目与项目资产域、白底图版本、对象补偿与清理；专用 PostgreSQL 演练待执行。 |
| 6 | `prompt-authoring` | 已规划，未开始 | 建立提示词的生产与沉淀闭环：描述创作、爆品图反推、改写生成三种输入统一产出可复用模板。依赖已发布的提示词商城模板与版本机制，不新增业务表，也不调用图片生成 Provider。 |
| 6 | `project-asset-product-archive` | 实现完成，待人工验收 | 项目创建即建档、全部项目资产实时汇总、历史幂等回填；提示词测试成功自动进入独立测试库。 |

## 维护规则

- 项目内的 OpenSpec、架构、设计、验收和实现说明文档默认使用中文；代码标识、命令、路径、API 路径和 OpenSpec 必需字段可保留原文。
- 新建 change 后、开始实现前，先登记到本表。
- 有前置依赖的 change 必须排在依赖它的 change 之前。
- 有代码重叠的 change 不要并行实现；前置 change 完成、验证并归档后，再开始后续 change。
- 每个 change 的 `proposal.md` 中的依赖说明必须与本路线图保持一致。
- 在规划完成、实现完成、验证完成和归档后更新状态。

## 状态查看命令

```bash
openspec list
openspec status --change <change-name>
```

## 最近验证

- `npm test`：10 项通过，覆盖素材创建/上传、主题和布局契约。
- `npm run check:encoding`：16 个 Markdown 文件通过 UTF-8 检查。
- `npm run typecheck`：通过。
- `npm run build`：通过。
- Playwright Chromium：已使用本机 Chromium 可执行文件完成欢迎页主题切换、空项目创建、1440/1120/1920 宽度布局和横向溢出检查。

## 第二版最近验证

- `npm test`：13 项通过。
- `npm run check:encoding`：24 个 Markdown 文件通过 UTF-8 检查。
- `npm run typecheck`：通过。
- `npm run build`：通过。
- `openspec validate global-navigation-v2 --strict`：通过。
- Playwright：验证四个分支路由、激活态、1120px 窄窗口横向溢出和创建弹窗无文件输入。

## 项目成品档案最近验证

- `python -m pytest -q backend/tests`：305 通过，6 个外部环境用例跳过。
- `npm test`：148 通过。
- `npm run typecheck`：通过。
- `npm run build`：通过。
- 开发数据库回填两次执行分别创建 2 个项目档案并关联 5 个资产、随后零新增。

最后检查时间：2026-09-17
