## Purpose

让根目录 `prompt/` 始终保存每个提示词的最新可读文件，并通过导入、原子覆盖和失败重试与数据库版本历史保持可观测的一致状态。

## ADDED Requirements

### Requirement: Root prompt files use a stable Markdown format
系统 MUST 以根目录 `prompt/` 为唯一文件仓库；每个提示词 MUST 使用一个以稳定 `code` 命名的 UTF-8 Markdown 文件，并包含元数据、System Prompt、User Prompt Template、Input Schema 和 Output Schema 区块。

#### Scenario: A valid file can be imported
- **WHEN** `prompt/` 中存在包含必需元数据和区块的 Markdown 文件
- **THEN** 导入命令解析出一个提示词模板及其完整版本内容

#### Scenario: Legacy prompt directory is ignored
- **WHEN** 执行提示词导入
- **THEN** 系统只扫描根 `prompt/`，不读取或依赖 `pic_agent_suite_workbench/prompt/`

#### Scenario: Invalid file is reported without partial import
- **WHEN** 文件缺少必需元数据、区块或包含无效 schema
- **THEN** 系统报告文件级错误，并且该文件不会产生半成品版本

### Requirement: File import creates or iterates database versions
系统 MUST 将根 `prompt/` 中的新文件导入为 `v1`；已有 `code` 的文件内容发生变化时 MUST 创建下一个版本并更新默认版本，不得覆盖历史版本。

#### Scenario: New file creates v1
- **WHEN** 数据库不存在文件中的 `code`
- **THEN** 导入创建模板、`v1` 版本并将其设为默认版本

#### Scenario: Changed file creates a new version
- **WHEN** 数据库已有同一 `code` 且文件 hash 与默认版本不同
- **THEN** 导入创建下一个版本并记录 `source=file_import`

### Requirement: Saving a version atomically updates the latest file
系统 MUST 在商城保存新版本或执行同步重试时，将渲染后的 Markdown 写入临时文件并通过原子替换更新 `prompt/<code>.md`；文件内容 MUST 对应被同步版本。

#### Scenario: Successful marketplace save synchronizes the file
- **WHEN** 新版本写入数据库且目标目录可写
- **THEN** 对应文件被原子替换，版本同步状态为 `synced`

#### Scenario: Filesystem failure is observable
- **WHEN** 数据库版本已保存但临时文件写入或替换失败
- **THEN** 版本仍保留，状态为 `failed`，记录错误信息，且 API 明确返回同步失败

### Requirement: Failed synchronization can be retried safely
系统 MUST 提供针对失败版本的幂等重试能力；重试成功后更新同步状态和时间，不得创建额外版本。

#### Scenario: Retry repairs a failed file
- **WHEN** 用户对 `failed` 版本执行同步重试且目录恢复可写
- **THEN** 文件被更新为该版本内容，状态变为 `synced`

#### Scenario: Retrying an already synced version is harmless
- **WHEN** 用户重复执行同一版本的同步重试
- **THEN** 系统不创建新版本，文件仍保持该版本内容

### Requirement: Reset and migration start from the new root schema
系统 MUST 使用根项目的 Alembic 迁移重建所需 schema；全量重置命令 MUST 需要开发环境和显式确认，并且旧提示词模板不得自动导入。

#### Scenario: Guarded development reset
- **WHEN** 操作者在 `ENVIRONMENT=development` 下提供 `--confirm-reset`
- **THEN** 系统删除应用数据库对象并执行 Alembic 最新迁移

#### Scenario: Reset is refused outside development
- **WHEN** 操作者在非开发环境或缺少确认参数时执行重置
- **THEN** 系统拒绝操作且不删除任何数据库对象
