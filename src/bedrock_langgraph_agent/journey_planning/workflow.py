from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Callable

from langgraph.graph import END, START, StateGraph

from .nodes import build_journey_nodes
from .state import JourneyPlanningState
from ..shared.workflow_tracing import utc_now


def build_journey_planning_graph(
    *,
    output_root: Path | None = None,
    now_provider: Callable[[], datetime] = utc_now,
):
    nodes = build_journey_nodes(output_root=output_root, now_provider=now_provider)

    def route_after_auth_decision(state: JourneyPlanningState) -> str:
        next_node = state.get("next_node")
        if next_node == "record_auth_checkpoint":
            return "record_auth_checkpoint"
        return "skip_auth_checkpoint"

    builder = StateGraph(JourneyPlanningState)
    builder.add_node("prepare_run_artifacts", nodes["prepare_run_artifacts"])
    builder.add_node("load_events", nodes["load_events"])
    builder.add_node("plan_journey", nodes["plan_journey"])
    builder.add_node("decide_auth_requirement", nodes["decide_auth_requirement"])
    builder.add_node("record_auth_checkpoint", nodes["record_auth_checkpoint"])
    builder.add_node("skip_auth_checkpoint", nodes["skip_auth_checkpoint"])
    builder.add_node("persist_journey_artifacts", nodes["persist_journey_artifacts"])
    builder.add_node("complete_journey_planning", nodes["complete_journey_planning"])

    builder.add_edge(START, "prepare_run_artifacts")
    builder.add_edge("prepare_run_artifacts", "load_events")
    builder.add_edge("load_events", "plan_journey")
    builder.add_edge("plan_journey", "decide_auth_requirement")
    builder.add_conditional_edges("decide_auth_requirement", route_after_auth_decision)
    builder.add_edge("record_auth_checkpoint", "persist_journey_artifacts")
    builder.add_edge("skip_auth_checkpoint", "persist_journey_artifacts")
    builder.add_edge("persist_journey_artifacts", "complete_journey_planning")
    builder.add_edge("complete_journey_planning", END)
    return builder.compile()
