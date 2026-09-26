## Purpose

为 PicAgent 建立可启动、可观测、可测试的 FastAPI 服务基础，使后续业务域能够共享一致的配置、生命周期、错误响应和依赖健康检查。

## ADDED Requirements

### Requirement: Service configuration is environment-driven

服务 MUST 从环境变量或本地未提交的环境文件读取运行配置，启动时校验必填项、URL 和端口；缺少或格式错误的配置 MUST 阻止服务启动，并且错误信息不得包含密钥值。

#### Scenario: Missing required configuration

- **WHEN** 服务启动且缺少数据库、对象存储或服务端口所需配置
- **THEN** 进程以非零状态退出，并指出缺少的配置名称，不输出任何密钥内容

#### Scenario: Valid configuration

- **WHEN** 所有必填配置通过校验
- **THEN** 服务完成应用初始化并开始监听配置的地址和端口

### Requirement: API responses use a stable envelope

所有 JSON API 响应 MUST 包含唯一 `requestId`。成功响应 MUST 使用 `{ "data": ... , "requestId": "..." }`，失败响应 MUST 使用 `{ "error": { "code": "...", "message": "..." }, "requestId": "..." }`，并返回与错误类别一致的 HTTP 状态码。

#### Scenario: Successful request

- **WHEN** API 请求成功完成
- **THEN** 响应状态为 2xx，body 包含 `data` 和非空 `requestId`

#### Scenario: Validation or dependency failure

- **WHEN** API 请求因输入、资源或依赖失败
- **THEN** 响应使用错误信封，包含稳定错误码和非空 `requestId`，且不返回堆栈或密钥

### Requirement: Service exposes liveness and readiness checks

服务 MUST 提供健康检查端点。存活检查只反映进程是否能够响应；就绪检查 MUST 验证 PostgreSQL 和对象存储依赖是否可用，并在依赖不可用时返回非 2xx 状态。

#### Scenario: Dependencies are ready

- **WHEN** 客户端请求健康检查且数据库与对象存储连接可用
- **THEN** 存活和就绪检查均返回 2xx，并在 `data` 中标识服务已就绪

#### Scenario: Dependency is unavailable

- **WHEN** 客户端请求就绪检查且任一必需依赖不可用
- **THEN** 就绪检查返回 503 和错误信封，存活检查仍可返回进程存活状态

### Requirement: Mutating requests support idempotency

创建、上传和其他会产生持久化副作用的 API MUST 接受 `Idempotency-Key`。相同作用域内使用相同 key 重复提交时，服务 MUST 返回第一次提交的结果，不得重复创建资源或写入对象。

#### Scenario: Duplicate mutation

- **WHEN** 客户端使用相同 `Idempotency-Key` 重复发送完全相同的变更请求
- **THEN** 服务返回与第一次请求等价的资源结果，并保持资源数量不变

#### Scenario: Key is missing where required

- **WHEN** 需要幂等保护的变更请求未提供 `Idempotency-Key`
- **THEN** 服务拒绝请求并返回明确的幂等键错误码
