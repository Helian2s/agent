from __future__ import annotations

import argparse
import json
from pathlib import Path

from .config import load_settings
from .graph import build_graph
from .llm import BedrockConverseTextGenerator
from .page_object_tracing import serialize_trace_value
from .page_object_workflow import build_page_object_graph


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Minimal LangGraph starter for Amazon Bedrock Converse."
    )
    parser.add_argument(
        "--prompt",
        help="Single user prompt to send to the graph. Falls back to the YAML default when omitted.",
    )
    parser.add_argument(
        "--html-input",
        help="Path to an HTML file that should be converted into a Python Selenium page object.",
    )
    parser.add_argument(
        "--page-object-output",
        help="Optional output path for the verified page object Python file.",
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=3,
        help="Maximum number of generate-and-fix attempts when producing a page object.",
    )
    parser.add_argument(
        "--trace-output",
        help="Optional path for writing detailed page-object workflow traces as JSON.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = load_settings()

    if args.html_input:
        text_generator = BedrockConverseTextGenerator(settings)
        graph = build_page_object_graph(text_generator)
        result = graph.invoke(
            {
                "html_path": args.html_input,
                "max_attempts": args.max_attempts,
            }
        )
        trace_events = serialize_trace_value(result.get("trace_events", []))

        if args.trace_output:
            trace_path = Path(args.trace_output)
            trace_path.parent.mkdir(parents=True, exist_ok=True)
            trace_path.write_text(json.dumps(trace_events, indent=2), encoding="utf-8")

        if result.get("run_status") == "failed":
            raise RuntimeError(
                str(result.get("failure_message", "Page object generation failed."))
            )

        page_object_code = result["final_page_object"]

        if args.page_object_output:
            output_path = Path(args.page_object_output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(page_object_code, encoding="utf-8")
            print(f"Wrote verified page object to {output_path}")
            if args.trace_output:
                print(f"Wrote workflow trace to {args.trace_output}")
        else:
            print(page_object_code)
        return

    graph = build_graph(settings)
    prompt = args.prompt or settings.default_user_prompt
    result = graph.invoke({"user_input": prompt})
    print(result["response_text"])


if __name__ == "__main__":
    main()
