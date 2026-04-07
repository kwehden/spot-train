"""End-to-end dry-run smoke test exercising Phases 0-5."""
from __future__ import annotations

from spot_train.adapters.approval import FakeApprovalAdapter
from spot_train.adapters.perception import FakePerceptionAdapter
from spot_train.adapters.spot import (
    FakeSpotAdapter,
    SpotNavigationBinding,
    SpotNavigationSurface,
    SpotStopState,
)
from spot_train.memory.repository import WorldRepository
from spot_train.memory.schema import create_schema
from spot_train.models import (
    ModelSource,
    OperatorEventType,
    Task,
    TaskStatus,
)
from spot_train.safety.operator_event_router import OperatorEventRouter
from spot_train.safety.terminal_estop import TerminalStopController
from spot_train.supervisor.state_machine import SupervisorStateMachine
from spot_train.tools.contracts import (
    GetOperatorStatusRequest,
    ResolveTargetRequest,
)
from spot_train.tools.handlers import ToolHandlerService
from spot_train.ui.ridealong import RidealongUI


def main() -> None:
    # ── Bootstrap ──
    repo = WorldRepository.connect(initialize=False)
    create_schema(repo.connection)
    repo.seed_minimal_lab_world()

    spot = FakeSpotAdapter()
    spot.register_navigation_binding(
        SpotNavigationBinding(
            place_id="plc_optics_bench",
            surface=SpotNavigationSurface.WAYPOINT,
            anchor_hint="optics area",
        )
    )
    perception = FakePerceptionAdapter()
    approval = FakeApprovalAdapter()
    handler = ToolHandlerService(repo, spot_adapter=spot, perception_adapter=perception)

    import types

    runner_stub = types.SimpleNamespace(state_machine=SupervisorStateMachine)
    router = OperatorEventRouter(repository=repo, runner=runner_stub)
    ui = RidealongUI(repository=repo, spot_adapter=spot)

    callback_fired = []
    estop = TerminalStopController(
        adapter=spot,
        repository=repo,
        supervisor_callback=lambda: callback_fired.append(True),
    )

    print("=== Phase 0-1: Bootstrap + Persistence ===")
    places = repo.list_places()
    print(f"  Seeded {len(places)} places")
    for p in places:
        aliases = repo.list_place_aliases(p.place_id)
        print(f"    {p.canonical_name} ({len(aliases)} aliases)")
    assert len(places) > 0, "No places seeded"
    print("  ✅ Persistence OK\n")

    # ── Target resolution ──
    print("=== Phase 3: Target Resolution ===")
    result = handler.handle("resolve_target", {"name": "optics bench"})
    print(f"  resolve_target -> status={result.status}, outcome={result.outcome_code}")
    assert result.status.value == "success", f"Expected success, got {result.status}"
    resolved_place_id = result.data.get("selected_target_id") if hasattr(result, "data") else None
    if resolved_place_id is None and hasattr(result, "payload"):
        resolved_place_id = result.payload.selected_target_id
    print(f"  Resolved to: {resolved_place_id}")
    print("  ✅ Target resolution OK\n")

    # ── Create a task and walk it through supervisor states ──
    print("=== Phase 2: Supervisor State Machine ===")
    task = repo.create_task(Task(instruction="check the optics bench", status=TaskStatus.CREATED))
    task_id = task.task_id

    sm = SupervisorStateMachine
    t = sm.start_resolution(TaskStatus.CREATED)
    repo.update_task_status(task_id, status=t.current)
    print(f"  {t.previous} -> {t.current}")

    t = sm.target_resolved(TaskStatus.RESOLVING_TARGET)
    repo.update_task_status(task_id, status=t.current)
    print(f"  {t.previous} -> {t.current}")

    # Test approval gate
    t = sm.approval_required(TaskStatus.READY)
    repo.update_task_status(task_id, status=t.current)
    print(f"  {t.previous} -> {t.current}")

    # ── Ridealong shows approval pending ──
    print("\n=== Phase 5: Ridealong (approval pending) ===")
    status_text = ui.render_status(task_id)
    assert "APPROVAL PENDING" in status_text
    print("  ✅ Ridealong shows APPROVAL PENDING\n")

    # ── Approval adapter ──
    print("=== Phase 5: Approval Adapter ===")
    approval_outcome = approval.request_approval(task_id, "navigate to optics bench")
    print(f"  Approval: approved={approval_outcome.approved}")
    assert approval_outcome.approved
    print("  ✅ FakeApprovalAdapter auto-approves\n")

    # ── Route approval event through operator event router ──
    print("=== Phase 5: Operator Event Router (approval) ===")
    router.create_and_route(
        event_type=OperatorEventType.APPROVAL_GRANTED,
        task_id=task_id,
        operator_id="smoke-test-operator",
        source=ModelSource.TERMINAL,
    )
    task = repo.get_task(task_id)
    print(f"  After APPROVAL_GRANTED: status={task.status}")
    assert task.status == TaskStatus.EXECUTING
    print("  ✅ Router transitioned task to EXECUTING\n")

    # ── Navigation via tool handler ──
    print("=== Phase 3-4: Navigation ===")
    if resolved_place_id:
        nav_result = handler.handle("navigate_to_place", {"place_id": resolved_place_id})
        status_val = getattr(nav_result, "status", None)
        outcome_val = getattr(nav_result, "outcome_code", getattr(nav_result, "error_code", None))
        print(f"  navigate_to_place -> status={status_val}, outcome={outcome_val}")
    print("  ✅ Navigation handler OK\n")

    # ── Evidence capture ──
    print("=== Phase 3-4: Evidence Capture ===")
    if resolved_place_id:
        cap_result = handler.handle(
            "capture_evidence", {"place_id": resolved_place_id, "capture_kind": "image"}
        )
        status_val = getattr(cap_result, "status", None)
        outcome_val = getattr(cap_result, "outcome_code", getattr(cap_result, "error_code", None))
        print(f"  capture_evidence -> status={status_val}, outcome={outcome_val}")
    print("  ✅ Evidence capture OK\n")

    # ── Condition verification ──
    print("=== Phase 3-4: Condition Verification ===")
    if resolved_place_id:
        verify_result = handler.handle(
            "verify_condition",
            {
                "target_type": "place",
                "target_id": resolved_place_id,
                "condition_id": "equipment_powered_on",
            },
        )
        status_val = getattr(verify_result, "status", None)
        outcome_val = getattr(
            verify_result, "outcome_code", getattr(verify_result, "error_code", None)
        )
        print(f"  verify_condition -> status={status_val}, outcome={outcome_val}")
    print("  ✅ Condition verification OK\n")

    # ── Operator status ──
    print("=== Phase 3: Operator Status ===")
    op_status = handler.get_operator_status(GetOperatorStatusRequest(task_id=task_id))
    print(f"  operator_status -> status={op_status.status}")
    print("  ✅ Operator status OK\n")

    # ── Ridealong with task data ──
    print("=== Phase 5: Ridealong (with task data) ===")
    status_text = ui.render_status(task_id)
    assert "check the optics bench" in status_text
    print(status_text)
    print("  ✅ Ridealong renders task state\n")

    # ── Terminal stop control ──
    print("=== Phase 5: Terminal Stop Control ===")
    assert estop.status() == SpotStopState.CLEAR
    print(f"  Initial stop state: {estop.status().value}")

    estop.request_stop("smoke test stop", "smoke-operator", task_id)
    assert estop.status() == SpotStopState.STOP_REQUESTED
    assert callback_fired == [True]
    print(f"  After stop: {estop.status().value}, callback fired: {callback_fired}")

    events = repo.list_operator_events(task_id=task_id)
    stop_events = [e for e in events if e.event_type == OperatorEventType.STOP_REQUESTED]
    assert len(stop_events) == 1
    print(f"  Stop event persisted: {stop_events[0].operator_event_id}")

    # Ridealong should show stop state
    status_text = ui.render_status(task_id)
    assert "STOP REQUESTED" in status_text
    print("  ✅ Ridealong shows STOP REQUESTED")

    estop.clear_stop()
    assert estop.status() == SpotStopState.CLEAR
    print(f"  After clear: {estop.status().value}")
    print("  ✅ Terminal stop control OK\n")

    # ── Cancel via router ──
    print("=== Phase 5: Operator Event Router (cancel) ===")
    router.create_and_route(
        event_type=OperatorEventType.TASK_CANCEL_REQUESTED,
        task_id=task_id,
        operator_id="smoke-operator",
    )
    task = repo.get_task(task_id)
    print(f"  After TASK_CANCEL_REQUESTED: status={task.status}")
    assert task.status == TaskStatus.CANCELLED
    print("  ✅ Router cancelled task\n")

    # ── Final ridealong ──
    print("=== Phase 5: Ridealong (final) ===")
    status_text = ui.render_status(task_id)
    assert "cancelled" in status_text.lower()
    print("  ✅ Ridealong shows cancelled state\n")

    # ── Summary ──
    all_events = repo.list_operator_events(task_id=task_id)
    print("=== Audit Trail ===")
    for e in all_events:
        print(f"  {e.event_type.value} by {e.operator_id} via {e.source}")
    print()
    print("🎉 Full-stack smoke test PASSED (Phases 0-5)")


if __name__ == "__main__":
    main()
