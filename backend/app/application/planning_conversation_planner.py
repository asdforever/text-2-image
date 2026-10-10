"""Reuse the exact existing rule/material preparation without a planning call."""
import json
from .module_planning_service import ModuleMasterRequest
from .planning_conversation_models import Reply

class PlanningConversationPlanner:
    def __init__(self, module_service):
        self.module = module_service

    async def prepare(self, project, payload, base, text, messages, workspace_id=None):
        frozen = {}
        planner, request, catalog = await self.module._execute(project, payload, frozen, prepare_only=True, workspace_id=workspace_id)
        context = json.loads(request.user_prompt)
        context.update(currentEffectiveSnapshot=base, feedback=text, recentConversation=messages,
                       outputSchema=Reply.model_json_schema(), conversationInstructions=(
                           '每轮保留未要求修改的内容、taskId 和自定义参数。常规版 copyPolicy 未设置时默认为 flexible，'
                           '允许根据已提供参数组织参考文案；只有 copyPolicy=fixed 时保持锁定文案原样。'
                           '本图最新补充参数优先于旧规划关于缺失信息的假设，不得虚构事实或承诺。'
                           '提问、解释、比较、建议和讨论返回 answer 和空 operations，只回答，不修改方案或新增图片。'
                           '结合当前有效方案和最近对话回答，可提出建议，但建议本身不代表用户同意修改。'
                           '例如“为什么第二张这样安排”“能只展示糖粒吗”“你觉得怎么更合理”都是讨论。'
                           '“这里面应该有不展示商品整体，只展示糖的那种吧”应先说明当前方案是否包含这种画面及适用方式，不直接增加页面。'
                           '只有明确要求执行修改才返回 revision 和最小操作，例如“请增加一张只展示糖粒的图”“按这个建议修改第二张”。'
                           '“能帮我把第二张标题缩短吗”虽是问句，但明确请求执行修改，可以返回 revision。不要仅凭问号或关键词判断意图。'
                           '意图或修改范围不明确时返回 clarification 和空 operations，等待确认。回答仅依据已有商品资料与方案，不虚构事实。'
                           '操作 kind: set_plan(changes), set_module(taskId,changes), set_parameters(taskId,parameters), '
                           'add_module(module: 完整模块但不得含 taskId), delete_module(taskId), reorder(taskIds)。'
                           '遵守原有全部规则，不生成非法候选。'))
        user = json.dumps(context, ensure_ascii=False)
        system = request.system_prompt + '\n\nconversationReply 输出契约：当前调用是连续规划对话。保留上述商品事实、视觉、平台及数量规则；本轮输出遵循以下 Reply JSON schema，采用 answer、clarification 或 revision，不输出完整 MasterOutput/RegularOutput。先判断用户是在提问讨论还是明确请求执行修改；讨论返回 answer，仅回复文字且 operations 为空，不创建修改方案；不明确时先澄清。taskDesignOverrides 中用户明确的 productPresence=auto 是当前有效设计选择，未要求修改时必须保留；该选择不替换自动规划的具体出场字段。\n' + json.dumps(Reply.model_json_schema(), ensure_ascii=False)
        frozen['snapshot']['systemPrompt'] = system
        frozen['snapshot']['userPrompt'] = user
        return planner, ModuleMasterRequest(system, user, request.image_inputs, request.image_mime_types), frozen['snapshot'], catalog
