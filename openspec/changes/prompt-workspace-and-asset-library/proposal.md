## Why

提示词商城的前端存在多个用户体验问题：新建按钮位置不合理（放在搜索区域）、版本迭代功能过于粗糙（无法直观对比版本效果）、缺少测试素材管理和版本验证机制。同时，现有的 `kind`/`stage` 分类不够清晰，无法准确表达提示词的输入输出类型（图生图、文生图、文生文、图生文）。本次变更通过重塑提示词分类体系、引入素材库和成品库、构建独立的版本工作台，为提示词的迭代验证提供完整的工作流支持。

## What Changes

- **BREAKING**: 重塑提示词分类体系
  - 删除 `stage` 字段
  - `kind` 改为四分类：`image_to_image`（图生图）、`text_to_image`（文生图）、`text_to_text`（文生文）、`image_to_text`（图生文）
  - 新增 `kind_name` 字段存储中文名称，前端通过中文下拉选择
  
- 新增素材库（Asset Library）
  - 支持图片素材（存 MinIO）和文本素材（存 DB）
  - 分类管理测试输入素材（白底图测试集、爆品图测试集等）
  
- 新增测试产物库（Product Library for Test Results）
  - 存储提示词测试生成的结果
  - 关联测试运行记录（版本 + 素材 + 产出）
  - **不包含项目成品**，仅限测试产物
  
- 新增版本工作台页面（独立路由）
  - 多版本并排对比（最多6个）
  - 根据 `kind` 适配输入素材选择和输出展示
  - 测试运行记录和结果缓存
  - 生成按钮 UI 完整但功能暂不实现（无推理服务调用）
  
- 提示词商城页面优化
  - 新建按钮移至左上角独立区域
  - 新增 `kind` 筛选（全部/图生图/文生图/文生文/图生文）
  - 卡片显示 `kind` 图标和中文标签
  - 创建表单改为中文下拉选择

## Capabilities

### New Capabilities

- `asset-library`: 素材库管理，包括图片和文本测试素材的 CRUD、上传到 MinIO、分类管理
- `test-product-library`: 测试产物库管理，存储提示词测试生成的结果，关联测试运行记录
- `prompt-version-workspace`: 提示词版本工作台，支持多版本对比、素材选择、测试运行记录
- `prompt-kind-restructure`: 提示词分类体系重塑，定义新的四分类 `kind` 和 `kind_name` 字段，删除 `stage`

### Modified Capabilities

- `prompt-marketplace`: 商城页面布局优化（新建按钮位置、kind 筛选、中文显示），创建表单改为中文 kind 选择

## Impact

**数据库**
- `prompt_library.prompt_templates` 表：删除 `stage`，修改 `kind` 枚举，新增 `kind_name`（**BREAKING**）
- `prompt_library.prompt_versions` 表：删除 `stage`（**BREAKING**）
- 新增 `prompt_library.asset_libraries` 表
- 新增 `prompt_library.assets` 表
- 新增 `prompt_library.product_libraries` 表（仅 `library_type='test'`）
- 新增 `prompt_library.products` 表
- 新增 `prompt_library.test_runs` 表

**MinIO**
- 新建 `suite-workbench/test-assets/` 桶路径（存测试素材）
- 新建 `suite-workbench/test-results/` 桶路径（存测试产物）

**API**
- 提示词 API 更新：`kind`/`kind_name` 字段变更，去掉 `stage`（**BREAKING**）
- 新增素材库 CRUD 端点
- 新增素材上传端点（图片 multipart，文本 JSON）
- 新增测试产物库 CRUD 端点
- 新增测试运行记录端点

**前端路由**
- `/prompts/:id/versions` - 版本工作台（新增）
- `/asset-libraries` - 素材库列表（新增）
- `/asset-libraries/:id` - 素材库详情（新增）
- `/product-libraries` - 测试产物库（新增）
- `/product-libraries/:id` - 产物库详情（新增）
- `/prompts` - 商城页面（布局和交互更新）

**依赖**
- MinIO SDK（已有，需新建桶路径）
- 前端文件上传组件
