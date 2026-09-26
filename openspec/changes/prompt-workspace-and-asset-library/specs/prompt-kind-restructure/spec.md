## Purpose

重塑提示词分类体系，将原有的 `kind`/`stage` 双字段分类简化为基于输入输出类型的单 `kind` 字段四分类系统（图生图、文生图、文生文、图生文），并新增 `kind_name` 字段存储中文名称，提升分类清晰度和用户体验。

## ADDED Requirements

### Requirement: 新的 kind 枚举值

系统 SHALL 使用四个新的 `kind` 枚举值替代原有的分类。

#### Scenario: kind 枚举值定义

- **WHEN** 创建或更新提示词模板
- **THEN** `kind` 字段仅接受以下四个值之一：`"image_to_image"`（图生图）、`"text_to_image"`（文生图）、`"text_to_text"`（文生文）、`"image_to_text"`（图生文）

#### Scenario: 无效的 kind 值

- **WHEN** 用户提交不在枚举范围内的 `kind` 值
- **THEN** 系统返回 400 错误，提示 `kind` 值无效

### Requirement: kind_name 字段

系统 SHALL 要求提示词模板包含 `kind_name` 字段存储中文名称。

#### Scenario: 创建时提供 kind_name

- **WHEN** 用户创建提示词模板时提供 `kind_name` 字段
- **THEN** 系统存储该中文名称到数据库

#### Scenario: kind 与 kind_name 对应关系

- **WHEN** 用户提交 `kind="image_to_image"` 和 `kind_name="图生图"`
- **THEN** 系统接受该组合并存储

#### Scenario: kind_name 不匹配

- **WHEN** 用户提交的 `kind_name` 与 `kind` 不对应（如 `kind="image_to_image"` 但 `kind_name="文生图"`）
- **THEN** 系统接受该值（前端负责保证一致性，后端不强制校验）

#### Scenario: 缺少 kind_name

- **WHEN** 用户创建提示词模板时未提供 `kind_name`
- **THEN** 系统返回 400 错误，提示缺少必填字段 `kind_name`

### Requirement: 前端 kind 选择

系统 SHALL 在前端提供中文下拉选择 `kind`。

#### Scenario: 创建表单显示中文选项

- **WHEN** 用户打开创建提示词表单
- **THEN** 类型下拉框显示选项：图生图、文生图、文生文、图生文

#### Scenario: 选择后同时设置 kind 和 kind_name

- **WHEN** 用户选择"图生图"
- **THEN** 前端同时设置 `kind="image_to_image"` 和 `kind_name="图生图"`，并在提交时一起发送给后端

### Requirement: 列表显示 kind_name

系统 SHALL 在提示词商城列表中显示 `kind_name` 而非 `kind`。

#### Scenario: 卡片显示中文类型

- **WHEN** 用户浏览提示词商城
- **THEN** 每个提示词卡片显示 `kind_name`（如"图生图"）和对应的图标

#### Scenario: 列表 API 返回 kind_name

- **WHEN** 前端调用 `GET /api/prompt-templates`
- **THEN** 响应中每个模板包含 `kind` 和 `kind_name` 字段

### Requirement: 商城 kind 筛选

系统 SHALL 在提示词商城提供按 `kind` 筛选的功能。

#### Scenario: 筛选选项显示中文

- **WHEN** 用户查看筛选选项
- **THEN** 系统显示：全部、图生图、文生图、文生文、图生文

#### Scenario: 选择筛选条件

- **WHEN** 用户选择"图生图"筛选
- **THEN** 系统仅显示 `kind="image_to_image"` 的提示词模板

#### Scenario: API 支持 kind 筛选

- **WHEN** 前端调用 `GET /api/prompt-templates?kind=image_to_image`
- **THEN** 后端返回仅包含该 `kind` 的模板列表

## REMOVED Requirements

### Requirement: stage 字段

**Reason**: `stage` 字段与 `kind` 分类重叠且含义不清晰，新的四分类 `kind` 体系已涵盖其功能。

**Migration**: 
- 数据库迁移需删除 `prompt_templates.stage` 和 `prompt_versions.stage` 列
- 现有提示词需根据原 `kind` 和 `stage` 组合映射到新的 `kind` 值
- 前端代码需移除所有对 `stage` 字段的引用
- API 端点不再接受或返回 `stage` 字段

#### Scenario: 迁移脚本映射规则

- **WHEN** 执行数据库迁移
- **THEN** 系统根据以下规则映射现有数据：
  - `kind="direct_generation"` + `stage="task_image"` → 新 `kind="image_to_image"`
  - `stage="reverse_prompt"` → 新 `kind="image_to_text"`
  - 其他组合根据实际语义映射到对应的新 `kind`

### Requirement: 原有 kind 枚举值

**Reason**: 原有的 `kind` 枚举值（`planner`、`direct_generation`、`repair`）语义不明确，不能直观表达输入输出类型。

**Migration**:
- 数据库迁移需将现有 `kind` 值映射到新的四分类
- 前端需更新所有硬编码的 `kind` 值引用
- API 需拒绝旧的 `kind` 值，返回 400 错误

#### Scenario: API 拒绝旧 kind 值

- **WHEN** 用户提交 `kind="planner"` 的创建请求
- **THEN** 系统返回 400 错误，提示 `kind` 值无效，并建议使用新的四分类值
