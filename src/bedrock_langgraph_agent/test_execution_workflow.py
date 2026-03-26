from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from .llm import TextGenerator
from .test_execution_nodes import build_test_execution_nodes
from .test_execution_runner import GeneratedTestRunner
from .test_execution_state import TestExecutionState


def build_test_execution_graph(
    text_generator: TextGenerator,
    test_runner: GeneratedTestRunner,
):
    nodes = build_test_execution_nodes(text_generator, test_runner)

    def route_after_choice(state: TestExecutionState) -> str:
        next_node = state.get("next_node")
        if next_node == "repair_generated_test":
            return "repair_generated_test"
        return "persist_test_execution"

    def route_after_repair(state: TestExecutionState) -> str:
        if state.get("run_status") == "failed":
            return "persist_test_execution"
        return "execute_generated_test"

    def route_after_persist(state: TestExecutionState) -> str:
        if state.get("run_status") == "failed":
            return "fail_test_execution"
        return "complete_test_execution"

    builder = StateGraph(TestExecutionState)
    builder.add_node("load_test_execution_context", nodes["load_test_execution_context"])
    builder.add_node("execute_generated_test", nodes["execute_generated_test"])
    builder.add_node("choose_next_step", nodes["choose_next_step"])
    builder.add_node("repair_generated_test", nodes["repair_generated_test"])
    builder.add_node("persist_test_execution", nodes["persist_test_execution"])
    builder.add_node("complete_test_execution", nodes["complete_test_execution"])
    builder.add_node("fail_test_execution", nodes["fail_test_execution"])

    builder.add_edge(START, "load_test_execution_context")
    builder.add_edge("load_test_execution_context", "execute_generated_test")
    builder.add_edge("execute_generated_test", "choose_next_step")
    builder.add_conditional_edges("choose_next_step", route_after_choice)
    builder.add_conditional_edges("repair_generated_test", route_after_repair)
    builder.add_conditional_edges("persist_test_execution", route_after_persist)
    builder.add_edge("complete_test_execution", END)
    builder.add_edge("fail_test_execution", END)
    return builder.compile()
