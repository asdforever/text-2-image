## Purpose

定义提示词商城「新建提示词」弹层的交互契约：弹层何时可以关闭、未提交输入如何受保护，以及创建操作的成功、失败、结果未知三种状态在界面上如何被准确表述。

## ADDED Requirements

### Requirement: Create dialog survives incidental interaction
新建提示词弹层 MUST 在用户与表单内部任何控件交互时保持打开，包括文本输入框、多行文本域、原生下拉选择控件及其展开的选项列表。弹层 MUST NOT 因表单内部控件的点击、焦点变化或选项选择而关闭。

#### Scenario: Typing in a field keeps the dialog open
- **WHEN** 用户在 Code、名称、System Prompt 或 User Prompt Template 任一字段中输入内容
- **THEN** 弹层保持打开，已输入内容不丢失

#### Scenario: Selecting a dropdown option keeps the dialog open
- **WHEN** 用户展开「类型」或「阶段」下拉框并选中一个选项
- **THEN** 弹层保持打开，所选值写入表单，其它字段已输入内容不丢失

#### Scenario: Interacting elsewhere on the page does not silently close the dialog
- **WHEN** 用户点击弹层以外的页面区域（如顶部导航、搜索框）
- **THEN** 系统 MUST NOT 在未经确认的情况下丢弃用户已输入的内容

### Requirement: Closing with unsaved input requires confirmation
当新建表单存在任何用户已输入且未提交的内容时，任何关闭意图（背景层点击、关闭按钮、取消按钮）MUST 先向用户确认；用户确认放弃后 MUST 关闭弹层并清空草稿，用户取消确认后 MUST 保持弹层打开且内容完整。

#### Scenario: Backdrop click on a dirty form asks first
- **WHEN** 用户已填写部分字段后点击弹层外的背景区域
- **THEN** 系统显示放弃确认提示，且在用户确认前不关闭弹层

#### Scenario: Discarding is explicit
- **WHEN** 用户在放弃确认提示中选择确认放弃
- **THEN** 弹层关闭，草稿内容被清空，列表状态不变

#### Scenario: Cancelling the confirmation preserves input
- **WHEN** 用户在放弃确认提示中选择继续编辑
- **THEN** 弹层保持打开，所有已输入字段内容保持原样

#### Scenario: Empty form closes without friction
- **WHEN** 用户未输入任何内容即点击关闭或背景区域
- **THEN** 弹层直接关闭，不显示确认提示

### Requirement: Creation outcome is reported accurately
创建提交后，界面 MUST 区分三种结果并分别表述：创建成功、创建被拒绝（服务端明确拒绝）、创建结果未知（请求已发出但客户端无法确认服务端结果）。系统 MUST NOT 在服务端已成功创建的情况下把结果表述为创建失败。

#### Scenario: Successful creation is confirmed
- **WHEN** 服务端成功创建模板及其 `v1` 且客户端完整收到响应
- **THEN** 界面显示创建成功及版本号，关闭弹层并刷新列表

#### Scenario: Server rejection is reported as failure
- **WHEN** 服务端以明确错误拒绝创建（如 code 重复冲突、字段非法）
- **THEN** 界面显示服务端给出的拒绝原因，弹层保持打开且保留用户输入，列表中不出现新模板

#### Scenario: Unknown outcome is not reported as failure
- **WHEN** 请求已发出，但客户端因响应体缺失、无法解析或连接中断而无法确认服务端结果
- **THEN** 界面 MUST 提示结果未确认并建议用户刷新核对，MUST NOT 断言「创建失败」

#### Scenario: Refreshing after an unknown outcome reflects true state
- **WHEN** 出现结果未知提示后用户刷新商城列表
- **THEN** 列表如实反映服务端状态——若已创建成功则新模板可见

### Requirement: Retry after an uncertain outcome does not duplicate
用户在结果未知或失败提示后重新提交同一份表单内容时，系统 MUST NOT 因该重试产生重复的提示词模板。

#### Scenario: Resubmitting the same draft creates at most one template
- **WHEN** 用户因结果未知提示而再次点击创建，且表单内容与首次提交完全一致
- **THEN** 服务端最终只存在一个对应模板，界面展示该模板的创建结果
