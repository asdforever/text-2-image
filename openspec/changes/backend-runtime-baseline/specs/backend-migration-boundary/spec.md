## Purpose

为 FastAPI 与现有 Node 服务并行演进建立单一、可审计且可回滚的数据库迁移边界，确保 schema 变更不会重复执行、静默漂移或破坏已有项目素材与对象存储数据。

## ADDED Requirements

### Requirement: 唯一迁移事实来源

系统 SHALL 为本项目声明唯一的迁移来源和执行入口。应用启动 SHALL 默认只检查 schema 状态，不得隐式执行未审批的结构变更；迁移命令和 CI SHALL 使用同一入口。

#### Scenario: 执行待处理迁移
- **WHEN** 运维在专用数据库执行迁移入口
- **THEN** 系统按确定顺序执行所有待处理迁移，并记录每个迁移的名称、校验和和执行时间

#### Scenario: 检测迁移漂移
- **WHEN** 已执行迁移文件的内容或校验和发生变化
- **THEN** 系统拒绝继续迁移并报告漂移，不得静默覆盖执行记录

### Requirement: 并发迁移安全

迁移执行 SHALL 使用数据库级互斥机制保证同一数据库同一时间只有一个迁移者。并发启动的其他实例 SHALL 等待或明确失败，不得交错执行迁移步骤。

#### Scenario: 两个实例并发迁移
- **WHEN** 两个 FastAPI 实例同时执行迁移
- **THEN** 只有一个实例执行结构变更，另一个实例在锁释放后读取一致版本或返回可重试错误

### Requirement: 升级与回滚验证

每个迁移版本 SHALL 声明可验证的升级和回滚行为。回滚操作 SHALL 只撤销明确选定的版本，并保留迁移记录的一致性；失败时不得标记为已完成。

#### Scenario: 升级和回滚成功
- **WHEN** 测试环境执行一次升级后再执行对应回滚
- **THEN** schema 恢复到目标版本，迁移记录与实际 schema 一致，已有业务数据仍满足约束

#### Scenario: 迁移中途失败
- **WHEN** 迁移在事务或步骤中失败
- **THEN** 系统报告失败版本并阻止应用将数据库视为已升级，不得留下半完成的迁移记录

### Requirement: 服务并行与选择性路由

迁移期间 FastAPI 和现有 Node 服务 SHALL 能在不同端口并行运行。代理配置 SHALL 仅将已验收的路径切换到 FastAPI，未声明路径继续由 Node 服务处理。

#### Scenario: 选择性代理切流
- **WHEN** 代理只切换 suite/input-image 垂直切片
- **THEN** 该切片请求到达 FastAPI，其他请求仍到达 Node 服务，两个服务可以同时响应

### Requirement: 无损回滚到 Node

停止或切回 Node 服务 SHALL 不删除 FastAPI 创建的 schema、迁移记录、数据库记录或对象存储对象。回滚后 Node 服务仍能读取迁移前兼容的数据和已上传素材。

#### Scenario: 停止 FastAPI 并恢复 Node 路由
- **WHEN** 代理恢复到 Node 服务并停止 FastAPI
- **THEN** 已有项目、输入图片及其对象仍可读取，数据库和对象存储不会因服务停止而清理
