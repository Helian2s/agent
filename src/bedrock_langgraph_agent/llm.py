from __future__ import annotations

from typing import Any, Protocol

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from .config import AppSettings


class TextGenerator(Protocol):
    def generate(self, *, system_prompt: str, user_prompt: str) -> str:
        """Return plain text output for the supplied prompts."""


class BedrockConverseTextGenerator:
    def __init__(self, settings: AppSettings):
        self._settings = settings

        session_kwargs: dict[str, str] = {}
        if settings.bedrock.profile:
            session_kwargs["profile_name"] = settings.bedrock.profile

        session = boto3.Session(region_name=settings.bedrock.region, **session_kwargs)
        self._bedrock_runtime = session.client("bedrock-runtime")

    def generate(self, *, system_prompt: str, user_prompt: str) -> str:
        try:
            response = self._bedrock_runtime.converse(
                modelId=self._settings.bedrock.model_id,
                system=[{"text": system_prompt}],
                messages=[
                    {
                        "role": "user",
                        "content": [{"text": user_prompt}],
                    }
                ],
                inferenceConfig={
                    "temperature": self._settings.bedrock.temperature,
                    "topP": self._settings.bedrock.top_p,
                    "maxTokens": self._settings.bedrock.max_tokens,
                },
            )
        except (BotoCoreError, ClientError) as exc:
            raise RuntimeError(
                "Amazon Bedrock Converse failed. Check AWS credentials, region, model access, and IAM permissions."
            ) from exc

        return extract_text(response)


def extract_text(response: dict[str, Any]) -> str:
    content_blocks = response.get("output", {}).get("message", {}).get("content", [])
    text_parts = [
        block["text"].strip()
        for block in content_blocks
        if isinstance(block, dict) and "text" in block and block["text"].strip()
    ]

    if not text_parts:
        raise RuntimeError("Bedrock returned no text content blocks.")

    return "\n".join(text_parts)
