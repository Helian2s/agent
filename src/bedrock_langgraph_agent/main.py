from __future__ import annotations

import argparse

from .config import load_settings
from .graph import build_graph


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Minimal LangGraph starter for Amazon Bedrock Converse."
    )
    parser.add_argument(
        "--prompt",
        help="Single user prompt to send to the graph. Falls back to the YAML default when omitted.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = load_settings()
    graph = build_graph(settings)

    prompt = args.prompt or settings.default_user_prompt
    result = graph.invoke({"user_input": prompt})
    print(result["response_text"])


if __name__ == "__main__":
    main()
