# 项目全资产成品档案交付说明

## 交付状态

OpenSpec 变更 `project-asset-product-archive` 已完成代码实现和自动化验证，等待最终统一人工验收。项目创建时会自动建立成品档案，项目内图片资产会实时汇总；提示词商城测试成功后自动保存到独立测试库，不会混入正式项目档案。

## 数据模型

- `products.project_id` 标识项目成品档案，通过活动记录条件唯一索引保证一个工作区中的一个项目只有一个产品条目。
- `product_asset_links` 保存产品与项目资产的关系，唯一约束阻止同一资产重复关联；文件、尺寸、哈希和对象键仍以项目资产域为事实来源。
- `product_versions` 继续保存生成或发布时的提示词、配置、模型、任务和尝试快照；手动上传资产允许没有生成版本。
- 测试成品通过 `test_run_id` 唯一关联测试任务，同一任务重放不会重复入库。
- `test_runs.request_snapshot` 保存测试输入和本次生成参数；本次参数覆盖提示词版本默认参数，但不会修改提示词版本。

数据库当前 Alembic head 为 `c4d5e6f7a8b9`。已执行迁移不可改写，后续结构调整必须新增 revision。

## 生命周期

1. `POST /api/projects` 返回前确保项目成品条目已经存在，幂等重放复用同一条目。
2. 项目源图、外部导入、白底图、主图、详情图、场景图和编辑结果写入项目资产后，同步建立成品档案关联。
3. 删除项目资产时解除关联；归档项目时同步归档项目产品，历史生成版本仍可审计。
4. 提示词测试成功时由后端执行器上传图片、写入统一“测试结果”库并回写 `outputProductId`；失败测试不创建测试成品。
5. 前端只展示自动保存状态，不再下载测试图片后重复上传到正式成品库。

## 主要入口

| 入口 | 用途 |
| --- | --- |
| `GET /api/product-libraries` | 查询正式成品库 |
| `GET /api/product-libraries/{library_id}/products` | 按项目查询产品条目和资产摘要 |
| `GET /api/products/{product_id}` | 查看一个项目的全部资产和生成版本 |
| `GET /api/products/{product_id}/versions` | 按类型或状态查看不可变生成版本 |
| `GET /api/products/{product_id}/versions/{version_id}/preview` | 站内受控预览生成版本 |
| `POST /api/test-runs` | 创建提示词测试任务并保存请求快照 |
| `GET /api/test-runs/{test_run_id}` | 轮询测试状态与自动入库结果 |
| `GET /api/test-product-libraries` | 查询与正式成品隔离的测试库 |
| `GET /api/test-product-libraries/{library_id}/products` | 查看测试结果及提示词名称、版本来源 |
| `python -m backend.cli project-archive-backfill --page-size 100` | 幂等补齐历史项目档案和资产关系 |

API、Worker、迁移和运行检查命令见 `backend/README.md`。

## 历史数据回填

当前开发数据库首次回填结果：

```json
{"scanned":2,"created":2,"reused":0,"linked":5,"unlinked":0,"failed":0}
```

第二次执行结果：

```json
{"scanned":2,"created":0,"reused":2,"linked":0,"unlinked":0,"failed":0}
```

结果证明回填可重复执行，不会新增重复产品或资产关系，也不会复制或删除现有对象存储文件。

## 自动化验证

2026-09-17 在当前工作树执行：

| 命令 | 结果 |
| --- | --- |
| `python -m pytest -q backend/tests` | 305 通过，6 个外部环境用例跳过 |
| `npm test` | 148 通过 |
| `npm run typecheck` | 通过 |
| `npm run build` | 通过 |
| `python -m pytest -q backend/tests/test_prompt_test_archive.py` | 3 通过 |

后端覆盖项目建档、资产关联与解除、归档、回填幂等、测试成功自动入库、失败隔离和任务重放。前端覆盖项目聚合成品库、测试库来源展示与筛选，以及提示词商城自动入库状态。

## 人工验收路径

1. 按 `backend/README.md` 启动 API、生成 Worker 和前端，确认 `/api/health` 成功，并在处理业务前确认 `/api/ready` 成功。
2. 创建一个空项目，立即打开“成品库”，确认已经出现该项目条目，详情显示空状态。
3. 向项目上传源图，刷新项目和成品库详情，确认同一资产在两处出现且没有复制上传。
4. 生成白底图、主图或套图，确认结果实时进入当前项目档案，并能查看对应生成版本来源。
5. 删除一张项目资产，确认它从成品档案消失，其他资产不受影响。
6. 在提示词商城运行一次成功的图片测试，确认页面显示“已自动保存到测试库”，点击入口能看到图片、提示词名称和版本号。
7. 按提示词名称或 `v版本号` 筛选测试结果，确认筛选正确；手工上传的旧测试结果显示“未记录提示词来源”。
8. 制造一次测试 Provider 失败，确认任务显示失败且测试库没有新增不完整成品。
9. 返回正式成品库，确认提示词测试结果没有自动出现在任何项目档案中。
10. 归档项目，确认对应项目产品从默认活动列表隐藏，历史版本仍可查询。

真实图片测试会调用已配置 Provider 并可能产生费用；自动化测试使用受控替身，不会触发计费调用。
