"""Identifier generation utilities."""

from __future__ import annotations

from collections.abc import Callable
from uuid import uuid4

IdFactory = Callable[[], str]

_PREFIXES: dict[str, str] = {
    "place": "plc",
    "alias": "als",
    "graph_ref": "grf",
    "asset": "ast",
    "inspection_profile": "ipr",
    "approval_profile": "apr",
    "task": "tsk",
    "task_step": "stp",
    "observation": "obs",
    "condition_result": "cdr",
    "operator_event": "evt",
}


def generate_id(prefix: str) -> str:
    """Return a compact, stable-looking identifier with a type prefix."""

    return f"{prefix}_{uuid4().hex}"


def _factory(key: str) -> IdFactory:
    prefix = _PREFIXES[key]
    return lambda: generate_id(prefix)


generate_place_id = _factory("place")
generate_alias_id = _factory("alias")
generate_graph_ref_id = _factory("graph_ref")
generate_asset_id = _factory("asset")
generate_inspection_profile_id = _factory("inspection_profile")
generate_approval_profile_id = _factory("approval_profile")
generate_task_id = _factory("task")
generate_step_id = _factory("task_step")
generate_observation_id = _factory("observation")
generate_condition_result_id = _factory("condition_result")
generate_operator_event_id = _factory("operator_event")

__all__ = [
    "IdFactory",
    "generate_alias_id",
    "generate_approval_profile_id",
    "generate_asset_id",
    "generate_condition_result_id",
    "generate_graph_ref_id",
    "generate_id",
    "generate_inspection_profile_id",
    "generate_observation_id",
    "generate_operator_event_id",
    "generate_place_id",
    "generate_step_id",
    "generate_task_id",
]
