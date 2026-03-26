from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from .llm import TextGenerator
from .page_capture_browser import BrowserSession
from .page_object_runtime_nodes import build_page_object_runtime_nodes
from .page_object_runtime_state import PageObjectRuntimeState


def build_page_object_runtime_graph(
    text_generator: TextGenerator,
    browser_session: BrowserSession,
):
    nodes = build_page_object_runtime_nodes(text_generator, browser_session)

    def route_after_verification(state: PageObjectRuntimeState) -> str:
        if state.get("run_status") == "failed":
            return "fail_runtime_verification"
        return "persist_runtime_manifest"

    builder = StateGraph(PageObjectRuntimeState)
    builder.add_node("load_runtime_context", nodes["load_runtime_context"])
    builder.add_node("verify_and_repair_page_objects", nodes["verify_and_repair_page_objects"])
    builder.add_node("persist_runtime_manifest", nodes["persist_runtime_manifest"])
    builder.add_node("complete_runtime_verification", nodes["complete_runtime_verification"])
    builder.add_node("fail_runtime_verification", nodes["fail_runtime_verification"])

    builder.add_edge(START, "load_runtime_context")
    builder.add_edge("load_runtime_context", "verify_and_repair_page_objects")
    builder.add_conditional_edges("verify_and_repair_page_objects", route_after_verification)
    builder.add_edge("persist_runtime_manifest", "complete_runtime_verification")
    builder.add_edge("complete_runtime_verification", END)
    builder.add_edge("fail_runtime_verification", END)
    return builder.compile()
