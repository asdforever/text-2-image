## MODIFIED Requirements

### Requirement: 新建提示词按钮位置

系统 SHALL 将新建提示词按钮放置在页面左上角独立区域，与搜索框分离。

#### Scenario: 新建按钮独立显示

- **WHEN** 用户访问提示词商城页面
- **THEN** 页面左上角独立显示"新建提示词"按钮，搜索框位于右侧

#### Scenario: 空状态的新建按钮

- **WHEN** 商城中没有任何提示词模板
- **THEN** 空状态界面显示独立的"新建提示词"按钮，不与搜索区域混在一起

### Requirement: 创建表单 kind 选择为中文

系统 SHALL 在创建提示词表单中使用中文下拉选择 `kind`。

#### Scenario: 类型下拉显示中文

- **WHEN** 用户打开创建提示词表单
- **THEN** 类型字段显示为下拉选择框，选项为：图生图、文生图、文生文、图生文

#### Scenario: 选择类型后设置 kind 和 kind_name

- **WHEN** 用户选择"图生图"
- **THEN** 系统设置 `kind="image_to_image"` 和 `kind_name="图生图"`

#### Scenario: 提交时包含 kind_name

- **WHEN** 用户提交创建表单
- **THEN** 请求体包含 `kind` 和 `kind_name` 两个字段

### Requirement: 商城 kind 筛选

系统 SHALL 在提示词商城顶部提供按 `kind` 筛选的功能。

#### Scenario: 筛选标签显示

- **WHEN** 用户访问提示词商城
- **THEN** 页面顶部显示筛选标签：[ 全部 ] [ 图生图 ] [ 文生图 ] [ 文生文 ] [ 图生文 ]

#### Scenario: 点击筛选标签

- **WHEN** 用户点击"图生图"标签
- **THEN** 系统仅显示 `kind="image_to_image"` 的提示词卡片，该标签高亮显示

#### Scenario: 全部标签

- **WHEN** 用户点击"全部"标签
- **THEN** 系统显示所有提示词，不进行 `kind` 筛选

#### Scenario: 筛选与搜索结合

- **WHEN** 用户选择"图生图"筛选并在搜索框输入关键词
- **THEN** 系统显示同时满足 `kind` 筛选和搜索关键词的提示词

### Requirement: 卡片显示 kind 图标和中文标签

系统 SHALL 在提示词卡片上显示 `kind` 对应的图标和中文名称。

#### Scenario: 图生图卡片显示

- **WHEN** 提示词的 `kind="image_to_image"`
- **THEN** 卡片顶部显示 🖼️→🖼️ 图标和"图生图"标签

#### Scenario: 文生图卡片显示

- **WHEN** 提示词的 `kind="text_to_image"`
- **THEN** 卡片顶部显示 📝→🖼️ 图标和"文生图"标签

#### Scenario: 文生文卡片显示

- **WHEN** 提示词的 `kind="text_to_text"`
- **THEN** 卡片顶部显示 📝→📝 图标和"文生文"标签

#### Scenario: 图生文卡片显示

- **WHEN** 提示词的 `kind="image_to_text"`
- **THEN** 卡片顶部显示 🖼️→📝 图标和"图生文"标签

### Requirement: 卡片按钮文案更新

系统 SHALL 将提示词卡片的"查看版本"按钮更名为"版本工作台"。

#### Scenario: 按钮文案显示

- **WHEN** 用户浏览提示词卡片
- **THEN** 卡片底部按钮显示"版本工作台"而非"查看版本"

#### Scenario: 点击按钮跳转

- **WHEN** 用户点击"版本工作台"按钮
- **THEN** 系统导航到 `/prompts/:id/versions` 版本工作台页面

### Requirement: 去除 stage 字段引用

系统 SHALL 从提示词商城的所有显示和逻辑中移除 `stage` 字段。

#### Scenario: API 响应不包含 stage

- **WHEN** 前端调用 `GET /api/prompt-templates`
- **THEN** 响应中的模板对象不包含 `stage` 字段

#### Scenario: 创建表单不包含 stage

- **WHEN** 用户打开创建提示词表单
- **THEN** 表单中不显示 `stage` 相关的输入字段

#### Scenario: 前端代码移除 stage 引用

- **WHEN** 开发者检查前端代码
- **THEN** 所有对 `stage` 字段的读取、显示、提交逻辑已删除
