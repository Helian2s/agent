from __future__ import annotations

from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from .config import AppSettings
from .llm import BedrockConverseTextGenerator


class AgentState(TypedDict, total=False):
    user_input: str
    response_text: str


def build_graph(settings: AppSettings):
    text_generator = BedrockConverseTextGenerator(settings)

    def call_bedrock(state: AgentState) -> AgentState:
        prompt = state.get("user_input", "").strip()
        if not prompt:
            raise ValueError("The graph requires a non-empty `user_input` value.")

        return {
            "response_text": text_generator.generate(
                system_prompt=settings.bedrock.system_prompt,
                user_prompt=prompt,
            )
        }

    builder = StateGraph(AgentState)
    builder.add_node("call_bedrock", call_bedrock)
    builder.add_edge(START, "call_bedrock")
    builder.add_edge("call_bedrock", END)
    return builder.compile()
