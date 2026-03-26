from __future__ import annotations

import argparse
from pathlib import Path
import sys

from .config import load_settings
from .graph import build_graph
from .journey_workflow import build_journey_planning_graph
from .llm import BedrockConverseTextGenerator
from .page_capture_workflow import build_page_capture_graph
from .page_object_factory_workflow import build_page_object_factory_graph
from .page_object_runtime_workflow import build_page_object_runtime_graph
from .page_object_tracing import (
    resolve_trace_log_path,
)
from .page_object_workflow import build_page_object_graph
from .test_authoring_workflow import build_test_authoring_graph
from .test_execution_runner import PytestCommandRunner
from .test_execution_workflow import build_test_execution_graph
from .workflow_tracing import serialize_trace_value, write_trace_log


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
        "--journey-events",
        help="Path to an NDJSON file containing one captured website journey for deterministic planning.",
    )
    parser.add_argument(
        "--capture-run",
        help="Path to an existing run directory whose journey artifacts should be captured with Selenium.",
    )
    parser.add_argument(
        "--generate-page-objects-run",
        help="Path to an existing run directory whose captured page snapshots should be turned into verified page objects.",
    )
    parser.add_argument(
        "--verify-page-objects-run",
        help="Path to an existing run directory whose generated page objects should be verified against captured snapshots and repaired if needed.",
    )
    parser.add_argument(
        "--generate-tests-run",
        help="Path to an existing run directory whose verified page objects should be turned into a pytest Selenium test.",
    )
    parser.add_argument(
        "--execute-tests-run",
        help="Path to an existing run directory whose generated pytest Selenium test should be executed and repaired if needed.",
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

    if args.journey_events:
        graph = build_journey_planning_graph()
        result = graph.invoke({"journey_events_path": args.journey_events})
        run_directories = result["run_directories"]
        write_trace_log(
            serialize_trace_value(result.get("trace_events", [])),
            run_directories.journey_trace_path,
        )

        print(f"Created run output at {run_directories.run_root}")
        print(f"Wrote journey spec to {result['journey_spec_path']}")
        print(f"Wrote normalized events to {result['normalized_events_path']}")
        print(f"Auth checkpoint status: {result['auth_checkpoint_status']}")
        print(f"Wrote journey trace to {run_directories.journey_trace_path}", file=sys.stderr)
        return

    if args.capture_run:
        from .page_capture_browser import SeleniumChromeBrowserSession

        browser_session = SeleniumChromeBrowserSession()
        try:
            graph = build_page_capture_graph(browser_session)
            result = graph.invoke({"run_root": args.capture_run})
        finally:
            browser_session.close()

        run_directories = result["run_directories"]
        write_trace_log(
            serialize_trace_value(result.get("trace_events", [])),
            run_directories.page_capture_trace_path,
        )

        print(f"Captured pages into {run_directories.pages_dir}")
        print(f"Wrote page capture manifest to {result['page_capture_manifest_path']}")
        print(f"Auth session status: {result['auth_session_status']}")
        print(f"Wrote page capture trace to {run_directories.page_capture_trace_path}", file=sys.stderr)
        return

    if args.generate_page_objects_run:
        settings = load_settings()
        text_generator = BedrockConverseTextGenerator(settings)
        graph = build_page_object_factory_graph(text_generator)
        result = graph.invoke(
            {
                "run_root": args.generate_page_objects_run,
                "max_attempts": args.max_attempts,
            }
        )
        run_directories = result["run_directories"]
        write_trace_log(
            serialize_trace_value(result.get("trace_events", [])),
            run_directories.page_object_factory_trace_path,
        )

        if result.get("run_status") == "failed":
            raise RuntimeError(
                f"{result.get('failure_message', 'Page object factory failed.')}\n"
                f"Trace log: {run_directories.page_object_factory_trace_path}"
            )

        print(f"Generated page objects into {run_directories.page_objects_dir}")
        print(f"Wrote page object manifest to {result['page_object_manifest_path']}")
        print(
            f"Wrote page object factory trace to {run_directories.page_object_factory_trace_path}",
            file=sys.stderr,
        )
        return

    if args.verify_page_objects_run:
        from .page_capture_browser import SeleniumChromeBrowserSession

        settings = load_settings()
        text_generator = BedrockConverseTextGenerator(settings)
        browser_session = SeleniumChromeBrowserSession()
        try:
            graph = build_page_object_runtime_graph(text_generator, browser_session)
            result = graph.invoke(
                {
                    "run_root": args.verify_page_objects_run,
                    "max_attempts": args.max_attempts,
                }
            )
        finally:
            browser_session.close()

        run_directories = result["run_directories"]
        write_trace_log(
            serialize_trace_value(result.get("trace_events", [])),
            run_directories.page_object_runtime_verification_trace_path,
        )

        if result.get("run_status") == "failed":
            raise RuntimeError(
                f"{result.get('failure_message', 'Runtime page object verification failed.')}\n"
                f"Trace log: {run_directories.page_object_runtime_verification_trace_path}"
            )

        print(f"Verified page objects in {run_directories.page_objects_dir}")
        print(
            f"Wrote runtime verification manifest to {result['runtime_verification_manifest_path']}"
        )
        print(
            "Wrote runtime verification trace to "
            f"{run_directories.page_object_runtime_verification_trace_path}",
            file=sys.stderr,
        )
        return

    if args.generate_tests_run:
        graph = build_test_authoring_graph()
        result = graph.invoke({"run_root": args.generate_tests_run})
        run_directories = result["run_directories"]
        write_trace_log(
            serialize_trace_value(result.get("trace_events", [])),
            run_directories.test_authoring_trace_path,
        )

        if result.get("run_status") == "failed":
            raise RuntimeError(
                f"{result.get('failure_message', 'Generated test authoring failed.')}\n"
                f"Trace log: {run_directories.test_authoring_trace_path}"
            )

        print(f"Generated tests into {run_directories.tests_dir}")
        print(f"Wrote generated test to {result['generated_test_path']}")
        print(f"Wrote test authoring manifest to {result['test_authoring_manifest_path']}")
        print(
            f"Wrote test authoring trace to {run_directories.test_authoring_trace_path}",
            file=sys.stderr,
        )
        return

    if args.execute_tests_run:
        settings = load_settings()
        text_generator = BedrockConverseTextGenerator(settings)
        test_runner = PytestCommandRunner()
        graph = build_test_execution_graph(text_generator, test_runner)
        result = graph.invoke(
            {
                "run_root": args.execute_tests_run,
                "max_attempts": args.max_attempts,
            }
        )
        run_directories = result["run_directories"]
        write_trace_log(
            serialize_trace_value(result.get("trace_events", [])),
            run_directories.test_execution_trace_path,
        )

        if result.get("run_status") == "failed":
            raise RuntimeError(
                f"{result.get('failure_message', 'Generated test execution failed.')}\n"
                f"Trace log: {run_directories.test_execution_trace_path}"
            )

        print(f"Executed generated tests in {run_directories.tests_dir}")
        print(f"Wrote test execution report to {result['test_execution_report_path']}")
        print(f"Wrote test execution manifest to {result['test_execution_manifest_path']}")
        print(
            f"Wrote test execution trace to {run_directories.test_execution_trace_path}",
            file=sys.stderr,
        )
        return

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
