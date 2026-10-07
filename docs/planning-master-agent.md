# 规划大师 LangChain Agent

规划大师通过 `langchain.agents.create_agent` 和 `langchain_openai.ChatOpenAI`
执行。主图、套图的普通版和专业版共用该入口，页面与 API 输出结构保持现有契约。

## 输入与边界

- 专业版沿用主图／套图规划 Skill、设计知识、风格模板和平台约束。
- 普通版沿用轻量内容规划指令。
- 商品图、参考图按原顺序作为多模态消息传入，图片角色仍写在用户上下文中。
- 模型连接在每个请求中绑定，保留管理员选择的地址、模型和密钥；不共享对话状态。
- 本阶段 Agent 的工具列表为空，Skill 作为系统指令注入。框架替换本身不增加设计知识。

## 执行与校验

Agent 使用 Chat Completions 的 JSON object 模式，支持当前兼容网关。
保留缺省 assistant role、文本包装、Markdown JSON 和思考标签的响应适配。
业务层仍校验模块目录、任务标识、输出字段与商品事实约束。
SDK 重试关闭：普通版一次模型调用，专业版结构校验不通过时最多补一次纠正调用。
每次 Agent 执行设定递归上限，返回工具调用或无效响应会被拒绝。

规划仍由现有仓库存储，并沿用请求幂等机制。快照新增 `planningEngine`，记录
`langchain/create_agent`、工具列表及 SDK 重试设置，原模型连接、输入与纠正记录继续保留。
LangGraph 作为 LangChain Agent 的运行时依赖安装；全项目的任务队列、图片生成和
持久化流程继续由现有业务服务负责。

## 本地验证

```powershell
python -m pip install -e '.[dev]'
python -m pytest backend/tests/test_planning_agent.py backend/tests/test_module_planning.py backend/tests/test_prompt_compiler_provider.py backend/tests/test_regular_mode.py backend/tests/test_generation_model_connections.py -q
```

测试运行实际 Agent，并只在 HTTP 边界模拟模型响应，无需消耗线上模型额度。
