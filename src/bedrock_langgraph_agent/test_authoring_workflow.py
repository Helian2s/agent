from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from .test_authoring_nodes import build_test_authoring_nodes
from .test_authoring_state import TestAuthoringState


def build_test_authoring_graph():
    nodes = build_test_authoring_nodes()

    def route_after_plan(state: TestAuthoringState) -> str:
        if state.get("run_status") == "failed":
            return "fail_test_authoring"
        return "render_test_module"

    def route_after_verification(state: TestAuthoringState) -> str:
        if state.get("run_status") == "failed":
            return "fail_test_authoring"
        return "persist_test_artifacts"

    def route_after_render(state: TestAuthoringState) -> str:
        if state.get("run_status") == "failed":
            return "fail_test_authoring"
        return "verify_test_module"

    builder = StateGraph(TestAuthoringState)
    builder.add_node("load_test_authoring_context", nodes["load_test_authoring_context"])
    builder.add_node("build_test_plan", nodes["build_test_plan"])
    builder.add_node("render_test_module", nodes["render_test_module"])
    builder.add_node("verify_test_module", nodes["verify_test_module"])
    builder.add_node("persist_test_artifacts", nodes["persist_test_artifacts"])
    builder.add_node("complete_test_authoring", nodes["complete_test_authoring"])
    builder.add_node("fail_test_authoring", nodes["fail_test_authoring"])

    builder.add_edge(START, "load_test_authoring_context")
    builder.add_edge("load_test_authoring_context", "build_test_plan")
    builder.add_conditional_edges("build_test_plan", route_after_plan)
    builder.add_conditional_edges("render_test_module", route_after_render)
    builder.add_conditional_edges("verify_test_module", route_after_verification)
    builder.add_edge("persist_test_artifacts", "complete_test_authoring")
    builder.add_edge("complete_test_authoring", END)
    builder.add_edge("fail_test_authoring", END)
    return builder.compile()
