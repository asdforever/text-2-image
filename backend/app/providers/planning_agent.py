"""Bounded, task-local LangChain runtime for the commerce planning master."""
from typing import Any

import httpx
from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage
from langchain_openai import ChatOpenAI
from openai import BaseModel


class _CompatiblePlanningChat(ChatOpenAI):
    def _create_chat_result(self, response, generation_info=None):
        # Legacy compatible gateways omit the assistant role in completion choices.
        # Normalize only that envelope field; the model output still gets validated.
        if isinstance(response, BaseModel):
            response = response.model_dump(warnings=False)
        if isinstance(response, dict) and isinstance(response.get("choices"), list):
            for choice in response["choices"]:
                message = choice.get("message") if isinstance(choice, dict) else None
                if isinstance(message, dict) and message.get("role") is None:
                    message["role"] = "assistant"
        return super()._create_chat_result(response, generation_info)


def planning_engine_snapshot() -> dict[str, Any]:
    return {
        "framework": "langchain", "factory": "create_agent",
        "tools": [], "sdkMaxRetries": 0,
    }


async def run_planning_agent(
    *, base_url: str, api_key: str, model: str, timeout_ms: int,
    system_prompt: str, content: list[dict[str, Any]],
    transport: httpx.AsyncBaseTransport | None = None,
) -> str | list:
    # Business validation owns correction attempts; SDK retries would multiply calls.
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(timeout_ms / 1000), transport=transport,
    ) as client:
        chat = _CompatiblePlanningChat(
            model=model, base_url=base_url, api_key=api_key,
            temperature=0, timeout=timeout_ms / 1000, max_retries=0,
            http_async_client=client, use_responses_api=False,
            http_socket_options=(),
            model_kwargs={"response_format": {"type": "json_object"}},
        )
        # Existing Skills and output schemas are carried in the prompts. JSON mode
        # also works with gateways that do not support structured-output tool calls.
        agent = create_agent(
            model=chat, tools=[], system_prompt=system_prompt,
            name="commerce_planning_master",
        )
        result = await agent.ainvoke(
            {"messages": [HumanMessage(content=content)]},
            config={"recursion_limit": 4},
        )
        message = result["messages"][-1]
        if not isinstance(message, AIMessage) or message.tool_calls:
            raise ValueError("planning agent must return a final assistant message")
        return message.content
