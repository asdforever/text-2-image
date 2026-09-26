## Purpose

为提示词提供稳定身份、完整且可追溯的不可变版本历史，使商城和后续生成流程能够默认使用最新版本并按需选择任意历史版本。

## ADDED Requirements

### Requirement: Prompt templates are grouped by stable identity
系统 MUST 使用唯一且稳定的 `code` 标识一个提示词模板，并将该模板的所有版本聚合为一个可查询资源。

#### Scenario: Listing templates returns one entry per code
- **WHEN** 客户端请求提示词模板列表
- **THEN** 每个稳定 `code` 只返回一个模板聚合项，并包含默认版本摘要和版本数量

#### Scenario: Duplicate code is rejected for unrelated templates
- **WHEN** 创建新模板时提交已存在的 `code`
- **THEN** 系统拒绝创建并返回可识别的冲突错误，不创建第二个模板身份

### Requirement: Saved prompt versions are immutable and sequential
系统 MUST 为每个模板生成从 `v1` 开始连续递增的版本号；已保存版本的提示词内容和元数据 MUST 不可被更新或删除。

#### Scenario: First saved version is v1
- **WHEN** 一个不存在版本的模板首次保存有效提示词
- **THEN** 系统创建版本号为 `v1` 的版本并记录完整内容

#### Scenario: Saving a later version increments the number
- **WHEN** 用户以任意已有版本为编辑起点保存新内容
- **THEN** 系统创建下一个连续版本，历史版本保持原样

#### Scenario: Published history cannot be overwritten
- **WHEN** 客户端尝试修改或删除已保存版本
- **THEN** 系统拒绝操作并保留原版本数据

### Requirement: Version records retain audit metadata
每个保存版本 MUST 记录完整提示词内容、输入/输出结构、内容 hash、来源、修改说明、创建者、创建时间、文件路径和文件同步状态。

#### Scenario: Marketplace save records metadata
- **WHEN** 商城保存新版本并提交修改说明
- **THEN** 返回的版本记录包含 `source=marketplace`、说明、`created_by=local-user` 及创建时间

#### Scenario: File import records metadata
- **WHEN** 本地导入一个新的 Markdown 提示词
- **THEN** 返回的版本记录包含 `source=file_import`、来源文件路径及内容 hash

### Requirement: Latest version is the default and historical versions are selectable
系统 MUST 在保存新版本后自动将其设为模板默认版本；版本解析在未指定版本 ID 时 MUST 返回默认版本，指定历史版本时 MUST 返回该模板下对应的版本。

#### Scenario: Resolve without explicit version
- **WHEN** 调用方未提供 `templateVersionId`
- **THEN** 系统返回该模板当前默认的最新版本

#### Scenario: Resolve an older version explicitly
- **WHEN** 调用方提供属于该模板的历史版本 ID
- **THEN** 系统返回该历史版本，而不改变默认版本指针

#### Scenario: Version from another template is rejected
- **WHEN** 调用方提供不属于目标模板的版本 ID
- **THEN** 系统返回版本归属错误，不执行提示词

### Requirement: Identical content does not create redundant versions
系统 MUST 使用规范化提示词内容计算 hash；同一模板提交与当前版本内容完全相同的保存请求时 MUST 拒绝重复版本或返回已存在版本。

#### Scenario: Repeated save is idempotent
- **WHEN** 用户重复提交与当前版本相同的内容
- **THEN** 版本数量不增加，并返回重复内容错误或现有版本标识
