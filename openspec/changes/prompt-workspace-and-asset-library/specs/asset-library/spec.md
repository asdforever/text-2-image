## Purpose

素材库管理系统用于组织和管理提示词测试所需的输入素材，支持图片素材（存储到 MinIO）和文本素材（存储到数据库），并提供分类管理能力。

## ADDED Requirements

### Requirement: 创建素材库

系统 SHALL 允许用户创建素材库，指定名称、描述和素材类型（图片或文本）。

#### Scenario: 创建图片素材库成功

- **WHEN** 用户提交 `{ name: "白底图测试集", description: "用于测试商品白底图生成", asset_type: "image" }`
- **THEN** 系统创建新的素材库记录并返回包含 `id`、`name`、`description`、`asset_type`、`created_at`、`updated_at` 的响应

#### Scenario: 创建文本素材库成功

- **WHEN** 用户提交 `{ name: "用户需求样例", description: "用户需求描述集合", asset_type: "text" }`
- **THEN** 系统创建新的素材库记录并返回完整信息

#### Scenario: 缺少必填字段

- **WHEN** 用户提交缺少 `name` 或 `asset_type` 的请求
- **THEN** 系统返回 400 错误，提示缺少必填字段

#### Scenario: 无效的素材类型

- **WHEN** 用户提交 `asset_type` 不是 `"image"` 或 `"text"` 的请求
- **THEN** 系统返回 400 错误，提示素材类型无效

### Requirement: 列出素材库

系统 SHALL 允许用户获取所有素材库的列表，包含素材数量统计。

#### Scenario: 获取素材库列表

- **WHEN** 用户请求素材库列表
- **THEN** 系统返回包含所有素材库的数组，每个素材库包含 `id`、`name`、`description`、`asset_type`、`asset_count`（该库下的素材数量）、`created_at`、`updated_at`

#### Scenario: 空列表

- **WHEN** 系统中没有任何素材库
- **THEN** 系统返回空数组

### Requirement: 获取素材库详情

系统 SHALL 允许用户获取指定素材库的详细信息。

#### Scenario: 获取存在的素材库

- **WHEN** 用户请求已存在的素材库 ID
- **THEN** 系统返回该素材库的完整信息

#### Scenario: 素材库不存在

- **WHEN** 用户请求不存在的素材库 ID
- **THEN** 系统返回 404 错误

### Requirement: 更新素材库

系统 SHALL 允许用户更新素材库的名称和描述。

#### Scenario: 更新素材库成功

- **WHEN** 用户提交 `{ name: "新名称", description: "新描述" }`
- **THEN** 系统更新素材库并返回更新后的完整信息

#### Scenario: 更新不存在的素材库

- **WHEN** 用户尝试更新不存在的素材库
- **THEN** 系统返回 404 错误

#### Scenario: 不允许更改素材类型

- **WHEN** 用户尝试更改素材库的 `asset_type`
- **THEN** 系统忽略该字段或返回 400 错误，提示素材类型不可更改

### Requirement: 删除素材库

系统 SHALL 允许用户删除素材库，级联删除该库下的所有素材。

#### Scenario: 删除素材库成功

- **WHEN** 用户请求删除已存在的素材库
- **THEN** 系统删除该素材库及其下的所有素材，返回 204 状态码

#### Scenario: 删除不存在的素材库

- **WHEN** 用户请求删除不存在的素材库
- **THEN** 系统返回 404 错误

### Requirement: 上传图片素材

系统 SHALL 允许用户上传图片文件到指定的图片素材库，文件存储到 MinIO。

#### Scenario: 上传图片成功

- **WHEN** 用户上传图片文件到图片素材库（`asset_type="image"`）
- **THEN** 系统将文件存储到 MinIO 路径 `suite-workbench/test-assets/images/{library-id}/{asset-id}.{ext}`，提取图片宽度、高度、文件大小等元数据，创建素材记录并返回包含 `id`、`name`、`library_id`、`asset_type`、`minio_bucket`、`minio_key`、`file_type`、`file_size`、`width`、`height`、`created_at` 的响应

#### Scenario: 上传到非图片素材库

- **WHEN** 用户尝试上传图片文件到文本素材库（`asset_type="text"`）
- **THEN** 系统返回 400 错误，提示该素材库不接受图片

#### Scenario: 上传非图片文件

- **WHEN** 用户上传非图片文件（如 PDF、视频）到图片素材库
- **THEN** 系统返回 400 错误，提示仅支持图片文件

#### Scenario: 文件过大

- **WHEN** 用户上传超过大小限制的图片文件
- **THEN** 系统返回 413 错误，提示文件过大

### Requirement: 创建文本素材

系统 SHALL 允许用户创建文本素材到指定的文本素材库，文本内容直接存储到数据库。

#### Scenario: 创建文本素材成功

- **WHEN** 用户提交 `{ name: "测试需求1", content: "我需要一个爆品图" }` 到文本素材库（`asset_type="text"`）
- **THEN** 系统创建素材记录并返回包含 `id`、`name`、`library_id`、`asset_type`、`content`、`created_at` 的响应

#### Scenario: 创建到非文本素材库

- **WHEN** 用户尝试创建文本素材到图片素材库（`asset_type="image"`）
- **THEN** 系统返回 400 错误，提示该素材库不接受文本

#### Scenario: 缺少内容

- **WHEN** 用户提交缺少 `content` 字段的请求
- **THEN** 系统返回 400 错误，提示缺少必填字段

### Requirement: 列出素材

系统 SHALL 允许用户获取指定素材库下的所有素材列表。

#### Scenario: 获取图片素材列表

- **WHEN** 用户请求图片素材库的素材列表
- **THEN** 系统返回该库下所有素材的数组，每个素材包含 `id`、`name`、`minio_bucket`、`minio_key`、`file_type`、`file_size`、`width`、`height`、`created_at`，并提供预签名 URL 用于前端预览

#### Scenario: 获取文本素材列表

- **WHEN** 用户请求文本素材库的素材列表
- **THEN** 系统返回该库下所有素材的数组，每个素材包含 `id`、`name`、`content`、`created_at`

#### Scenario: 空素材库

- **WHEN** 素材库中没有任何素材
- **THEN** 系统返回空数组

### Requirement: 获取素材详情

系统 SHALL 允许用户获取指定素材的详细信息。

#### Scenario: 获取图片素材详情

- **WHEN** 用户请求图片素材的详情
- **THEN** 系统返回完整的素材信息，包含预签名下载 URL

#### Scenario: 获取文本素材详情

- **WHEN** 用户请求文本素材的详情
- **THEN** 系统返回完整的素材信息，包含文本内容

#### Scenario: 素材不存在

- **WHEN** 用户请求不存在的素材 ID
- **THEN** 系统返回 404 错误

### Requirement: 删除素材

系统 SHALL 允许用户删除指定的素材。

#### Scenario: 删除图片素材

- **WHEN** 用户删除图片素材
- **THEN** 系统从 MinIO 删除文件，从数据库删除记录，返回 204 状态码

#### Scenario: 删除文本素材

- **WHEN** 用户删除文本素材
- **THEN** 系统从数据库删除记录，返回 204 状态码

#### Scenario: 删除不存在的素材

- **WHEN** 用户删除不存在的素材
- **THEN** 系统返回 404 错误

#### Scenario: 删除被引用的素材

- **WHEN** 用户删除正在被测试运行记录引用的素材
- **THEN** 系统将测试运行记录的 `input_asset_id` 设为 NULL（ON DELETE SET NULL），删除素材成功

### Requirement: MinIO 桶结构

系统 SHALL 使用固定的 MinIO 桶结构存储图片素材。

#### Scenario: 图片素材存储路径

- **WHEN** 上传图片素材
- **THEN** 文件存储到 `suite-workbench/test-assets/images/{library-id}/{asset-id}.{ext}`，其中 `{library-id}` 是素材库 UUID，`{asset-id}` 是素材 UUID，`{ext}` 是文件扩展名

#### Scenario: 预签名 URL 有效期

- **WHEN** 生成图片素材的预签名 URL
- **THEN** URL 有效期为 1 小时
