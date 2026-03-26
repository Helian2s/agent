from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from bedrock_langgraph_agent.test_authoring.workflow import build_test_authoring_graph
from bedrock_langgraph_agent.test_execution.runner import TestRunResult
from bedrock_langgraph_agent.test_execution.workflow import build_test_execution_graph

from test_test_authoring_workflow import _create_verified_run


class StubTextGenerator:
    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)

    def generate(self, *, system_prompt: str, user_prompt: str) -> str:
        if not self._responses:
            raise AssertionError("No stub responses left.")
        return self._responses.pop(0)

    def get_trace_metadata(self) -> dict[str, str]:
        return {"provider": "bedrock", "modelId": "stub.model"}


class InspectingStubTestRunner:
    def __init__(self) -> None:
        self.seen_sources: list[str] = []

    def run(self, *, test_path: Path, run_root: Path) -> TestRunResult:
        source = test_path.read_text(encoding="utf-8")
        self.seen_sources.append(source)
        failed = "submit_order(" in source
        if failed:
            return TestRunResult(
                command=["python", "-m", "pytest", str(test_path)],
                exit_code=1,
                stdout="FAILED test_generated_journey\nE   AttributeError: 'CheckoutExamplePage' object has no attribute 'submit_order'\n",
                stderr="",
                duration_ms=12.5,
            )
        return TestRunResult(
            command=["python", "-m", "pytest", str(test_path)],
            exit_code=0,
            stdout=".                                                                        [100%]\n1 passed in 0.02s\n",
            stderr="",
            duration_ms=11.0,
        )


class EnvironmentFailureRunner:
    def run(self, *, test_path: Path, run_root: Path) -> TestRunResult:
        return TestRunResult(
            command=["python", "-m", "pytest", str(test_path)],
            exit_code=1,
            stdout="",
            stderr="/usr/bin/python: No module named pytest",
            duration_ms=2.0,
        )


class TestExecutionWorkflowTests(unittest.TestCase):
    def test_test_execution_succeeds_on_first_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            run_root = _create_verified_run(
                tmp_path,
                [
                    {
                        "timestamp": "2026-03-25T15:00:00Z",
                        "url": "https://shop.example.test/checkout",
                        "event_name": "page_view",
                        "auth_required": False,
                    }
                ],
            )
            build_test_authoring_graph().invoke({"run_root": str(run_root)})

            execution_graph = build_test_execution_graph(
                StubTextGenerator([]),
                InspectingStubTestRunner(),
            )
            result = execution_graph.invoke({"run_root": str(run_root), "max_attempts": 2})

            self.assertEqual(result["run_status"], "succeeded")
            self.assertEqual(len(result["execution_attempts"]), 1)
            self.assertTrue(Path(result["test_execution_report_path"]).exists())
            self.assertTrue(Path(result["test_execution_manifest_path"]).exists())

    def test_test_execution_repairs_generated_test_after_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            run_root = _create_verified_run(
                tmp_path,
                [
                    {
                        "timestamp": "2026-03-25T15:00:00Z",
                        "url": "https://shop.example.test/checkout",
                        "event_name": "page_view",
                        "auth_required": False,
                    }
                ],
            )
            authoring_result = build_test_authoring_graph().invoke({"run_root": str(run_root)})
            generated_test_path = Path(authoring_result["generated_test_path"])
            original_test_code = generated_test_path.read_text(encoding="utf-8")
            broken_test_code = original_test_code.replace(
                "page_1.click_place_order()",
                "page_1.submit_order()",
            )
            generated_test_path.write_text(broken_test_code, encoding="utf-8")

            runner = InspectingStubTestRunner()
            execution_graph = build_test_execution_graph(
                StubTextGenerator([original_test_code]),
                runner,
            )
            result = execution_graph.invoke({"run_root": str(run_root), "max_attempts": 2})

            self.assertEqual(result["run_status"], "succeeded")
            self.assertEqual(len(result["execution_attempts"]), 2)
            self.assertFalse(result["execution_attempts"][0].succeeded)
            self.assertTrue(result["execution_attempts"][1].succeeded)
            self.assertTrue(result["execution_attempts"][1].repaired)
            self.assertTrue(Path(result["execution_attempts"][1].repair_trace_path).exists())
            self.assertNotIn("submit_order(", generated_test_path.read_text(encoding="utf-8"))
            self.assertIn("submit_order(", runner.seen_sources[0])
            self.assertNotIn("submit_order(", runner.seen_sources[1])

    def test_test_execution_fails_fast_on_non_repairable_environment_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            run_root = _create_verified_run(
                tmp_path,
                [
                    {
                        "timestamp": "2026-03-25T15:00:00Z",
                        "url": "https://shop.example.test/checkout",
                        "event_name": "page_view",
                        "auth_required": False,
                    }
                ],
            )
            build_test_authoring_graph().invoke({"run_root": str(run_root)})

            execution_graph = build_test_execution_graph(
                StubTextGenerator([]),
                EnvironmentFailureRunner(),
            )
            result = execution_graph.invoke({"run_root": str(run_root), "max_attempts": 3})

            self.assertEqual(result["run_status"], "failed")
            self.assertEqual(len(result["execution_attempts"]), 1)
            self.assertIn("No module named pytest", result["failure_message"])
            self.assertTrue(Path(result["test_execution_report_path"]).exists())


if __name__ == "__main__":
    unittest.main()
