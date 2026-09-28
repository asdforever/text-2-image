# 设计指导规划：实现与链路验证

日期：2026-09-28。状态：代码与链路已验证，实际成图对照未执行。

## 实现范围

- 规划大师实际接收 `designKnowledge`、`commerceDesign`、所选风格及模板库；测试捕获模型请求并与快照逐项比对。
- 应用内置主图/套图规划 Skill 更新为 `commerce-design-v1` 契约。先确定信息问题和表达，再选择执行模块；支持 `productPresence=none`。
- 新增 `hero-freeform` / `suite-freeform` 运行时目录，不改已发布配置。前端将运行时目录与配置管理草稿隔离。
- 单图编译读取所选设计指南、系列方向、primary/gallery/detail 位置；自动构图为建议，用户编辑的“构图要求”为显式要求，不作为上图文字或商品事实。
- 新任务卡显示任务标题、信息目标、表达方式、商品出场、构图建议。风格变化使规划失效；同模块任务按 taskId 独立编辑和恢复。
- 只支持新规划契约，不迁移或清理旧任务。没有新增模型调用阶段、运行时依赖或自动图片生成。

知识包：`commerce-design-v1`，SHA-256：`f976e64743b9cd7839f73905a7ba31f3ca1c5d630e4bbb7a428266481348a386`。

完整指南：commerce-core、visual-hierarchy、data-explanation、usage-context。大师收到完整精简包，单图收到 core 与选定的 1–2 项辅助指南。来源、固定修订和许可在 `backend/app/data/commerce_design_v1/`。这是适配后的设计规则注入，不是运行外部 Skill 工具工作流。

## 验证结果

| 验证 | 命令 | 结果 |
|---|---|---|
| 后端新链路 | `python -m pytest backend/tests/test_commerce_planning_flow.py -q` | 6 通过 |
| 后端广泛回归 | `python -m pytest backend/tests -q --disable-warnings --deselect=backend/tests/test_generation_rolling_worker.py::test_refill_recovers_undispatched_lease_without_waiting_for_all_calls --deselect=backend/tests/test_prompt_test_archive.py::test_failed_prompt_test_does_not_create_test_product` | 601 通过、12 跳过、2 排除 |
| 前端单元测试 | `npm test` | 216 通过、6 失败（均在基线复现） |
| 前端构建 | `npm run build` | 成功，仍有大于 500 KB chunk 提示 |
| 前端规划 E2E | `npx playwright test tests/e2e/module-planning.spec.ts --reporter=line --trace=on --output=../tmp/commerce-e2e-results` | 13 通过 |
| 本地服务 | GET `/api/health`、`/api/generation-config/resolve`、前端首页 | 后端 ready，前端 HTTP 200，运行时版本正确，两种 freeform 各 1 项 |

新链路测试覆盖真实大师服务到套图/主图编译服务：none、重复 freeform、独立 taskId、用户独立编辑、系列方向、primary/gallery/detail、每任务 1 张、模型调用数不增加。编译时图片 provider 调用为 0，没有创建图片 slots。

E2E 使用 stub API，覆盖主图/套图资料规划、手动同类任务、刷新保留编辑、风格变化失效、迟到响应保护、进行中恢复与失败重试幂等键。它证明操作链路，不代表真实模型输出质量。

独立审查发现并修复了两项问题：初始 planning 记录缺少契约版本；发布/重新加载配置后残留旧运行时目录。两者均有回归断言。

## 已有失败的基线验证

后端基线 `a4b609e` 上分别复现了两项失败，相关生产逻辑不是本次修改范围：

1. `test_refill_recovers_undispatched_lease_without_waiting_for_all_calls`：2 秒窗口内的并发时序断言超时。
2. `test_failed_prompt_test_does_not_create_test_product`：期望原始 `provider unavailable`，实际既有逻辑返回脱敏中文错误。

前端基线 `a318625c27863f3de995ce0eb0cd2769840c1dd4` 全量结果 211 通过、7 失败。当前剩余以下 6 项逐项匹配基线：

- generation configuration page groups concrete market CRUD cards by scope
- normalization defaults selected modules to one image and clamps counts to one through four
- hero compile and suite image submissions record generation snapshots
- project creation supports an optional product image
- 批次运行状态展示总进度、模块进度、槽位结果、失败重试和取消
- project upload controls are wired into the UI

另一个基线失败是套图规划旧文案断言，已随新文案更新并通过。本次没有为得到全绿而修改其他无关断言。

完整本地日志在父目录 `tmp/commerce-backend-final.log`、`commerce-baseline-tests.log`、`commerce-baseline-archive-test.log`、`commerce-frontend-final.log`、`commerce-frontend-baseline-npm-test.log`、`commerce-frontend-build.log` 和 `commerce-e2e-final.log`；日志和浏览器 trace 不纳入提交。

## 尚未验证

没有调用付费图片生成，没有执行鼠标或非数码商品的旧/新图片对照，因此不能确认文字准确率、商品一致性、审美提升、实际生成耗时或费用。后续按原方案固定输入、模型、画幅和风格后进行人工成图检查；本次交付结论仅为链路接通。

本地前后端已启用新代码。测试 API 检查不创建真实项目规划或生成任务；用户需重新规划以使用新链路。两个仓库均未配置远端，GitHub 推送未完成。
