## Purpose

为主图和套图生成提供一个可保存、可复用、可追溯的全局配置中心，统一管理市场、模型、图片风格及提示词绑定，同时保证配置变更不会改写历史生成结果。

## ADDED Requirements

### Requirement: Global configuration editing and publishing

系统 SHALL 在全局侧边栏提供“生成配置”入口，并展示当前已保存配置与未保存编辑态。用户 SHALL 能够显式保存编辑内容；未点击保存前，编辑内容不得影响生成工作台或新的生成请求。

#### Scenario: Open the configuration center
- **WHEN** 用户从全局侧边栏进入“生成配置”
- **THEN** 系统展示已保存的市场、模型、图片风格、内置模块和提示词绑定，并标识当前是否存在未保存修改

#### Scenario: Save configuration changes
- **WHEN** 用户完成编辑并点击“保存”
- **THEN** 系统校验全部配置，通过后创建新的已保存配置版本，并使该版本供后续生成使用

#### Scenario: Reject invalid configuration
- **WHEN** 配置包含空名称、重复标识、无效提示词绑定或超过风格数量上限
- **THEN** 系统阻止保存并在对应区域展示可理解的错误信息，原已保存配置保持不变

#### Scenario: Discard unsaved changes
- **WHEN** 用户放弃当前编辑
- **THEN** 系统恢复到最近一次已保存配置，且不产生新的配置版本

### Requirement: Manage markets, image models, and style library

系统 SHALL 允许用户对具体电商平台、生图模型和图片风格进行新增、编辑和删除。电商平台 SHALL 归属于固定的“国内”或“国外”大类，并至少包含名称、适用平台或规范说明和默认输出语言；模型至少包含名称、模型约束及支持的分辨率；风格由大类和风格项组成，风格项至少包含名称和描述。每个风格大类 SHALL 最多包含 4 个风格项。

#### Scenario: Create a market or model
- **WHEN** 用户填写合法信息、选择国内或国外并保存一个新的具体电商平台或生图模型
- **THEN** 该条目出现在对应分组的配置中心和生成选择器中，并可参与提示词绑定

#### Scenario: Select a concrete platform within a market scope
- **WHEN** 用户在主图、套图或生成配置中打开电商市场
- **THEN** 系统先展示“国内”和“国外”两组，再允许选择组内具体平台；生成请求引用具体平台 ID，不得只引用分组名称

#### Scenario: Create and edit a style category or style
- **WHEN** 用户新增或编辑风格大类/风格项并保存
- **THEN** 配置中心展示更新后的分组、名称和描述，生成工作台使用更新后的可选项

#### Scenario: Enforce the style limit
- **WHEN** 某风格大类已经包含 4 个风格项
- **THEN** 系统禁止再新增第 5 个风格项，并提示用户先删除或移动现有风格

#### Scenario: Delete a configuration item
- **WHEN** 用户删除市场、模型、风格大类或风格项并保存
- **THEN** 该条目从后续生成的可选项中移除；历史生成快照仍保留该条目的名称和参数

### Requirement: Keep generation modules built in

系统 SHALL 保留主图模块和详情页模块的系统内置列表。用户不得新增、重命名或删除模块，但 SHALL 能够为每个内置模块维护提示词绑定。

#### Scenario: View built-in modules
- **WHEN** 用户在配置中心打开主图模块或详情页模块区域
- **THEN** 系统展示当前内置模块列表及其绑定状态，且不显示模块增删改入口

#### Scenario: Bind a prompt to a built-in module
- **WHEN** 用户为某个主图或详情页模块选择提示词版本并保存
- **THEN** 该提示词版本成为该模块后续生成的当前绑定版本

#### Scenario: Set generation count per module
- **WHEN** 用户在主图或详情页模块中选择一个模块并设置生成张数
- **THEN** 系统保存该模块 1–4 张的数量，并在本次生成中为该模块创建对应数量的结果；未设置时默认为 1 张

#### Scenario: Remove suite advanced settings
- **WHEN** 用户打开套图工作台
- **THEN** 系统不展示独立的“高级设置”模块，模型、比例和分辨率仍在输出设置中可配置

### Requirement: Bind prompt versions by generation slot

系统 SHALL 按槽位维护当前生效的提示词版本绑定，槽位至少包括电商市场、生图模型、图片风格、主图模块和详情页模块。绑定 SHALL 引用具体提示词版本，而不是仅引用可变的提示词模板。

#### Scenario: Select a prompt version
- **WHEN** 用户在某个配置槽位选择提示词模板的具体版本并保存
- **THEN** 系统展示模板名称、版本号和绑定状态，并在后续生成中使用该版本

#### Scenario: Remove a prompt binding
- **WHEN** 用户清除某个槽位的绑定并保存
- **THEN** 后续生成不再附加该槽位的绑定提示词，并保留其他槽位绑定

#### Scenario: Referenced prompt version is unavailable
- **WHEN** 已绑定的提示词版本被归档或无法解析
- **THEN** 系统在配置中心标记该绑定失效并阻止依赖该绑定的配置发布，直到用户重新选择可用版本或清除绑定

### Requirement: Apply only published configuration to future generation

主图和套图工作台 SHALL 读取最近一次已保存的全局配置。每次发起生成时，系统 SHALL 将当时生效的具体市场、模型、风格、模块参数、模块张数和提示词版本写入该次生成的配置快照；之后的配置变更不得修改该快照。

#### Scenario: Generate with the published version
- **WHEN** 用户发起主图或套图生成
- **THEN** 请求使用最近一次已保存的全局配置和对应提示词绑定，而不是配置中心的未保存编辑态

#### Scenario: Historical generation remains stable
- **WHEN** 用户在生成完成后修改或删除市场、模型、风格或提示词绑定
- **THEN** 历史任务、历史图片和历史提示词快照继续显示生成时的原始配置内容

#### Scenario: Draft references a deleted item
- **WHEN** 当前项目草稿引用的市场、模型或风格已被删除并且用户尝试继续生成
- **THEN** 系统标记该选择失效，要求用户重新选择有效条目后才允许提交生成
