"""Phase 8 integration tests for T-025 dry-run workflows."""

from __future__ import annotations

import types

from spot_train.adapters.perception import (
    FakePerceptionAdapter,
)
from spot_train.adapters.spot import (
    FakeSpotAdapter,
    SpotNavigationBinding,
    SpotNavigationSurface,
)
from spot_train.memory.repository import WorldRepository
from spot_train.memory.schema import create_schema
from spot_train.models import (
    ModelSource,
    OperatorEventType,
    OutcomeCode,
    StepState,
    Task,
    TaskStatus,
)
from spot_train.observability import _default_collector
from spot_train.safety.operator_event_router import OperatorEventRouter
from spot_train.safety.terminal_estop import TerminalStopController
from spot_train.supervisor.policies import (
    InconclusivePolicy,
    RecoveryPolicy,
    RetryPolicy,
    TimeoutPolicy,
)
from spot_train.supervisor.runner import (
    StepExecutionResult,
    SupervisorRunner,
    SupervisorStep,
)
from spot_train.supervisor.state_machine import SupervisorStateMachine
from spot_train.tools.handlers import ToolHandlerService
from spot_train.ui.ridealong import RidealongUI


def _make_full_session():
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
    runner = SupervisorRunner(
        repo,
        state_machine=SupervisorStateMachine,
        retry_policy=RetryPolicy(),
        timeout_policy=TimeoutPolicy(),
        recovery_policy=RecoveryPolicy(),
        inconclusive_policy=InconclusivePolicy(),
    )
    handler = ToolHandlerService(
        repo,
        runner=runner,
        spot_adapter=spot,
        perception_adapter=perception,
    )
    return repo, spot, perception, runner, handler


def test_check_optics_bench_dry_run() -> None:
    repo, spot, perception, runner, handler = _make_full_session()

    # Resolve target
    resolve_result = handler.handle("resolve_target", {"name": "optics bench"})
    assert resolve_result.status.value == "success"
    place_id = resolve_result.data["selected_target_id"]

    # Create task and run navigation + capture through supervisor
    task = repo.create_task(Task(instruction="check the optics bench"))
    handler.handle(
        "navigate_to_place",
        {"place_id": place_id},
        task_id=task.task_id,
    )
    handler.handle(
        "capture_evidence",
        {"place_id": place_id, "capture_kind": "image"},
        task_id=task.task_id,
    )

    # Verify steps persisted
    steps = repo.list_task_steps(task.task_id)
    assert len(steps) >= 2
    observations = repo.list_observations(task.task_id)
    assert len(observations) >= 1

    final_task = repo.get_task(task.task_id)
    assert final_task.status in {TaskStatus.COMPLETED, TaskStatus.INCONCLUSIVE}
    repo.close()


def test_instruction_intake_persists_metadata() -> None:
    repo = WorldRepository.connect(initialize=False)
    create_schema(repo.connection)
    task = repo.create_task(Task(instruction="check the optics bench"))

    stored = repo.get_task(task.task_id)
    assert stored.instruction == "check the optics bench"
    assert stored.created_at is not None
    assert stored.status == TaskStatus.CREATED
    repo.close()


def test_navigation_failure_then_relocalization_recovery() -> None:
    repo = WorldRepository.connect(initialize=False)
    create_schema(repo.connection)
    repo.seed_minimal_lab_world()
    task = repo.create_task(Task(instruction="go to optics bench"))

    nav_attempts = 0

    def navigate(_ctx):
        nonlocal nav_attempts
        nav_attempts += 1
        if nav_attempts == 1:
            return StepExecutionResult.failed(
                outcome_code=OutcomeCode.NAVIGATION_FAILED,
                retryable=True,
                error_code="navigation_failed",
            )
        return StepExecutionResult.success(outcome_code=OutcomeCode.NAVIGATION_SUCCEEDED)

    def recover(_ctx):
        return StepExecutionResult.success(outcome_code=OutcomeCode.RELOCALIZATION_SUCCEEDED)

    runner = SupervisorRunner(
        repo,
        state_machine=SupervisorStateMachine,
        retry_policy=RetryPolicy(default_limit=1),
        recovery_policy=RecoveryPolicy(),
    )
    result = runner.run_task(
        task.task_id,
        steps=[
            SupervisorStep(
                tool_name="navigate_to_place",
                operation=navigate,
                retry_limit=1,
                recovery_operation=recover,
            )
        ],
    )

    assert result.final_status == TaskStatus.COMPLETED
    step_states = [s.step_state for s in repo.list_task_steps(task.task_id)]
    assert StepState.FAILED in step_states
    assert StepState.SUCCEEDED in step_states
    repo.close()


def test_inspection_with_inconclusive_evidence() -> None:
    repo = WorldRepository.connect(initialize=False)
    create_schema(repo.connection)
    repo.seed_minimal_lab_world()
    task = repo.create_task(Task(instruction="inspect optics bench"))

    runner = SupervisorRunner(
        repo,
        state_machine=SupervisorStateMachine,
        inconclusive_policy=InconclusivePolicy(minimum_confidence=0.5),
    )
    result = runner.run_task(
        task.task_id,
        steps=[
            SupervisorStep(
                tool_name="capture_evidence",
                operation=lambda _ctx: StepExecutionResult.inconclusive(
                    outcome_code=OutcomeCode.PERCEPTION_INCONCLUSIVE,
                    message="Low confidence capture",
                    confidence=0.3,
                ),
            )
        ],
    )

    assert result.final_status == TaskStatus.INCONCLUSIVE
    repo.close()


def test_ridealong_reflects_supervisor_progress() -> None:
    repo = WorldRepository.connect(initialize=False)
    create_schema(repo.connection)
    task = repo.create_task(Task(instruction="check bench", status=TaskStatus.CREATED))
    ui = RidealongUI(repository=repo)

    output = ui.render_status(task.task_id)
    assert "created" in output.lower()

    repo.update_task_status(task.task_id, status=TaskStatus.EXECUTING)
    output = ui.render_status(task.task_id)
    assert "executing" in output.lower()

    repo.update_task_status(task.task_id, status=TaskStatus.COMPLETED)
    output = ui.render_status(task.task_id)
    assert "completed" in output.lower()
    repo.close()


def test_terminal_stop_interrupts_dry_run() -> None:
    repo = WorldRepository.connect(initialize=False)
    create_schema(repo.connection)
    task = repo.create_task(Task(instruction="test stop", status=TaskStatus.EXECUTING))

    spot = FakeSpotAdapter()
    runner_stub = types.SimpleNamespace(state_machine=SupervisorStateMachine)
    router = OperatorEventRouter(repository=repo, runner=runner_stub)

    callback_fired = []
    estop = TerminalStopController(
        adapter=spot,
        repository=repo,
        supervisor_callback=lambda: callback_fired.append(True),
    )
    estop.request_stop("test", "operator", task.task_id)

    router.create_and_route(
        event_type=OperatorEventType.TASK_CANCEL_REQUESTED,
        task_id=task.task_id,
        operator_id="operator",
        source=ModelSource.TERMINAL,
    )

    final = repo.get_task(task.task_id)
    assert final.status == TaskStatus.CANCELLED

    events = repo.list_operator_events(task_id=task.task_id)
    assert any(e.event_type == OperatorEventType.STOP_REQUESTED for e in events)
    assert any(e.event_type == OperatorEventType.TASK_CANCEL_REQUESTED for e in events)
    repo.close()


def test_timing_traces_distinguish_categories() -> None:
    _default_collector.spans.clear()

    repo = WorldRepository.connect(initialize=False)
    create_schema(repo.connection)
    repo.seed_minimal_lab_world()
    handler = ToolHandlerService(repo)

    handler.handle("resolve_target", {"name": "optics bench"})

    tool_spans = [s for s in _default_collector.spans if s.category == "tool"]
    assert len(tool_spans) >= 1
    assert tool_spans[0].name == "resolve_target"

    # Run a supervisor step to get a 'supervisor' category span
    task = repo.create_task(Task(instruction="timing test"))
    runner = SupervisorRunner(repo)
    runner.run_task(
        task.task_id,
        steps=[
            SupervisorStep(
                tool_name="nav",
                operation=lambda _ctx: StepExecutionResult.success(
                    outcome_code=OutcomeCode.NAVIGATION_SUCCEEDED,
                ),
            )
        ],
    )

    supervisor_spans = [s for s in _default_collector.spans if s.category == "supervisor"]
    assert len(supervisor_spans) >= 1
    repo.close()
