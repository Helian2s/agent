from __future__ import annotations

import argparse
from pathlib import Path
import sys

from .config import load_settings
from .graph import build_graph
from .llm import BedrockConverseTextGenerator
from .page_object_tracing import (
    resolve_trace_log_path,
    serialize_trace_value,
    write_trace_log,
)
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
        trace_path = resolve_trace_log_path(
            html_path=args.html_input,
            trace_output=args.trace_output,
            run_status=str(result.get("run_status", "unknown")),
        )
        write_trace_log(trace_events, trace_path)

        if result.get("run_status") == "failed":
            raise RuntimeError(
                f"{result.get('failure_message', 'Page object generation failed.')}\n"
                f"Trace log: {trace_path}"
            )

        page_object_code = result["final_page_object"]

        if args.page_object_output:
            output_path = Path(args.page_object_output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(page_object_code, encoding="utf-8")
            print(f"Wrote verified page object to {output_path}")
        else:
            print(page_object_code)
        print(f"Wrote workflow trace to {trace_path}", file=sys.stderr)
        return

    graph = build_graph(settings)
    prompt = args.prompt or settings.default_user_prompt
    result = graph.invoke({"user_input": prompt})
    print(result["response_text"])


if __name__ == "__main__":
    main()
