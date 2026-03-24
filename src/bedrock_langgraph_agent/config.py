from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import os

import yaml
from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class BedrockSettings:
    region: str
    profile: str | None
    model_id: str
    system_prompt: str
    temperature: float
    top_p: float
    max_tokens: int


@dataclass(frozen=True)
class AppSettings:
    config_path: Path
    default_user_prompt: str
    bedrock: BedrockSettings


def load_settings(project_root: Path | None = None) -> AppSettings:
    root = project_root or PROJECT_ROOT
    load_dotenv(root / ".env", override=False)

    config_path = _resolve_config_path(root)
    raw_config = _load_yaml(config_path)

    app_config = raw_config.get("app", {})
    bedrock_config = raw_config.get("bedrock", {})

    region = os.getenv("AWS_REGION") or str(bedrock_config.get("region", "")).strip()
    if not region:
        raise ValueError("Set AWS_REGION in `.env` or `bedrock.region` in the YAML config.")

    model_id = str(bedrock_config.get("model_id", "")).strip()
    if not model_id:
        raise ValueError("Set `bedrock.model_id` in the YAML config.")

    system_prompt = str(
        bedrock_config.get(
            "system_prompt",
            "You are a concise assistant used in a LangGraph Bedrock demo.",
        )
    ).strip()

    return AppSettings(
        config_path=config_path,
        default_user_prompt=str(
            app_config.get(
                "default_user_prompt",
                "Say hello from LangGraph using Amazon Bedrock.",
            )
        ).strip(),
        bedrock=BedrockSettings(
            region=region,
            profile=os.getenv("AWS_PROFILE", "").strip() or None,
            model_id=model_id,
            system_prompt=system_prompt,
            temperature=float(bedrock_config.get("temperature", 0.0)),
            top_p=float(bedrock_config.get("top_p", 0.9)),
            max_tokens=int(bedrock_config.get("max_tokens", 256)),
        ),
    )


def _resolve_config_path(project_root: Path) -> Path:
    configured_path = os.getenv("AGENT_CONFIG_PATH")
    if configured_path:
        candidate = Path(configured_path)
    else:
        local_config = project_root / "config" / "agent.local.yaml"
        candidate = local_config if local_config.exists() else project_root / "config" / "agent.example.yaml"

    if not candidate.is_absolute():
        candidate = project_root / candidate

    if not candidate.exists():
        raise FileNotFoundError(f"Config file not found: {candidate}")

    return candidate


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}

    if not isinstance(data, dict):
        raise ValueError(f"Expected a mapping in config file: {path}")

    return data
