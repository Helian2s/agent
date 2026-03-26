from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from .llm import TextGenerator
from .page_object_factory_nodes import build_page_object_factory_nodes
from .page_object_factory_state import PageObjectFactoryState


def build_page_object_factory_graph(
    text_generator: TextGenerator,
):
    nodes = build_page_object_factory_nodes(text_generator)

    def route_after_generation(state: PageObjectFactoryState) -> str:
        if state.get("run_status") == "failed":
            return "fail_page_object_factory"
        return "persist_page_object_manifest"

    builder = StateGraph(PageObjectFactoryState)
    builder.add_node("load_factory_context", nodes["load_factory_context"])
    builder.add_node("generate_page_objects", nodes["generate_page_objects"])
    builder.add_node("persist_page_object_manifest", nodes["persist_page_object_manifest"])
    builder.add_node("complete_page_object_factory", nodes["complete_page_object_factory"])
    builder.add_node("fail_page_object_factory", nodes["fail_page_object_factory"])

    builder.add_edge(START, "load_factory_context")
    builder.add_edge("load_factory_context", "generate_page_objects")
    builder.add_conditional_edges("generate_page_objects", route_after_generation)
    builder.add_edge("persist_page_object_manifest", "complete_page_object_factory")
    builder.add_edge("complete_page_object_factory", END)
    builder.add_edge("fail_page_object_factory", END)
    return builder.compile()
