"""Strands @tool wrappers that delegate to ToolHandlerService."""

from __future__ import annotations

from strands import tool

from spot_train.tools.handlers import ToolHandlerService

_handler: ToolHandlerService | None = None
_active_task_id: str | None = None


def configure(handler: ToolHandlerService) -> None:
    """Set the shared handler instance for all tools."""
    global _handler
    _handler = handler


def set_active_task(task_id: str | None) -> None:
    """Set the active task ID for side-effect tools."""
    global _active_task_id
    _active_task_id = task_id


def get_active_task() -> str | None:
    """Return the current active task ID."""
    return _active_task_id


def _require_handler() -> ToolHandlerService:
    if _handler is None:
        raise RuntimeError("Tools not configured. Call configure(handler) first.")
    return _handler


@tool
def resolve_target(name: str, target_type: str = "auto", min_confidence: float = 0.70) -> dict:
    """Resolve a human reference to the most likely known place or asset.

    Args:
        name: The human-facing name or alias to resolve.
        target_type: Type to resolve - 'place', 'asset', or 'auto'.
        min_confidence: Minimum confidence threshold for resolution.

    Returns:
        Resolution result with selected target and confidence.
    """
    h = _require_handler()
    return h.handle(
        "resolve_target",
        {"name": name, "target_type": target_type, "min_confidence": min_confidence},
        task_id=_active_task_id,
    ).model_dump()


@tool
def get_place_context(place_id: str) -> dict:
    """Retrieve contextual information about a known place.

    Args:
        place_id: Unique identifier of the place.

    Returns:
        Place context including aliases, familiarity, and known assets.
    """
    h = _require_handler()
    return h.handle("get_place_context", {"place_id": place_id}).model_dump()


@tool
def navigate_to_place(
    place_id: str, route_policy: str = "default", timeout_s: int | None = None
) -> dict:
    """Navigate the robot to a known place. Requires an active task context.

    Args:
        place_id: Unique identifier of the destination place.
        route_policy: Routing strategy to use.
        timeout_s: Optional timeout in seconds.

    Returns:
        Navigation outcome with status and route details.
    """
    h = _require_handler()
    req: dict = {"place_id": place_id, "route_policy": route_policy}
    if timeout_s is not None:
        req["timeout_s"] = timeout_s
    return h.handle("navigate_to_place", req, task_id=_active_task_id).model_dump()


@tool
def inspect_place(place_id: str, inspection_profile_id: str) -> dict:
    """Run an inspection profile at a place. Requires an active task context.

    Args:
        place_id: Unique identifier of the place to inspect.
        inspection_profile_id: Identifier of the inspection profile to execute.

    Returns:
        Inspection results including observations and condition verdicts.
    """
    h = _require_handler()
    return h.handle(
        "inspect_place",
        {"place_id": place_id, "inspection_profile_id": inspection_profile_id},
        task_id=_active_task_id,
    ).model_dump()


@tool
def capture_evidence(place_id: str, capture_kind: str) -> dict:
    """Capture a single piece of evidence at a place. Requires an active task context.

    Args:
        place_id: Unique identifier of the place.
        capture_kind: Type of evidence to capture (e.g. 'photo', 'thermal').

    Returns:
        Captured observation details including artifact URI and confidence.
    """
    h = _require_handler()
    return h.handle(
        "capture_evidence",
        {"place_id": place_id, "capture_kind": capture_kind},
        task_id=_active_task_id,
    ).model_dump()


@tool
def verify_condition(target_type: str, target_id: str, condition_id: str) -> dict:
    """Verify a condition against a target. Requires an active task context.

    Args:
        target_type: Entity type - 'place' or 'asset'.
        target_id: Unique identifier of the target entity.
        condition_id: Identifier of the condition to verify.

    Returns:
        Condition verdict with confidence and rationale.
    """
    h = _require_handler()
    return h.handle(
        "verify_condition",
        {"target_type": target_type, "target_id": target_id, "condition_id": condition_id},
        task_id=_active_task_id,
    ).model_dump()


@tool
def relocalize(place_id: str | None = None, strategy: str = "nearest_hint") -> dict:
    """Relocalize the robot within the known map. Requires an active task context.

    Args:
        place_id: Optional place to relocalize near.
        strategy: Relocalization strategy to use.

    Returns:
        Relocalization outcome with confidence.
    """
    h = _require_handler()
    req: dict = {"strategy": strategy}
    if place_id is not None:
        req["place_id"] = place_id
    return h.handle("relocalize", req, task_id=_active_task_id).model_dump()


@tool
def get_operator_status(task_id: str | None = None) -> dict:
    """Get current operator and task status.

    Args:
        task_id: Optional task identifier. Uses active task if not provided.

    Returns:
        Operator status including active task, supervisor state, and recent evidence.
    """
    h = _require_handler()
    tid = task_id or _active_task_id
    req: dict = {}
    if tid is not None:
        req["task_id"] = tid
    return h.handle("get_operator_status", req).model_dump()


@tool
def summarize_task(task_id: str | None = None) -> dict:
    """Generate a human-readable summary of a task.

    Args:
        task_id: Task identifier. Uses active task if not provided.

    Returns:
        Task summary with status, evidence links, and condition results.
    """
    h = _require_handler()
    tid = task_id or _active_task_id
    if tid is None:
        return {"status": "error", "message": "No task_id provided and no active task."}
    return h.handle("summarize_task", {"task_id": tid}).model_dump()


def all_tools() -> list:
    """Return the list of all Strands tool functions for agent registration."""
    return [
        resolve_target,
        get_place_context,
        navigate_to_place,
        inspect_place,
        capture_evidence,
        verify_condition,
        relocalize,
        get_operator_status,
        summarize_task,
    ]
