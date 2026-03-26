from __future__ import annotations

from .browser import BrowserSession
from .nodes import LoginHandler, build_page_capture_nodes
from .state import PageCaptureState

from langgraph.graph import END, START, StateGraph


def build_page_capture_graph(
    browser_session: BrowserSession,
    *,
    login_handler: LoginHandler | None = None,
):
    nodes = build_page_capture_nodes(
        browser_session,
        login_handler=login_handler,
    )

    builder = StateGraph(PageCaptureState)
    builder.add_node("load_capture_context", nodes["load_capture_context"])
    builder.add_node("maybe_authenticate_session", nodes["maybe_authenticate_session"])
    builder.add_node("capture_pages", nodes["capture_pages"])
    builder.add_node("persist_capture_manifest", nodes["persist_capture_manifest"])
    builder.add_node("complete_page_capture", nodes["complete_page_capture"])

    builder.add_edge(START, "load_capture_context")
    builder.add_edge("load_capture_context", "maybe_authenticate_session")
    builder.add_edge("maybe_authenticate_session", "capture_pages")
    builder.add_edge("capture_pages", "persist_capture_manifest")
    builder.add_edge("persist_capture_manifest", "complete_page_capture")
    builder.add_edge("complete_page_capture", END)
    return builder.compile()
