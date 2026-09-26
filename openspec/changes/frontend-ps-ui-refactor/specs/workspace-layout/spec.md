## Purpose

定义工作台的整体布局结构（三栏：工具栏/工作区/侧边面板）和 tab 切换机制。

## ADDED Requirements

### Requirement: 工作台使用三栏布局

系统 SHALL 在用户进入项目后展示三栏布局：左侧工具栏（固定宽度）、中间工作区（自适应）、右侧侧边面板（可收起）。

#### Scenario: 首次进入项目
- **WHEN** 用户通过项目列表点击某个项目
- **THEN** 显示三栏布局，左侧工具栏宽度 60px，中间工作区占满剩余宽度，右侧侧边面板宽度 280px

#### Scenario: 收起右侧面板
- **WHEN** 用户点击右侧面板顶部的收起按钮
- **THEN** 面板收起为 0px 宽度，中间工作区宽度自动扩展，左侧留下展开按钮

### Requirement: 顶部显示 tab 栏和项目信息

系统 SHALL 在工作台顶部显示项目名称、tab 栏（白底图/套图/视频）、用户头像。

#### Scenario: 显示已激活的 tab
- **WHEN** 用户进入项目且 URL 为 `/projects/:id?tab=suite`
- **THEN** 顶部 tab 栏中"套图"tab 高亮显示，中间工作区展示套图工作区内容

#### Scenario: 点击 tab 切换工作区
- **WHEN** 用户当前在"白底图"tab，点击"套图"tab
- **THEN** URL 更新为 `/projects/:id?tab=suite`，中间工作区切换到套图工作区，右侧面板内容随之更新

#### Scenario: 未启用的 tab 显示禁用状态
- **WHEN** 用户创建项目时未勾选"生成视频"
- **THEN** 顶部 tab 栏中"视频"tab 显示为灰色禁用状态，点击无反应

### Requirement: 左侧工具栏根据当前 tab 动态变化

系统 SHALL 根据当前激活的 tab 在左侧工具栏展示对应的工具按钮。

#### Scenario: 白底图 tab 的工具栏
- **WHEN** 用户在白底图 tab
- **THEN** 左侧工具栏显示图标按钮："选择"、"批量选择"、"生成白底图"、"导出"、"删除"

#### Scenario: 套图 tab 的工具栏
- **WHEN** 用户在套图 tab
- **THEN** 左侧工具栏显示图标按钮："选择"、"生成套图"、"编辑图片"、"调整布局"、"导出"

#### Scenario: 视频 tab 的工具栏
- **WHEN** 用户在视频 tab（占位状态）
- **THEN** 左侧工具栏显示占位按钮，点击后显示"功能开发中"提示

### Requirement: 右侧面板包含资产库和历史两个子 tab

系统 SHALL 在右侧面板顶部提供"资产库"和"历史"两个子 tab，用户可切换查看。

#### Scenario: 默认显示资产库
- **WHEN** 用户首次进入工作台
- **THEN** 右侧面板默认显示"资产库"子 tab，展示项目内所有资产

#### Scenario: 切换到历史面板
- **WHEN** 用户点击右侧面板的"历史"子 tab
- **THEN** 面板内容切换为历史/版本时间线视图

### Requirement: 工作台支持键盘快捷键

系统 SHALL 支持常用键盘快捷键（如 Ctrl+S 保存、Ctrl+Z 撤销、Tab 键切换工作区）。

#### Scenario: 使用 Tab 键切换工作区
- **WHEN** 用户在白底图 tab 按下 Ctrl+Tab
- **THEN** 激活下一个可用 tab（套图 tab），工作区内容切换

#### Scenario: 未启用 tab 被跳过
- **WHEN** 用户在白底图 tab 按 Ctrl+Tab，但套图 tab 未启用
- **THEN** 跳过套图 tab，直接切换到下一个可用 tab（如视频 tab 已启用则切换到视频，否则循环回白底图）
