from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from .llm import TextGenerator
from .page_object_nodes import build_page_object_nodes
from .page_object_policy import DEFAULT_PAGE_OBJECT_POLICY, PageObjectGenerationPolicy
from .page_object_state import PageObjectState


def build_page_object_graph(
    text_generator: TextGenerator,
    policy: PageObjectGenerationPolicy = DEFAULT_PAGE_OBJECT_POLICY,
):
    nodes = build_page_object_nodes(text_generator, policy)

    def route_after_choice(state: PageObjectState) -> str:
        next_node = state.get("next_node")
        if next_node == "complete_page_object":
            return "complete_page_object"
        if next_node == "fail_generation":
            return "fail_generation"
        return "generate_page_object"

    builder = StateGraph(PageObjectState)
    builder.add_node("plan_page_object", nodes["plan_page_object"])
    builder.add_node("generate_page_object", nodes["generate_page_object"])
    builder.add_node("verify_generated_page_object", nodes["verify_generated_page_object"])
    builder.add_node("choose_next_step", nodes["choose_next_step"])
    builder.add_node("complete_page_object", nodes["complete_page_object"])
    builder.add_node("fail_generation", nodes["fail_generation"])
    builder.add_edge(START, "plan_page_object")
    builder.add_edge("plan_page_object", "generate_page_object")
    builder.add_edge("generate_page_object", "verify_generated_page_object")
    builder.add_edge("verify_generated_page_object", "choose_next_step")
    builder.add_conditional_edges("choose_next_step", route_after_choice)
    builder.add_edge("complete_page_object", END)
    builder.add_edge("fail_generation", END)
    return builder.compile()
