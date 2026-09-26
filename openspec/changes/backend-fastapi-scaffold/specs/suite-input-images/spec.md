## Purpose

提供第一条可落地的业务垂直切片，让客户端能够创建和查询 suite，并在 suite 创建后独立上传、校验、去重和预览商品原图。

## ADDED Requirements

### Requirement: Client can create and retrieve suites

服务 MUST 提供 suite 的创建、列表和详情查询。创建请求必须包含非空名称；新建 suite 默认处于可继续上传图片的草稿状态，并返回稳定的 suite 标识和时间字段。

#### Scenario: Create a suite

- **WHEN** 客户端向 `/api/suites` 提交非空名称
- **THEN** 服务返回 201 和包含 `id`、`name`、`status`、`createdAt`、`updatedAt` 的 suite 数据

#### Scenario: Reject blank suite name

- **WHEN** 客户端提交空白或缺失的 suite 名称
- **THEN** 服务返回 400 错误信封，错误码明确指出名称无效

#### Scenario: Retrieve suite aggregate

- **WHEN** 客户端请求已存在的 `/api/suites/{suiteId}`
- **THEN** 服务返回 suite 基础信息及该 suite 当前的 input image 列表

### Requirement: Client can upload validated input images

服务 MUST 接受 `multipart/form-data` 图片上传，并将图片归属于指定 suite。单个 suite 最多允许 6 张图片；支持 JPG、PNG 和 WebP；单文件大小不得超过 12MB；服务 MUST 校验真实图片格式、尺寸元数据和可选 ordinal，并拒绝越界或重复图片。

#### Scenario: Upload a valid image

- **WHEN** 客户端向 `/api/suites/{suiteId}/input-images` 上传符合限制的图片
- **THEN** 服务返回 201，持久化图片元数据和对象存储引用，并返回图片 `id`、`ordinal`、尺寸、MIME 类型、哈希和创建时间

#### Scenario: Reject unsupported or oversized image

- **WHEN** 客户端上传不支持的 MIME 类型、超过 12MB 或无法解析为图片的文件
- **THEN** 服务返回 400 错误信封，不创建数据库记录，也不留下孤立对象

#### Scenario: Reject duplicate image or ordinal

- **WHEN** 客户端上传与同一 suite 中已有图片哈希相同的文件，或使用已占用的 ordinal
- **THEN** 服务返回冲突错误信封，已有图片和对象保持不变

### Requirement: Client can preview stored input images

服务 MUST 提供 input image 的原图和缩略图预览访问。预览响应 MUST 使用持久化对象的真实 Content-Type；suite 或图片不存在时 MUST 返回明确的 404 错误。

#### Scenario: Preview original or thumbnail

- **WHEN** 客户端请求已存在图片的原图或缩略图预览
- **THEN** 服务返回对应二进制内容、正确的 `Content-Type` 和可缓存控制头

#### Scenario: Preview missing resource

- **WHEN** 客户端请求不存在的 suite、图片或预览类型
- **THEN** 服务返回 404 错误信封，不暴露对象存储内部路径
