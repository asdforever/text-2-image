## Purpose

测试产物库用于存储提示词测试过程中生成的结果（图片、文本等），关联到具体的测试运行记录，用于版本对比和效果评估。不包含实际项目交付的成品。

## ADDED Requirements

### Requirement: 创建测试产物库

系统 SHALL 允许用户创建测试产物库，类型固定为 `test`。

#### Scenario: 创建测试产物库成功

- **WHEN** 用户提交 `{ name: "白底图测试产物", description: "白底图生成测试的结果" }`
- **THEN** 系统创建新的产物库记录，`library_type` 自动设为 `"test"`，返回包含 `id`、`name`、`description`、`library_type`、`created_at`、`updated_at` 的响应

#### Scenario: 缺少必填字段

- **WHEN** 用户提交缺少 `name` 的请求
- **THEN** 系统返回 400 错误，提示缺少必填字段

### Requirement: 列出测试产物库

系统 SHALL 允许用户获取所有测试产物库的列表。

#### Scenario: 获取测试产物库列表

- **WHEN** 用户请求产物库列表
- **THEN** 系统返回 `library_type="test"` 的所有产物库数组，每个产物库包含 `id`、`name`、`description`、`library_type`、`product_count`（该库下的产物数量）、`created_at`、`updated_at`

#### Scenario: 空列表

- **WHEN** 系统中没有任何测试产物库
- **THEN** 系统返回空数组

### Requirement: 获取产物库详情

系统 SHALL 允许用户获取指定产物库的详细信息。

#### Scenario: 获取存在的产物库

- **WHEN** 用户请求已存在的产物库 ID
- **THEN** 系统返回该产物库的完整信息

#### Scenario: 产物库不存在

- **WHEN** 用户请求不存在的产物库 ID
- **THEN** 系统返回 404 错误

### Requirement: 更新产物库

系统 SHALL 允许用户更新产物库的名称和描述。

#### Scenario: 更新产物库成功

- **WHEN** 用户提交 `{ name: "新名称", description: "新描述" }`
- **THEN** 系统更新产物库并返回更新后的完整信息

#### Scenario: 不允许更改类型

- **WHEN** 用户尝试更改产物库的 `library_type`
- **THEN** 系统忽略该字段或返回 400 错误，提示库类型不可更改

### Requirement: 删除产物库

系统 SHALL 允许用户删除产物库，级联删除该库下的所有产物。

#### Scenario: 删除产物库成功

- **WHEN** 用户请求删除已存在的产物库
- **THEN** 系统删除该产物库及其下的所有产物文件（从 MinIO）和记录，返回 204 状态码

#### Scenario: 删除不存在的产物库

- **WHEN** 用户请求删除不存在的产物库
- **THEN** 系统返回 404 错误

### Requirement: 上传测试产物

系统 SHALL 允许用户上传测试产物文件到指定的产物库，文件存储到 MinIO。

#### Scenario: 上传图片产物成功

- **WHEN** 用户上传图片文件到产物库，并关联 `test_run_id`
- **THEN** 系统将文件存储到 MinIO 路径 `suite-workbench/test-results/{test-run-id}/output.{ext}`，创建产物记录并返回包含 `id`、`name`、`library_id`、`product_type`、`minio_bucket`、`minio_key`、`file_type`、`file_size`、`test_run_id`、`created_at` 的响应

#### Scenario: 上传视频产物成功

- **WHEN** 用户上传视频文件到产物库
- **THEN** 系统将文件存储到 MinIO，`product_type` 设为 `"video"`，创建产物记录

#### Scenario: 上传时关联测试运行

- **WHEN** 用户上传产物并提供 `test_run_id`
- **THEN** 系统验证测试运行记录存在，关联产物到该测试运行

#### Scenario: 测试运行不存在

- **WHEN** 用户上传产物时提供不存在的 `test_run_id`
- **THEN** 系统返回 400 错误，提示测试运行记录不存在

### Requirement: 列出产物

系统 SHALL 允许用户获取指定产物库下的所有产物列表。

#### Scenario: 获取产物列表

- **WHEN** 用户请求产物库的产物列表
- **THEN** 系统返回该库下所有产物的数组，每个产物包含 `id`、`name`、`product_type`、`file_type`、`file_size`、`test_run_id`、`created_at`，并提供预签名 URL 用于前端预览

#### Scenario: 空产物库

- **WHEN** 产物库中没有任何产物
- **THEN** 系统返回空数组

#### Scenario: 按测试运行筛选

- **WHEN** 用户请求产物列表并提供 `test_run_id` 参数
- **THEN** 系统仅返回关联到该测试运行的产物

### Requirement: 获取产物详情

系统 SHALL 允许用户获取指定产物的详细信息。

#### Scenario: 获取产物详情

- **WHEN** 用户请求产物的详情
- **THEN** 系统返回完整的产物信息，包含预签名下载 URL

#### Scenario: 产物不存在

- **WHEN** 用户请求不存在的产物 ID
- **THEN** 系统返回 404 错误

### Requirement: 删除产物

系统 SHALL 允许用户删除指定的产物。

#### Scenario: 删除产物成功

- **WHEN** 用户删除产物
- **THEN** 系统从 MinIO 删除文件，从数据库删除记录，返回 204 状态码

#### Scenario: 删除不存在的产物

- **WHEN** 用户删除不存在的产物
- **THEN** 系统返回 404 错误

#### Scenario: 删除被引用的产物

- **WHEN** 用户删除正在被测试运行记录引用的产物（`test_runs.output_product_id`）
- **THEN** 系统将测试运行记录的 `output_product_id` 设为 NULL（ON DELETE SET NULL），删除产物成功

### Requirement: MinIO 桶结构

系统 SHALL 使用固定的 MinIO 桶结构存储测试产物。

#### Scenario: 测试产物存储路径

- **WHEN** 上传测试产物
- **THEN** 文件存储到 `suite-workbench/test-results/{test-run-id}/output.{ext}`，其中 `{test-run-id}` 是测试运行记录 UUID，`{ext}` 是文件扩展名

#### Scenario: 预签名 URL 有效期

- **WHEN** 生成产物的预签名 URL
- **THEN** URL 有效期为 1 小时

### Requirement: 文本产物存储

系统 SHALL 允许测试产物为纯文本结果，直接存储到测试运行记录中。

#### Scenario: 文本产物无需文件

- **WHEN** 测试生成的结果是文本（如图生文、文生文的输出）
- **THEN** 系统将文本直接存储到 `test_runs.output_text` 字段，不创建产物文件，`output_product_id` 为 NULL
