## Purpose

定义提示词模板与版本创建接口的幂等语义：客户端如何标识一次创建意图，服务端如何识别重复请求，以及重复请求应当返回什么，使网络重试或用户重试不会产生重复记录。

## ADDED Requirements

### Requirement: Prompt write requests carry an idempotency key
创建提示词模板和创建提示词版本的请求 MUST 携带幂等键。同一次创建意图的重试 MUST 复用同一个幂等键；不同的创建意图 MUST 使用不同的幂等键。

#### Scenario: Create requests include a key
- **WHEN** 客户端发起创建提示词模板或创建提示词版本的请求
- **THEN** 请求携带幂等键标识本次创建意图

#### Scenario: Retry of one intent reuses its key
- **WHEN** 一次创建意图因网络原因重试
- **THEN** 重试请求携带与首次请求相同的幂等键

#### Scenario: A new intent uses a fresh key
- **WHEN** 用户在一次创建完成后发起另一次独立的创建
- **THEN** 该请求携带与之前不同的幂等键

### Requirement: Server deduplicates by idempotency key
服务端 MUST 按幂等键去重同一作用域内的创建请求。当收到已成功处理过的幂等键时，服务端 MUST NOT 创建新记录，而 MUST 返回首次创建的资源，且响应形态与首次成功响应一致。

#### Scenario: Duplicate key returns the original resource
- **WHEN** 服务端收到一个已成功处理过的幂等键的创建请求
- **THEN** 服务端返回首次创建的模板及版本，数据库中记录数量不增加

#### Scenario: Distinct keys create distinct resources
- **WHEN** 服务端收到两个幂等键不同、内容合法且 code 不冲突的创建请求
- **THEN** 服务端分别创建两条独立记录

#### Scenario: Absent key falls back to normal creation
- **WHEN** 创建请求未携带幂等键
- **THEN** 服务端按常规创建流程处理，既有的 code 唯一性与内容重复校验仍然生效

#### Scenario: Rejected requests do not consume a key
- **WHEN** 一次携带幂等键的创建请求被服务端拒绝（如 code 冲突、字段非法）
- **THEN** 该幂等键 MUST NOT 被记录为已成功，用户修正输入后可复用该键成功创建

### Requirement: Creation remains atomic across template and version
创建提示词模板的操作 MUST 原子地建立模板、其 `v1` 版本以及默认版本指向。任一环节失败时 MUST NOT 留下部分记录。文件同步失败 MUST NOT 回滚已提交的模板与版本，而 MUST 以同步状态形式记录。

#### Scenario: Failure leaves no partial records
- **WHEN** 模板创建过程中版本写入失败
- **THEN** 数据库中不留下该模板记录，也不留下孤立版本

#### Scenario: File sync failure preserves the created version
- **WHEN** 模板与 `v1` 已成功写入但提示词文件同步失败
- **THEN** 模板与版本保留，版本同步状态标记为失败并可重试
