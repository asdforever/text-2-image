## Context

见 proposal.md - Why。以下是塑造本设计的现状约束：

- 前端存在共享弹层原语 `src/components/ui/dialog.tsx`，其背景层使用 `onMouseDown` 关闭、内容区用 `onMouseDown` 阻止冒泡。而 `PromptMarketplacePage.tsx:62` 自行手写了一套背景层，使用的是 `onClick`。两者行为并不等价——这是 Bug 1 的关键差异点。
- API 客户端只有一个统一出口 `request()`（`src/api/client.ts:95-100`），所有接口共用其响应契约处理逻辑。
- 后端幂等设施已存在但覆盖不全：表 `suite_workbench.idempotency_keys(scope, key, resource_id, created_at)`，主键 `(scope, key)`，目前仅 `create-suite` 与 `upload:{suite_id}` 两个 scope 在用。
- 提示词数据位于独立 schema `prompt_library`，与 `suite_workbench` 分离。
- `prompt_library.prompt_versions` 上有 `protect_prompt_version()` 触发器：任何 `DELETE` 以及对内容字段的 `UPDATE` 都会抛异常，版本行是不可变的。
- 后端 `create_template_with_version` 已在单个 `session.begin()` 内原子完成模板、版本与默认版本指向的写入，事务边界本身正确，无需改动。

## Goals / Non-Goals

**Goals:**

- 让 `request()` 的响应契约失败可被调用方区分，而不是静默降级为 `undefined`。
- 统一新建弹层的关闭语义，消除手写背景层与共享 `Dialog` 原语之间的行为分歧。
- 用最小侵入的方式把既有幂等设施扩展到提示词写接口。

**Non-Goals:**

- 不引入新的弹层／表单／状态管理依赖（如 Radix、react-hook-form）——项目目前无此类依赖，为两个 bug 引入是不成比例的。
- 不重构 `PromptMarketplacePage` 的整体结构或把其它弹层（版本详情弹层）一并迁移。版本详情弹层同样是手写背景层，但不承载用户输入，误关闭代价低，本次不动。
- 不改动 `prompt_versions` 的不可变性约束或事务边界。
- 不为全部接口补幂等键，只覆盖本次涉及的两个提示词写接口。

## Decisions

### 决策 1：`request()` 在响应契约不完整时抛出专用错误类型

当前实现：

```ts
const payload = await response.json().catch(() => null);
if (!response.ok) throw new Error(payload?.error?.message ?? "请求失败");
return payload?.data as T;   // payload 为 null 时静默返回 undefined
```

`as T` 掩盖了 `undefined`，把「响应无法解析」变成了调用方的运行时 `TypeError`，而该异常与真正的请求失败在 `catch` 里无法区分。

选择：新增一个可判别的错误类型（如 `ApiResultUnknownError`），在 `response.ok` 为真但 `payload?.data` 缺失时抛出，携带 HTTP 状态码与请求方法/路径。调用方据此走「结果未知」分支。

- **为什么不改成返回 `null` 并让调用方判空**：需要修改全部数十个调用点，且忘记判空时行为退化回当前的静默失败。抛错默认安全。
- **为什么不直接沿用 `Error`**：调用方无法把「服务端明确拒绝」与「结果未知」分开，而 specs 要求这两者的界面表述不同。
- **副作用**：其它接口若曾依赖 `undefined` 返回值而未报错，现在会抛错。这是暴露既有隐藏缺陷，属预期收益；需在实施时检查是否有接口返回空响应体（如 204），必要时对这类接口显式豁免。

### 决策 2：Bug 1 通过收敛到 `onMouseDown` + 复用共享语义修复

根因判断：手写背景层用 `onClick` 关闭。`click` 事件在 `mousedown` 与 `mouseup` 都发生后、由二者的**共同祖先**派发。因此当用户在表单内按下鼠标、拖动后在背景层松开（长文本 textarea 里选择文本、拖拽滚动条时很容易发生），`click` 的目标会落到背景层，内容区的 `stopPropagation` 从未被触发，弹层随即关闭——用户的主观感受就是「点了别的地方就关了」。原生 `<select>` 展开的选项列表在部分平台上渲染于文档树之外，其点击事件路径同样不经过内容区，会产生同类效果。共享 `Dialog` 原语用 `onMouseDown` 恰好避开了这个问题，这解释了为何其它弹层没有同样症状。

选择：新建弹层的背景层关闭改用 `onMouseDown`，并要求关闭意图仅在事件目标确为背景层自身时才生效（`event.target === event.currentTarget`），双重防护。

- **为什么不直接复用 `src/components/ui/dialog.tsx`**：该原语的 header 硬编码了 `PROJECT SETUP` eyebrow 文案和固定 `dialog-panel` 样式，与新建提示词弹层的既有视觉（`prompt-create-form`）不符。复用需先参数化原语，会扩大改动面并影响项目创建流程。本次先在页面内对齐语义，把原语参数化留作后续独立变更。
- **待确认项**：用户尚未确认具体触发路径（见 Open Questions）。上述修复对三种候选路径（拖拽跨区域、`<select>` 选项、真正的点击穿透）均有效，因此不阻塞实施；确认结果只影响验证用例的侧重。

### 决策 3：脏表单关闭前确认，通过派生 dirty 状态判断

以「当前表单值是否不等于初始空值」派生 dirty，而非新增独立的 dirty 标志位——后者需要在每个 onChange 里维护，容易漏。确认交互复用浏览器原生 `confirm` 还是自绘弹层，取决于项目既有约定；实施时若页面内已有二次确认样式则沿用，否则用原生 `confirm` 以避免嵌套弹层的焦点管理复杂度。

- **为什么不干脆禁用背景层关闭**：会与项目其它弹层的交互习惯不一致；且空表单时的快速关闭是合理需求，specs 已区分这两种情况。

### 决策 4：幂等键复用既有表，scope 命名为 `create-prompt-template` 与 `create-prompt-version:{template_id}`

沿用 `suite_workbench.idempotency_keys`，不在 `prompt_library` 下新建表。

- **为什么跨 schema 复用**：该表是通用基础设施而非业务表，`(scope, key)` 主键与 `resource_id uuid` 已能容纳提示词场景，无需迁移。新建表会产生两套等价机制。
- **代价**：`prompt_library` 的写事务需要触及 `suite_workbench` 的表，schema 边界被弱化。评估认为可接受——两者本就在同一数据库同一事务域内，且已有先例是同一张表服务多个 scope。若未来要把 prompt 库独立部署，此处需一并迁移，记入风险。
- **scope 命名**：`create-prompt-version` 带上 `template_id`，与既有 `upload:{suite_id}` 的作用域化命名一致，避免不同模板间键冲突。
- **关键约束**：幂等键的写入 MUST 与模板/版本创建处于**同一事务**。否则会出现「记录已创建但键未落库」，重试时产生重复。这一点与 `create_suite` 现有实现的处理方式需保持一致。
- **拒绝的请求不得占用键**：由于校验失败会回滚整个事务，键的插入自然一同回滚，无需额外处理——这正是同事务写入的附带好处。

### 决策 5：前端幂等键的生命周期绑定「一次创建意图」

`createIdempotencyKey()` 已存在（`client.ts:82`）。但若在 `createPromptTemplate` 内部每次调用都生成新键，重试就会拿到不同的键，幂等形同虚设。因此键必须在**发起一次创建意图时**生成并保存在组件状态中，成功或用户修改表单后才作废，重试复用同一个键。

- **为什么不在客户端函数内部生成**：那只能防住 `fetch` 层的自动重试，防不住用户看到「结果未知」后手动再点一次——而后者恰是本次要解决的场景。
- **签名影响**：`createPromptTemplate` / `createPromptVersion` 需接受调用方传入的键，这会改变其签名，需检查其它调用点（`updatePromptTemplate` 经由 `createPromptVersion`）。

## Risks / Trade-offs

- **决策 1 可能暴露其它接口的既有隐藏缺陷** → 实施时全量检查返回空响应体的接口（尤其 DELETE / 204 场景），必要时为其提供显式豁免路径；变更后跑通既有测试套件。
- **幂等键跨 schema 写入弱化了 `prompt_library` 的边界** → 记录于此，若未来 prompt 库独立部署需一并迁移该表或改为库内表；当前单库部署下无实际影响。
- **`prompt_versions` 的 DELETE 触发器禁止删除** → 幂等去重必须依赖事务回滚而非补偿删除；回滚不触发该触发器，故安全。切勿引入「先创建后删除」的补偿逻辑。
- **Bug 1 根因尚未由用户复现确认** → 所选修复对全部候选路径均有效，风险在于可能存在第四种未识别路径（如某处全局点击监听）。缓解：实施前在 `src` 中检索 `document.addEventListener('click'` / `'mousedown'` 类全局监听，确认不存在干扰源。
- **原生 `confirm` 阻塞主线程且样式不可控** → 若项目对交互一致性要求高，改为自绘确认层，代价是需处理嵌套弹层焦点管理。留给实施时按既有约定裁量。

## Migration Plan

无数据库迁移（复用既有表，不改表结构）。无需回填。

部署顺序：后端先行（接受并忽略未知的 `Idempotency-Key` 头是向后兼容的），前端随后。回滚策略：前后端可独立回滚——后端保留对无幂等键请求的常规处理路径，旧前端不发键仍可工作；新前端配旧后端时键被忽略，退化为当前行为，不会报错。

## Open Questions

- Bug 1 的确切触发路径（拖拽跨区域松开 / 原生 `<select>` 选项 / 其它）仍待用户复现确认。不阻塞实施，仅影响验证用例侧重——所选修复覆盖全部候选路径。
- 放弃确认使用原生 `confirm` 还是自绘确认层，按实施时页面既有约定裁量，不影响 specs 中的可观察行为。
