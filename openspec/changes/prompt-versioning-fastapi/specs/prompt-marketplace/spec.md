## Purpose

为前端提供简洁的提示词商城体验：按模板聚合浏览、查看完整版本历史、从任意版本编辑并保存新版本，以及为生成流程选择默认或历史版本。

## ADDED Requirements

### Requirement: Marketplace lists templates as aggregate cards
商城 MUST 按提示词模板而不是按版本展示卡片；每张卡片 MUST 显示名称、稳定 code、默认版本和版本数量。

#### Scenario: Multiple versions remain one card
- **WHEN** 一个模板存在 v1、v2、v3
- **THEN** 商城列表只显示一张卡片，并标记 v3 为默认/最新

#### Scenario: Search matches aggregate metadata
- **WHEN** 用户输入名称、code 或类型关键词
- **THEN** 列表只显示匹配的模板聚合项，不把单独版本拆成多张卡片

### Requirement: Users can inspect version history
商城 MUST 在模板详情中展示版本号、创建时间、来源、修改说明、同步状态和默认标记，并允许查看任意版本的完整内容。

#### Scenario: History shows audit information
- **WHEN** 用户展开版本历史
- **THEN** 每个版本显示其版本号、来源、修改说明、创建时间和文件同步状态

#### Scenario: Historical content can be previewed
- **WHEN** 用户选择 v1 或其他历史版本查看
- **THEN** 详情面板展示该版本保存时的完整提示词内容，不被当前版本替换

### Requirement: Users save edits as a new version
商城 MUST 支持从默认或历史版本开始编辑；用户点击“保存为新版本”后 MUST 提交完整内容和可选修改说明，成功后显示新版本及同步状态。

#### Scenario: Save from a historical version
- **WHEN** 用户以 v1 为编辑起点并保存修改
- **THEN** 系统创建下一个版本（例如 v4），v1 不变，新版本自动成为默认版本

#### Scenario: Unsaved edits are not formal versions
- **WHEN** 用户仅修改编辑器内容但未点击保存
- **THEN** 数据库版本数量和默认版本不发生变化

#### Scenario: Sync failure is visible in the editor
- **WHEN** 保存成功但文件同步失败
- **THEN** 商城显示版本已保存及同步失败提示，并提供重试操作

### Requirement: Generation callers can choose a version
商城和后续生成配置 MUST 提供默认版本选择；用户显式选择历史版本后，本次请求 MUST 携带对应 `templateVersionId`，且不改变模板默认版本。

#### Scenario: Default selection uses latest
- **WHEN** 用户未手动选择版本开始生成
- **THEN** 请求使用模板当前默认版本 ID

#### Scenario: Explicit historical selection is preserved
- **WHEN** 用户选择 v2 开始生成
- **THEN** 请求使用 v2 的版本 ID，并在生成记录中保留该 ID

### Requirement: Users can create the first prompt from the marketplace
商城 MUST 在没有提示词模板时显示“新建提示词”入口，并提供创建表单；提交有效表单后 MUST 创建模板的 `v1` 版本、将其设为默认版本并显示文件同步结果。

#### Scenario: Empty marketplace offers creation
- **WHEN** 数据库中没有任何提示词模板
- **THEN** 页面显示“新建提示词”按钮和创建表单，而不是只有空状态

#### Scenario: Valid form creates v1
- **WHEN** 用户填写 code、名称、类型、阶段、执行目标和 System Prompt 后提交
- **THEN** 系统创建对应模板的 `v1`，将其设为默认版本，并刷新商城列表

#### Scenario: Invalid form is rejected locally
- **WHEN** 用户未填写必填字段或 code 格式不合法
- **THEN** 页面阻止提交并显示字段错误，不发送创建请求

#### Scenario: Creation failure is visible
- **WHEN** 服务端拒绝重复 code、数据库不可用或文件同步失败
- **THEN** 页面显示可理解的错误/同步状态，且不伪造创建成功
