# 规划大师连续对话 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在主图和详情套图的常规版、专业版加入弹窗连续对话，支持修改预览、确认应用、刷新恢复及版本恢复，继续执行现有规则。

**Architecture:** 新增会话服务和持久化存储，复用现有规划模型绑定、素材读取、结构校验和生图编译。每轮产生澄清问题或不可变候选规划，由服务端计算累计差异；应用操作更新正式规划指针。前端在原有配置与生成工作台中打开弹窗，应用前保持正式草稿，生成批次继续保留原始快照。

**Tech Stack:** 当前 FastAPI、Pydantic、SQLAlchemy/PostgreSQL、Alembic、React、TypeScript、Zustand、TanStack Router、pytest、Playwright。

**Spec:** `docs/superpowers/specs/2026-10-08-conversational-module-planning-design.md`

## Global Constraints

- “用户补充约束：尽量保持已有规则，新增交互遵守当前规则。”
- “没有要求修改的内容保持原样。”
- “修改先生成预览及差异，点击‘应用修改’后才更新正式规划。”
- “存在待应用预览时，下一轮反馈基于该预览继续修改；放弃预览恢复正式规划。”
- “保持现有批准文案原样使用的默认行为。” 文案拟写仅在用户显式允许时启用。
- 原有产品身份、事实准确、模块出场、套图一致性、最多一张完整静置图、平台规则、数量及规格限制继续生效。
- 每个已有任务保留 taskId；新增才分配新 ID；每个任务仍是一张图。
- 自定义参数继续开放：保留有序 key/value 列表和现有添加、删除、改名能力；模块预设不是参数名白名单。每轮对话及生成使用最新有效参数，未要求改动的自定义行保留。
- 会话按 workspace + project + hero/suite + regular/professional 隔离。
- 现有常规表单、专业描述式及反推描述式编译保持各自路径；项目反推本轮不接入对话。
- 修改当前草稿和应用版本不改写已提交生成批次，不删除生成结果。
- 沿用已绑定的规划提示词模型连接，不创建独立模型配置。
- 原型使用示例数据，不直接升级为正式代码；正式实现接入真实 API 和持久化。
- 两个仓库均有既有未提交改动。执行前记录当前差异，保留无关改动；本计划不自动提交 Git，也不切换现有分支。
- 计划编写阶段不运行数据库迁移、不重启服务、不调用付费模型。

## 实施顺序与交付

| 阶段 | 可验收交付 |
|---|---|
| 1 | 会话、轮次和已应用版本能够持久化并隔离 |
| 2 | 精确修改、累计差异及手动编辑冲突合并正确 |
| 3 | 真实规划模型支持续聊、澄清、失败恢复 |
| 4 | 常规表单附带新增的文案策略和视觉要求，现有规则保持 |
| 5 | 已应用方案正确进入编译及生成，历史批次保持原样 |
| 6 | 生产工作台中的规划大师弹窗接入 API，替换示例原型 |

前五阶段用接口和测试验收，第六阶段接通用户流程。每个阶段完成后检查本次差异及对应测试，再进入下一阶段。

## 文件职责

后端根目录：`C:/Users/jack/Desktop/item-zuizhong2/text-2-image`。

- 新建 `backend/app/application/planning_conversation_models.py`：请求/响应、修改操作及作用域类型。
- 新建 `backend/app/planning_conversation_repository.py`：Memory/Postgres 实现、幂等、revision CAS、应用版本事务。
- 新建 `backend/app/application/planning_conversation_patch.py`：应用操作、累计差异、三方合并；不调用模型。
- 新建 `backend/app/application/planning_conversation_planner.py`：将现有规则和当前有效方案组织成修改请求，复用模型连接。
- 新建 `backend/app/application/planning_conversation_service.py`：会话生命周期、轮次执行、校验、应用/放弃/恢复。
- 新建 `backend/app/routes/planning_conversations.py`：HTTP 参数、身份和后台执行入口。
- 新建 `alembic/versions/20261008_planning_conversations.py`：新增会话表，不改旧规则或生成记录。
- 小范围修改 `module_planning_service.py`、`module_planning_repository.py`、`main.py`：复用规则校验、隔离候选、服务注入。
- 小范围修改 `regular_design.py`、`batch_generation_service.py`、`suite_planning_service.py`、对应 routes：可选字段传递和已应用方案校验。

前端根目录：`C:/Users/jack/Desktop/item-zuizhong2/text-2-image-front`。

- 新建 `src/api/planning-conversations.ts`：类型及 API 调用，复用现有请求封装。
- 新建 `src/lib/planning-conversation.ts`：草稿与完整规划的有效快照转换、服务端差异映射。
- 新建 `src/hooks/usePlanningConversation.ts`：读取、同步、轮次轮询、应用及冲突状态。
- 新建 `src/features/planning/PlanningConversationDialog.tsx`、`PlanningConversationMessages.tsx`、`PlanningConversationPreview.tsx`、`planning-conversation.css`：弹窗、消息和两种模式的预览。
- 小范围修改 `HeroConfigPanel.tsx`、`SuiteConfigPanel.tsx`、`useModulePlanning.ts`、`planning-master.ts`、`generation-workspace.ts`、`useProjectStore.ts`、`HeroImageWorkspace.tsx`、`SuiteWorkspace.tsx`：入口、快照和编译失效。
- 最终移除本次 `PlanningChatPrototype.tsx`、`planning-chat-prototype.css` 以及 ProjectWorkbench/router 中的本次原型开关；保留其他已有原型。

---

## Task 1：持久化会话、轮次和版本

**Files:** 创建 models、repository、迁移；测试 `backend/tests/test_planning_conversation_repository.py`、`backend/tests/test_planning_conversation_postgres.py`、`backend/tests/test_planning_conversation_migration.py`。

**Interfaces:** 在 models 定义以下作用域；仓库所有读写都接收作用域，不依赖后台任务的隐式请求身份。

```python
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

@dataclass(frozen=True)
class ConversationScope:
    workspace_id: UUID
    project_id: UUID
    mode: Literal['hero', 'suite']
    creation_mode: Literal['regular', 'professional']
```

仓库接口：

```python
ensure_session(scope: ConversationScope, initial: dict) -> dict
get_session(scope: ConversationScope, session_id: UUID) -> dict | None
reserve_turn(scope: ConversationScope, session_id: UUID, key: str,
             fingerprint: str, expected_revision: int, document: dict
             ) -> tuple[dict, dict, bool]  # session, turn, owner
finish_turn(scope: ConversationScope, session_id: UUID, turn_id: UUID,
            token: UUID, result: dict) -> dict
sync_snapshot(scope: ConversationScope, session_id: UUID,
              expected_revision: int, snapshot: dict) -> dict
apply_version(scope: ConversationScope, session_id: UUID,
              expected_revision: int, plan_id: UUID, snapshot: dict,
              restored_from_version_id: UUID | None = None) -> dict
discard_preview(scope: ConversationScope, session_id: UUID,
                expected_revision: int) -> dict
list_turns(scope: ConversationScope, session_id: UUID,
           before: UUID | None, limit: int) -> dict
list_versions(scope: ConversationScope, session_id: UUID,
              before: UUID | None, limit: int) -> dict
```

- [x] 写 Memory 仓库的作用域隔离和幂等测试，先运行确认缺少接口导致失败。

```python
@pytest.mark.asyncio
async def test_modes_are_isolated_and_turn_replay_is_owned_once():
    scope = ConversationScope(uuid4(), uuid4(), 'suite', 'regular')
    repo = MemoryPlanningConversationRepository()
    session = await repo.ensure_session(scope, {'currentSnapshot': None})
    sid = UUID(session['id'])
    other = ConversationScope(scope.workspace_id, scope.project_id,
                              'suite', 'professional')
    assert await repo.get_session(other, sid) is None
    first = await repo.reserve_turn(scope, sid, 'feedback-1', 'a' * 64,
                                    session['revision'], {'text': '缩短标题'})
    replay = await repo.reserve_turn(scope, sid, 'feedback-1', 'a' * 64,
                                     session['revision'], {'text': '缩短标题'})
    assert first[2] is True and replay[2] is False
    assert first[1]['id'] == replay[1]['id']
```

- [x] 迁移新增 `project_workbench.planning_conversations`、`planning_conversation_turns`、`planning_conversation_versions`。
  - 会话：scope 唯一、revision 正整数、JSON document、创建/更新时间。
  - 轮次：session FK、`UNIQUE(session_id, request_key)`、fingerprint、状态、执行 token、JSON 冻结上下文、时间。
  - 版本：session FK、plan_id、版本序号、完整有效方案、恢复来源、创建时间；版本号在事务中递增。
  - project/session 删除使用 CASCADE；保持 workspace 外键和现有项目模型的约定。
  - down_revision 接实施时真实唯一 Alembic head；当前读取到的是 `20261007_reverse_analysis_token`，执行前用 `alembic heads` 再核对。
- [x] 用 `SELECT ... FOR UPDATE` 在短事务内检查 revision、写轮次和修改指针；模型调用在事务外。相同 key/fingerprint 的回放优先于 revision 检查，避免网络重试变成冲突；不同 fingerprint 返回 `IDEMPOTENCY_KEY_REUSED`。
- [x] 轮次只允许所属 token 完成；同一会话只允许一个 generating 轮次。保留正式指针和上一份有效预览直到新结果校验通过。
- [x] 增加 Postgres 回滚事务测试：重新创建仓库仍恢复全部状态；并发 reserve 仅一个 owner；错误 workspace 不可读取；删除测试项目清理三个新表；测试使用显式环境开关，与现有 DB 测试一致。
- [x] 验证迁移图与上述仓库测试。此阶段只写迁移文件，实际运行 upgrade 安排在联调前。

## Task 2：精确修改、累计差异、手动编辑合并

**Files:** 创建 `planning_conversation_patch.py`；补充 models；测试 `backend/tests/test_planning_conversation_patch.py`。

**Interfaces:** `EffectiveSnapshot` 是 `{plan: 完整规划文档, parameterOverrides: taskId到当前有效参数列表的映射, regularOptions: taskId到选项的映射}`。保留完整规划中未展示的字段，避免丢失设计指南、参考关联和风格元数据。`regularOptions` 为独立字段，不塞入当前只接受 goal/copy 的 regularTask。parameterOverrides 保存有序的完整有效参数列表，包含用户新增、删除或改名后的值；空编辑行可以存草稿，提交生成沿用当前过滤和校验行为。

当前编辑器最多 20 行，参数名最多 60 字符、值最多 500 字符；规划输出 schema 的自动参数最多 19 行，专业自动输出还禁止自动生成“构图要求”键。分别保留这两条既有路径：自动计划仍按旧 schema 验证，手动补充通过 parameterOverrides 传递，并按现有生成请求校验。不能把完整手动参数折叠进自动规划 schema，造成原来能填的自定义要求被误拒绝。

```python
apply_operations(base: dict, operations: list[dict]) -> dict
diff_snapshots(applied: dict, candidate: dict) -> list[dict]
merge_candidate(base: dict, current: dict, candidate: dict) -> dict
```

操作仅允许五类：`set_module(taskId, changes)`、`set_parameters(taskId, parameters)`、`add_module(module)`、`delete_module(taskId)`、`reorder(taskIds)`。字段白名单约束规划对象的可编辑字段及单独的 regularOptions，不限制用户参数名；set_parameters 更新 parameterOverrides 的有序列表。不可写规则、提示词模型连接、身份作用域、输入素材归属。新增 taskId 由服务端分配，模型不能覆盖已有身份。

- [x] 写测试验证只更新指定 task、顺序变化保留身份、删除不修改其他 task，以及三方合并。

```python
def test_unrelated_manual_edit_survives_application():
    base = {'plan': {'modules': [
        {'taskId': 'first', 'taskTitle': '首屏'},
        {'taskId': 'second', 'taskTitle': '细节'},
    ]}, 'parameterOverrides': {}, 'regularOptions': {}}
    candidate = apply_operations(base, [
        {'kind': 'set_module', 'taskId': 'second',
         'changes': {'taskTitle': '纹理细节'}}])
    current = deepcopy(base)
    current['plan']['modules'][0]['taskTitle'] = '我的首屏标题'
    result = merge_candidate(base, current, candidate)
    assert result['plan']['modules'][0]['taskTitle'] == '我的首屏标题'
    assert result['plan']['modules'][1]['taskTitle'] == '纹理细节'
    assert base['plan']['modules'][1]['taskTitle'] == '细节'
```

- [x] 按 taskId/字段做三方合并：候选没改的字段取 current；只有候选修改的取 candidate；双边修改相同值可合并；双边不同值返回 `PLANNING_EDIT_CONFLICT` 和具体字段。排序双边不一致、删除目标被手动编辑也属于冲突。
- [x] 不重写原始对象。对未知 taskId、重复 ID、缺漏 reorder ID、规则字段修改返回明确错误。新增任务使用 UUID 字符串，`resultCount` 固定 1。
- [x] 从 applied 到最新 candidate 计算累计差异，包含新增/删除/移动/字段修改。上一轮 candidate 是下一轮基底，但差异仍对 applied 计算。
- [x] 自定义参数逐项显示新增、删除、改值和改名；保留顺序、未知参数名及未触及的行。对同一参数双边不同修改提示冲突；重名或改名配对有歧义时提示用户处理，不静默覆盖或转成丢值的字典。
- [x] 增加同字段冲突、同类型两个独立 task、反复调整后改回原值的测试，确认累计差异不虚报。
- [x] 运行 `test_planning_conversation_patch.py`。完整模式和规则校验放在 Task 3，不能把本任务的字段合并当作完整合法性判定。

## Task 3：真实续聊、澄清与接口

**Files:** 创建 planner/service/routes；小改 `module_planning_service.py`、`module_planning_repository.py`、`main.py`；测试 `test_planning_conversation_service.py`、`test_planning_conversation_api.py`。

**Interfaces:** 在 models 用 Pydantic 定义下面的 wire 字段，`extra='forbid'`；snapshot 中 plan 按已有规划 schema 校验。

```text
BootstrapInput: mode, creationMode, input(ModulePlanInput), snapshot(EffectiveSnapshot|null)
SyncInput: expectedRevision, input(ModulePlanInput), snapshot(EffectiveSnapshot)
FeedbackInput: expectedRevision, text(1..4000), input(ModulePlanInput), snapshot(EffectiveSnapshot)
ApplyInput: expectedRevision, candidatePlanId, input(ModulePlanInput), snapshot(EffectiveSnapshot)
RestoreInput: expectedRevision, versionId, input(ModulePlanInput), snapshot(EffectiveSnapshot)
DiscardInput: expectedRevision

Reply: kind=clarification|revision, message, operations
clarification 必须 operations=[]；revision 必须有合法操作。
```

API 使用 `/api/projects/{project_id}/planning-conversations`：

| 方法/相对路径 | 行为 |
|---|---|
| GET `?mode=hero&creationMode=regular` | 读取当前会话，没有会话返回 data=null |
| POST `/bootstrap` | 导入当前有效规划；没有规划时以现有自动规划作为首轮 |
| POST `/{session_id}/sync` | 保存最新有效草稿；revision CAS |
| POST `/{session_id}/turns` | 校验并持久化轮次，202 返回 turn 和 session；要求 Idempotency-Key |
| GET `/{session_id}/turns/{turn_id}` | 恢复/轮询 generating、clarification、preview、failed、stale 状态 |
| GET `/{session_id}/messages?before=...&limit=20` | 消息分页，引用轮次持久化结果 |
| POST `/{session_id}/apply` | 合并并应用；返回完整正式 snapshot、planId、versionId 和 revision |
| POST `/{session_id}/discard` | 放弃待应用预览，不删除聊天 |
| GET `/{session_id}/versions?before=...&limit=20` | 历史应用版本 |
| POST `/{session_id}/restore` | 恢复旧版本为新应用版本，保留所有历史 |

- [x] 使用现有 `backend/tests/test_module_planning.py::fixture` 提供项目、素材、配置和假 planner；在本测试文件构造 `PlanningConversationService(repository, module_planning_service)`。

```python
@pytest.mark.asyncio
async def test_clarification_does_not_create_or_apply_a_plan():
    f = await fixture('suite')
    plan = await f.master_service.plan(f.project_id, f.input, 'initial')
    repo = MemoryPlanningConversationRepository()
    service = PlanningConversationService(repo, f.master_service)
    session = await service.bootstrap(f.project_id, {
        'mode': 'suite', 'creationMode': 'professional',
        'input': f.input.model_dump(mode='json'),
        'snapshot': {'plan': plan, 'parameterOverrides': {}, 'regularOptions': {}}})
    f.master.result = {'kind': 'clarification',
        'message': '更想改文案还是场景？', 'operations': []}
    submitted = await service.submit_turn(f.project_id, UUID(session['id']), {
        'expectedRevision': session['revision'], 'text': '不太满意',
        'input': f.input.model_dump(mode='json'),
        'snapshot': {'plan': plan, 'parameterOverrides': {}, 'regularOptions': {}}}, 'feedback')
    await service.run_turn(service.scope(f.project_id, 'suite', 'professional'),
                           UUID(session['id']), UUID(submitted['turn']['id']))
    current = await service.get(f.project_id, 'suite', 'professional')
    assert current['appliedPlanId'] == plan['id']
    assert current['pendingPlanId'] is None
```

- [x] 从现有规划服务提取最小的共享“加载规则与素材/验证完整输出”入口，保持普通规划输入时的 system/user 请求内容。新 planner 额外包装反馈、当前有效方案、最近对话和 Reply schema；不删除或重写旧规则。
- [x] 使用现有 `prompt_models.bind` 和 `ModuleMasterRequest`。保存模型连接、实际请求、素材 SHA256、规则配置版本、反馈基底和执行 token 的快照。
- [x] revision 回复先执行 patch，再复用现有 RegularOutput/MasterOutput、目录、素材归属、数量和产品出场校验。常规显式增删/排序后以候选任务列表作为本轮 selectedModules 再校验，保留普通自动填写固定选择的原行为。
- [x] 澄清问题只更新消息；revision 校验成功才替换 pending；失败保留 applied 与上一份 pending。与硬规则冲突时返回说明及合法调整方向，不生成可应用的非法预览。
- [x] 已完成候选规划记录 `origin='planning_conversation'`、sessionId、parentPlanId。旧 repository.latest 过滤此 origin；会话自行通过 applied 指针恢复，绝不自动选取最新候选。
- [x] FastAPI BackgroundTasks 只负责运行已持久化轮次，显式携带 scope。刷新只读同一轮次，不重新调用模型。执行超时沿用现有 540 秒；超时/重启失去执行者时将轮次标为 failed，重试必须是新操作。相同幂等 key 不重复计费。
- [x] candidate 完成时核对 token、基底和输入指纹；运行期间素材或草稿变化导致 stale，保留结果供对照但禁止直接应用。应用先完成三方合并及全量校验，再原子登记应用版本。
- [x] 补 API 的项目归属、跨模式、幂等冲突、stale revision、失败重试测试，以及“候选不出现在 latest”的回归。
- [x] 运行本任务测试和原 `test_module_planning.py`、`test_module_planning_v2.py`。不以真实模型调用作为结构正确性的测试门槛。

## Task 4：常规可选字段接入，原有规则与默认输出保持

**Files:** 修改 `regular_design.py`、batch/suite service 请求模型和对应 routes；前端修改 `generation-workspace.ts`、`api/client.ts`；测试 `test_regular_design.py`、`test_regular_mode.py`、新 `test_regular_conversation_options.py`。

**Interfaces:** 新增可选 `regularOptions`，与原 `regularTask={goal,copy}` 并列。前端配置按 taskId 保存 `regularTaskOptions`。

```typescript
export interface RegularTaskOptions {
  copyPolicy?: "fixed" | "flexible";
  visualRequirements?: string;
}
```

对应后端字段名为 `regular_options`，wire 用 `regularOptions`；缺省 copyPolicy=fixed、visualRequirements 空。每页选项由会话完整 snapshot.regularOptions 输出，编译请求映射到对应 task。

models 中定义同名 Pydantic `RegularTaskOptions`：`copyPolicy: Literal['fixed','flexible']='fixed'`、`visualRequirements: str=Field(default='',max_length=2000)`，extra='forbid'。这些是可选控制项，不代替开放的 moduleParameters。

- [x] 先捕获当前工作区的规则源文件 SHA256 和无新增选项的编译样本到测试 fixture：`regular_design.py`、`product_appearance.py`、`planning_skills.py`、`commerce_design.py`、`module_planning_v2.py`、实际规划技能及平台/风格规则。不要从 Git HEAD 取基线覆盖尚未提交的现有规则。
- [x] 写兼容测试：相同输入、没有 regularOptions 时 final prompt 与原样本逐字相同；有 fixed 选项时仍原样渲染文案；flexible 时明确品牌、数值和用户原文不可变；视觉要求只新增字段，不删除 moduleDirection、suiteConsistency 或 productAppearanceGuidance。

```python
def test_regular_options_default_is_fixed():
    assert RegularTaskOptions().copyPolicy == 'fixed'
    assert RegularTaskOptions(visualRequirements='不要人物').copyPolicy == 'fixed'

def test_options_reject_unrecognized_copy_policy():
    with pytest.raises(ValidationError):
        RegularTaskOptions(copyPolicy='ignore_product_facts')
```

- [x] 在原 local regular_snapshot 中仅新增有选项时的分支。fixed 沿用原 approvedCopy 语义；flexible 把文案标为基于事实的建议方向，并指定锁定信息优先。不要让同一请求同时要求“逐字渲染”及“自由改写”而互相矛盾。
- [x] 常规 UI 默认展示“按原文使用”，用户可以显式改为“允许拟写”。事实、品牌和参数始终锁定；将确认的指定原文保存为 fixed，下一轮未要求修改时保留。
- [x] 专业和反推路径不接收此选项。旧客户端缺少字段时行为不变；现有 regularTask 的 key 校验不放宽。
- [x] 运行原常规测试和新选项测试，检查规则源文本差异；除了可选字段的拼装分支，不改变任何已有规则内容。

## Task 5：应用版本进入生成，编译失效和历史安全

**Files:** 后端 `module_planning_service.py`、conversation service、batch/suite services；前端新 `planning-conversation.ts`、修改 `planning-master.ts`、`useProjectStore.ts`、`HeroImageWorkspace.tsx`、`SuiteWorkspace.tsx`；测试 `tests/planning-conversation.test.ts`、后端 `test_planning_conversation_generation.py`。

**Interfaces:**

```typescript
materializeEffectiveSnapshot(config: PlanningConfig, plan: ApiModulePlan): EffectiveSnapshot;
applyConversationSnapshot(config: PlanningConfig, snapshot: EffectiveSnapshot,
                          planId: string, appliedVersionId: string): PlanningConfig;
```

`CommonGenerationConfig` 新增可选 `planningConversationId`、`planningAppliedVersionId`、`regularTaskOptions`。服务端是合并和应用的权威；前端不独立实施另一套三方合并。

- [x] 写前端测试，将原规划和人工 taskDesign/参数/常规文案 overrides 转成有效 snapshot，确认上传的是实际显示值；完整隐藏元数据从原 plan 保留，当前全部参数放入 parameterOverrides。增加自定义“使用位置”“避免出现”键后，两轮仅改文案仍保留这些参数；用户要求修改参数后更新对应行。
- [x] 编写应用测试：服务端最终合并值进入新 baseline，明确要求改变的字段不被旧 override 盖回；其余手动值保留。清理已折叠进 baseline 的 override，清理被删除 task 的活跃配置，保留历史结果。

```typescript
test("effective snapshot contains current manual values", () => {
  const plan = regularPlanFixture();
  const config = normalizeSuiteConfig({
    creationMode: "regular", selectedModuleIds: ["detail"],
    moduleTypes: { detail: "suite-detail" },
    regularTasks: { detail: { goal: "展示按键", copy: "细节可见" } },
    regularTaskOverrides: { detail: { goal: "展示滚轮", copy: "滚轮细节" } },
  });
  const snapshot = materializeEffectiveSnapshot(config, plan);
  assert.equal(snapshot.plan.modules[0].reason, "展示滚轮");
  assert.equal(snapshot.plan.modules[0].suggestedCopy, "滚轮细节");
});
```

本测试文件定义 `regularPlanFixture()`：返回 completed 的 regular-design-v1、suite 模式、一个 taskId=detail/moduleId=suite-detail 的完整原规划，input 用 modulePlanRequestInput('suite', config) 生成，其余字段沿用现有 regular-planning 测试形状。

- [x] 新的 appliedVersionId 进入编译输入指纹。应用/恢复后标记活跃编译不可复用并分配新幂等键；历史 batch/plan IDs 继续留作结果读取。不要通过删除历史 generationSessions 或后端批次实现失效。
- [x] 后端 snapshot 获取会话候选时要求该 planId 已存在应用版本记录。仅生成预览的 candidate 返回 `MODULE_PLAN_NOT_APPLIED`；已应用的历史版本仍可用于原批次恢复/重试。
- [x] sync 与 apply 使用 expectedRevision/currentSnapshot；点击应用的短请求期间锁定本窗口编辑控件，响应后核对请求快照指纹，再更新本地草稿。其他窗口变化由 CAS 返回冲突，不能覆盖。
- [x] 新事实/产品图/风格变化后使旧预览不可应用，下一轮带最新输入；保留对话记录。版本恢复重新验证当前输入和规则，旧素材已删除时明确阻止恢复，不能自动替换产品。
- [x] 应用后将 parameterOverrides 回填现有 moduleParameters；编译直接使用当前 key/value 列表，常规表单把全部有效行带入 assignedProductFacts，专业路径继续使用已有参数通道。新增任意参数也参与草稿/编译指纹，不复用添加参数前的编译结果。
- [x] 保存完整历史有效快照，包括该版商品资料、素材、参数和输出配置。刷新无本地草稿时可恢复；有本地未同步草稿时保留并同步，不能用服务端旧值覆盖本机编辑。
- [x] 运行新 helper 测试及现有 planning-master/regular-planning、batch/suite 编译确认测试，验证候选不能生成、新批次使用已应用版本、旧批次快照不变。

## Task 6：生产弹窗接入与端到端验收

**Files:** 创建 frontend API/hook/features 文件；修改配置面板、useModulePlanning、两个 workspace；最终清理本次原型文件和路由开关；测试 `tests/e2e/planning-conversation.spec.ts`、`tests/planning-conversation-api.test.ts`。

**Interfaces:** `usePlanningConversation(projectId, mode, creationMode)` 暴露 `session, messages, pending, versions, loading, generating, applying, error, open, setOpen, sendFeedback, apply, discard, restore, sync`。sendFeedback 读取调用时的 store 草稿并 materialize，不使用过时闭包中的草稿。

- [x] 新 API 模块定义 Task 3 的类型和路径；从现有 client 导出可复用 request 封装，不复制错误处理/身份逻辑。为每次反馈保存 key 和 turnId，网络失败/刷新继续读同一轮次。
- [x] 在真实工作台左侧保留原有配置，点击规划按钮打开弹窗。初始未规划时展示商品资料并执行原自动规划；已有规划时进入续聊。两版共用窗口，关闭不取消模型执行或清空状态。
- [x] 从 B 版提取布局设计，重新实现生产组件：左侧正式/候选对比、右侧对话，顶部关闭、历史入口、应用/放弃操作。原型关键词模拟、示例回复和 A/C 切换不进入生产组件。
- [x] 常规卡片展示内容目标、事实、文案及 copyPolicy、可选视觉要求；专业卡片继续展示现有设计字段。字段差异来自服务器累计 diff，移动标记同时展示原/新顺序。
- [x] 弹窗使用 native dialog 或现有项目 Dialog 的焦点保护；验证 Escape、关闭后焦点返回、Tab 限制、移动尺寸和独立滚动。模型调用期间保持资料和已应用方案可见。
- [x] 编写接口 stub 的端到端测试，覆盖以下可操作路径：

```typescript
test("closing and reopening retains the unapplied preview", async ({ page }) => {
  await installPlanningConversationApiStub(page);
  await page.goto("/projects/planning-dialog-fixture?tab=suite");
  await page.getByRole("button", { name: "打开规划大师" }).click();
  await page.getByRole("textbox", { name: "规划修改意见" }).fill("第二张标题短一点");
  await page.getByRole("button", { name: "发送修改意见" }).click();
  await expect(page.getByRole("heading", { name: "修改预览", exact: true })).toBeVisible();
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "打开规划大师" }).click();
  await expect(page.getByRole("heading", { name: "修改预览", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "应用修改", exact: true }).click();
  await expect(page.getByRole("heading", { name: "当前规划", exact: true })).toBeVisible();
});
```

在同文件定义 `installPlanningConversationApiStub(page)`：复用现有 module-planning E2E 的项目、素材、发布配置数据；拦截上述 conversation API，维护 revision/正式指针/候选/轮次/版本状态，返回一次只改第二张的 Reply。刷新页面时测试 stub 保留服务端状态。

- [x] 再覆盖四个 scope 的恢复、预览多轮累计、澄清后补充回答、冲突反馈、人工编辑、版本恢复、模型失败/未知响应回放、没有候选时的旧编译流程。
- [x] 在本地 scratch 数据的 Postgres 测试通过后运行 Alembic upgrade；核对实际活跃任务，再用当前已有启动方式重启 API。检查 `/api/ready`，在正式项目中先做无付费的读取/恢复验证。
- [x] 从正式入口验证弹窗后移除本次 prototype route 字段/加载分支和原型文件；检查原 `/projects/{id}?tab=hero|suite` 无额外 query 即可使用。
- [ ] 用户实际模型验收使用一条明确反馈“仅缩短第二张标题，其余保持”，先检查输入、候选差异及应用后编译；用户未要求时不为验收自动触发生图。

## 验证命令

后端在 backend repo 工作目录设置一次路径，再执行对应阶段目标测试：

```powershell
$env:PYTHONPATH = (Get-Location).Path + ';' + (Join-Path (Get-Location).Path 'backend')
& D:/dev/python/python3.13.0/python.exe -m pytest backend/tests/test_planning_conversation_repository.py backend/tests/test_planning_conversation_patch.py backend/tests/test_planning_conversation_service.py backend/tests/test_planning_conversation_api.py backend/tests/test_planning_conversation_generation.py backend/tests/test_regular_conversation_options.py -q
& D:/dev/python/python3.13.0/python.exe -m pytest backend/tests/test_module_planning.py backend/tests/test_module_planning_v2.py backend/tests/test_regular_design.py backend/tests/test_regular_mode.py backend/tests/test_suite_planning_service.py backend/tests/test_suite_planning_v2.py backend/tests/test_batch_generation_compile_service.py backend/tests/test_batch_generation_confirm_service.py -q
git -c core.whitespace=cr-at-eol diff --check
```

DB rollback tests沿用显式开关，迁移只在 scratch 检查通过后执行。前端在 frontend repo：

```powershell
npm run typecheck
npx tsx --test tests/planning-conversation.test.ts tests/planning-conversation-api.test.ts tests/planning-master.test.ts tests/regular-planning.test.ts
npx playwright test tests/e2e/planning-conversation.spec.ts tests/e2e/module-planning.spec.ts tests/e2e/regular-workspace.spec.ts --workers=1
git diff --check
```

Playwright 使用现有独立 4177 服务，不同时启动多个相同端口的测试进程。正常浏览器人工验收使用现有 5173 前端。

## 完成标准

- 正式工作台常规/专业、主图/套图均可从按钮打开真实弹窗续聊。
- 每轮可以澄清或生成预览，未应用预览不进入生成输入，也不在刷新后自动应用。
- 输入包含实时商品资料及手动修改，未要求修改的字段和 taskId 保持；冲突有明确反馈。
- 应用、放弃、关闭、刷新、多轮预览和版本恢复语义一致，scope 不串数据。
- 常规表单扩展仅来自明确选项；原规则文本及旧输入默认输出保持。
- 新批次按最新已应用版本编译；旧批次、图片和重试快照保持。
- 既有相关测试与新增测试通过；真实模型的语义表现单独记录，不能用 mock 测试声称生图质量改善。

## 计划自检

- Spec coverage：初始规划、两版弹窗、增删排序、预览续聊、人工合并、上下文变化、历史恢复、scope、幂等与生成冻结均有对应任务。
- 自定义参数：预设不限制键名；Task 2 保留有序参数，Task 3 使用实时有效快照，Task 5 将最新值带入编译，Task 6 保留现有编辑能力。
- 状态：候选、当前草稿与已应用版本分别存储，最新候选不充当正式方案。
- 规则：Task 4 用当前工作区基线做默认行为回归；任何规则修改都不属于此计划。
- 原型：只沿用已选布局，生产组件用 API 重新实现，示例回复和布局切换不带入生产。
