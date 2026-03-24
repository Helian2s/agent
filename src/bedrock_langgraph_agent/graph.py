from __future__ import annotations

from typing import Any, TypedDict

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from langgraph.graph import END, START, StateGraph

from .config import AppSettings


class AgentState(TypedDict, total=False):
    user_input: str
    response_text: str


def build_graph(settings: AppSettings):
    session_kwargs: dict[str, str] = {}
    if settings.bedrock.profile:
        session_kwargs["profile_name"] = settings.bedrock.profile

    session = boto3.Session(region_name=settings.bedrock.region, **session_kwargs)
    bedrock_runtime = session.client("bedrock-runtime")

    def call_bedrock(state: AgentState) -> AgentState:
        prompt = state.get("user_input", "").strip()
        if not prompt:
            raise ValueError("The graph requires a non-empty `user_input` value.")

        try:
            response = bedrock_runtime.converse(
                modelId=settings.bedrock.model_id,
                system=[{"text": settings.bedrock.system_prompt}],
                messages=[
                    {
                        "role": "user",
                        "content": [{"text": prompt}],
                    }
                ],
                inferenceConfig={
                    "temperature": settings.bedrock.temperature,
                    "topP": settings.bedrock.top_p,
                    "maxTokens": settings.bedrock.max_tokens,
                },
            )
        except (BotoCoreError, ClientError) as exc:
            raise RuntimeError(
                "Amazon Bedrock Converse failed. Check AWS credentials, region, model access, and IAM permissions."
            ) from exc

        return {"response_text": _extract_text(response)}

    builder = StateGraph(AgentState)
    builder.add_node("call_bedrock", call_bedrock)
    builder.add_edge(START, "call_bedrock")
    builder.add_edge("call_bedrock", END)
    return builder.compile()


def _extract_text(response: dict[str, Any]) -> str:
    content_blocks = response.get("output", {}).get("message", {}).get("content", [])
    text_parts = [
        block["text"].strip()
        for block in content_blocks
        if isinstance(block, dict) and "text" in block and block["text"].strip()
    ]

    if not text_parts:
        raise RuntimeError("Bedrock returned no text content blocks.")

    return "\n".join(text_parts)
