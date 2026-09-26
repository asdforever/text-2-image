## Why

提示词商城的「新建提示词」弹层存在两个用户可见缺陷：弹层会在用户仍在填写时意外关闭，导致已输入内容丢失；以及创建操作在界面上报「创建失败」，但后端实际已经成功落库，用户据此重试会造成重复模板或困惑。第二个问题的根因已定位为 API 客户端把「响应解析失败」与「请求失败」混为一谈，且这两个写接口是全项目唯二未携带幂等键的变更类请求。

## What Changes

- **修复创建结果误判**：`request()` 在 HTTP 状态成功但响应体缺失或无法解析时，当前会静默返回 `undefined`，调用方随后访问 `result.version.versionNo` 抛出 `TypeError` 并落入 `catch`，展示「创建失败」。改为在响应契约不完整时抛出可区分的错误，使「创建结果未知」不再被表述为「创建失败」。
- **为提示词写接口补齐幂等键**：`createPromptTemplate` 与 `createPromptVersion` 补发 `Idempotency-Key` 请求头；后端 `POST /api/prompt-templates` 与 `POST /api/prompt-templates/{id}/versions` 接受并校验该头，重复键返回首次创建的资源而非新建一行。对齐项目中 `create_suite` / `upload_image` 已有的幂等模式。
- **修复新建弹层意外关闭**：弹层不再因背景层点击而直接丢弃用户输入。具体触发场景仍待确认（见 Open Questions），修复方案在 design 阶段收敛。
- **保护未保存输入**：在存在未提交内容时关闭弹层需明确确认，避免误触丢失长文本 System Prompt。

## Capabilities

### New Capabilities
<!-- openspec/specs/ 目前为空——历史变更虽已描述过 prompt-marketplace，
     但从未同步到 openspec/specs/，故此处按新建 spec 处理。 -->
- `prompt-marketplace`: 提示词商城的新建提示词交互契约——弹层生命周期、未保存输入保护、创建成功/失败/结果未知三态的界面表述。
- `prompt-write-idempotency`: 提示词模板与版本创建接口的幂等语义——幂等键的接受、去重与重复请求的返回行为。

### Modified Capabilities
<!-- 无：openspec/specs/ 下不存在已同步的 spec 文件，因此没有可写增量的既有 capability。 -->

## Impact

- `src/api/client.ts`：`request()` 的响应契约校验（第 95-100 行）；`createPromptTemplate`、`createPromptVersion` 补发幂等键（第 124-125 行）。
- `src/pages/PromptMarketplacePage.tsx`：新建弹层的关闭逻辑与 `create()` 的错误分支表述（第 36-52、62-76 行）。
- `backend/app/routes/prompts.py`：两个 POST 路由接受 `Idempotency-Key` 头。
- `backend/app/prompt_repository.py`、`backend/app/prompt_sqlalchemy_repository.py`：幂等键的存储与查询。数据库事务本身已是原子的，无需改动事务边界。
- 可能需要迁移：幂等键持久化若复用 `suite_workbench.idempotency_keys`，需确认其 scope 命名可容纳提示词写操作。

## Open Questions

- 弹层意外关闭的确切触发场景未确认：是点击表单内原生 `<select>` 展开的选项时关闭、点击背景灰色区域关闭（当前代码的既有行为），还是点击页面其它区域（顶部导航/搜索框）也会关闭？代码中 backdrop 与内容区的 `stopPropagation` 结构本身是正确的，因此根因取决于实际触发路径，需复现后确定。
