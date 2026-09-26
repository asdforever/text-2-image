## Context

See proposal.md - Why for motivation.

当前系统已有：
- 提示词模板和版本的数据库表（`prompt_templates`、`prompt_versions`）
- MinIO 集成用于文件存储（已配置在环境变量）
- 提示词商城页面（`PromptMarketplacePage.tsx`）显示模板列表和版本详情弹窗
- FastAPI 后端提供提示词 CRUD API

现有限制：
- `kind`/`stage` 双字段分类语义不清晰，前端硬编码枚举值
- 版本对比功能在弹窗中以列表形式展示，无法并排查看效果
- 缺少测试素材管理，无法系统化地验证提示词效果
- 缺少测试结果存储，历史测试数据丢失

## Goals / Non-Goals

**Goals:**
- 重塑提示词分类为清晰的四分类（图生图/文生图/文生文/图生文）
- 提供素材库和测试产物库的完整 CRUD 和文件上传能力
- 构建独立的版本工作台页面，支持最多 6 个版本并排对比
- 根据提示词 `kind` 动态适配输入素材选择和输出结果展示
- 设计测试运行记录数据模型，为未来推理服务集成留接口

**Non-Goals:**
- 实际调用推理服务生成结果（按钮 UI 完整但禁用）
- 项目成品库（`library_type='project'`）
- 测试结果的自动通过/失败判断
- 批量测试自动化执行

## Decisions

### Decision 1: 删除 stage 字段，重塑 kind 为四分类

**选择**: 将 `kind` 改为基于输入输出类型的四个枚举值，删除 `stage` 字段。

**理由**:
- 原 `kind`（planner/direct_generation/repair）+ `stage`（plan/base_refine/task_image/reverse_prompt）组合语义重叠且不直观
- 新四分类（image_to_image/text_to_image/text_to_text/image_to_text）直接表达 I/O 类型，前端可据此适配 UI
- 单字段分类简化数据模型和 API

**替代方案**:
- 保留 `stage`，只修改 `kind` → 拒绝，两个字段功能重叠
- 新增 `input_type`/`output_type` 两个字段 → 拒绝，冗余且需额外校验一致性

**影响**:
- **BREAKING**: 需数据库迁移映射现有记录
- 前端需更新所有硬编码的 `kind`/`stage` 引用

### Decision 2: kind_name 存储到数据库（方案 A）

**选择**: `kind_name` 字段存储到数据库，前端提交时同时传 `kind` 和 `kind_name`。

**理由**:
- 用户反馈需要前端显示中文，存 DB 可避免前端多处维护映射表
- 允许未来支持多语言或自定义类型名称

**替代方案**:
- 前端根据 `kind` 动态计算 `kind_name`（方案 B）→ 拒绝，需在多处组件维护映射逻辑

**Trade-off**: DB 存冗余字段，但换来前端简化和扩展性

### Decision 3: 素材库支持图片和文本两种类型

**选择**: `assets` 表同时支持图片素材（存 MinIO）和文本素材（存 DB `content` 字段）。

**理由**:
- 不同 `kind` 的提示词需要不同输入类型（`image_to_*` 需要图片，`text_to_*` 需要文本）
- 统一表结构简化 CRUD 逻辑
- 文本素材无需占用 MinIO 空间

**数据模型**:
```sql
asset_type: 'image' | 'text'
-- 图片素材字段: minio_bucket, minio_key, file_type, file_size, width, height
-- 文本素材字段: content
```

**校验**:
- 图片素材库（`asset_type='image'`）拒绝文本素材创建
- 文本素材库（`asset_type='text'`）拒绝图片上传

### Decision 4: 测试产物文本直接存 test_runs 表

**选择**: 图生文、文生文的输出为纯文本时，直接存 `test_runs.output_text`，不创建 `products` 记录。

**理由**:
- 文本无需文件管理，存 DB 更高效
- 避免为小文本创建 MinIO 文件的开销

**数据模型**:
```sql
test_runs:
  output_text: text | null        -- 文本输出直接存这里
  output_product_id: uuid | null  -- 图片/视频等文件输出存产物库
```

### Decision 5: MinIO 桶路径结构

**选择**:
```
suite-workbench/
  test-assets/
    images/{library-id}/{asset-id}.{ext}
  test-results/
    {test-run-id}/output.{ext}
```

**理由**:
- `test-assets/images/{library-id}/` 按素材库隔离，便于批量删除
- `test-results/{test-run-id}/` 按测试运行隔离，支持同一测试多次运行
- 不使用深层嵌套，避免路径过长

**替代方案**:
- 平铺 `test-assets/{asset-id}.{ext}` → 拒绝，删除素材库时需遍历所有文件
- 按日期分区 `test-results/2026/09/{test-run-id}` → 拒绝，增加复杂度且无实际收益

### Decision 6: 版本工作台为独立路由，非弹窗

**选择**: `/prompts/:id/versions` 独立页面，非商城页面的弹窗。

**理由**:
- 版本对比需要大量屏幕空间（最多 6 列网格 + 素材选择 + 详情）
- 弹窗无法提供足够的工作空间
- 独立路由支持深链接和浏览器前进后退

**布局**: 左侧版本选择器（固定宽度）+ 右侧测试区（flex 占满）

### Decision 7: 对比视图布局动态适配

**选择**: 根据选择版本数量自动调整网格布局。

**布局规则**:
- 2 个版本: 1x2 横向排列
- 3-4 个版本: 2x2 网格
- 5-6 个版本: 2x3 网格

**CSS 实现**: `display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr))`

### Decision 8: 生成按钮 UI 完整但禁用

**选择**: 所有"生成"按钮显示但处于禁用状态，hover 提示"功能开发中"。

**理由**:
- UI 先行，为未来推理服务集成预留界面
- 用户可理解完整工作流，明确当前限制

**未来扩展点**:
- 启用生成按钮调用推理服务 API
- 实现 `POST /api/test-runs` 实际执行逻辑
- 轮询或 WebSocket 获取异步生成结果

### Decision 9: 数据库迁移策略

**BREAKING 变更**: 删除 `stage` 字段，修改 `kind` 枚举。

**迁移步骤**:
1. 创建新表（`asset_libraries`, `assets`, `product_libraries`, `products`, `test_runs`）
2. 为 `prompt_templates` 添加 `kind_name` 列（nullable 先）
3. 数据迁移脚本：
   ```sql
   -- 映射现有 kind/stage 到新 kind
   UPDATE prompt_templates SET
     kind = CASE 
       WHEN stage = 'reverse_prompt' THEN 'image_to_text'
       WHEN stage = 'task_image' THEN 'image_to_image'
       -- 其他映射规则根据实际数据确定
       ELSE 'text_to_text'
     END,
     kind_name = CASE
       WHEN stage = 'reverse_prompt' THEN '图生文'
       WHEN stage = 'task_image' THEN '图生图'
       ELSE '文生文'
     END;
   ```
4. 删除 `stage` 列
5. `kind_name` 改为 NOT NULL

**回滚**: 保留迁移前的数据库备份

## Risks / Trade-offs

### Risk: 数据迁移可能丢失语义

现有 `kind`/`stage` 组合的映射到新 `kind` 的规则需人工确认。

**Mitigation**: 
- 迁移前导出现有数据并人工审查映射规则
- 迁移脚本包含日志记录每条记录的映射结果
- 保留完整数据库备份

### Risk: 素材文件上传失败处理

上传到 MinIO 失败但数据库记录已创建，导致孤儿记录。

**Mitigation**:
- 先上传文件到 MinIO，成功后再创建数据库记录
- 事务内先插入记录（获取 ID），上传失败则回滚
- 定期清理孤儿记录的后台任务（可选）

### Risk: MinIO 预签名 URL 过期

前端缓存的预签名 URL 在 1 小时后失效。

**Mitigation**:
- 前端在 URL 接近过期时自动重新请求
- 或每次渲染时动态获取新 URL

### Trade-off: kind_name 冗余存储

`kind_name` 可从 `kind` 计算得出，存 DB 增加冗余。

**接受理由**: 前端简化 > 存储成本，未来支持多语言或自定义名称

### Trade-off: 测试功能 UI 完整但不可用

用户可能困惑为何按钮禁用。

**Mitigation**: 
- 明确的 disabled 状态样式
- Hover 提示"功能开发中"
- 文档说明当前为 UI 预览阶段

## Migration Plan

### 数据库迁移

1. **创建迁移脚本** `alembic/versions/XXXX_prompt_workspace_and_asset_library.py`
2. **执行顺序**:
   - 创建新表（asset_libraries, assets, product_libraries, products, test_runs）
   - 添加 `prompt_templates.kind_name` (nullable)
   - 数据迁移脚本更新 `kind` 和 `kind_name`
   - 删除 `prompt_templates.stage` 和 `prompt_versions.stage`
   - 修改 `kind_name` 为 NOT NULL
3. **验证**: 迁移后查询确认所有记录有有效的 `kind` 和 `kind_name`

### MinIO 桶创建

后端启动时自动检查并创建必要的桶路径：
```python
minio_client.make_bucket("suite-workbench")  # 如已存在则跳过
```

### 前端部署

1. 部署新路由 `/prompts/:id/versions`, `/asset-libraries`, `/product-libraries`
2. 更新 `/prompts` 商城页面（新建按钮位置、kind 筛选、卡片显示）
3. 移除所有 `stage` 字段引用

### 回滚策略

- 数据库: 恢复迁移前备份
- MinIO: 删除新创建的桶路径（如有数据需保留则跳过）
- 前端: 回滚到上一版本

### 灰度发布（可选）

- 新路由先对内部用户开放
- 商城页面的 `kind` 筛选功能可通过 feature flag 控制

## Open Questions

无。所有设计决策已确定，可直接进入任务分解阶段。
