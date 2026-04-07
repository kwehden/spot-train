from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

from spot_train.memory.repository import WorldRepository
from spot_train.models import (
    OutcomeCode,
    StepState,
    Task,
    TaskStatus,
)
from spot_train.supervisor.policies import (
    InconclusivePolicy,
    RecoveryPolicy,
    RetryPolicy,
    TimeoutPolicy,
)
from spot_train.supervisor.runner import (
    PreconditionFailure,
    StepExecutionResult,
    SupervisorRunner,
    SupervisorStep,
)
from spot_train.supervisor.state_machine import SupervisorStateMachine


def make_repository() -> WorldRepository:
    return WorldRepository.connect(initialize=True)


def test_runner_completes_successful_step_sequence() -> None:
    repository = make_repository()
    task = repository.create_task(Task(instruction="check the optics bench"))
    runner = SupervisorRunner(repository)

    result = runner.run_task(
        task.task_id,
        steps=[
            SupervisorStep(
                tool_name="resolve_target",
                operation=lambda _context: StepExecutionResult.success(
                    outcome_code=OutcomeCode.RESOLVED_EXACT,
                    outputs={"target": "optics bench"},
                ),
            ),
            SupervisorStep(
                tool_name="inspect_place",
                operation=lambda _context: StepExecutionResult.success(
                    outcome_code=OutcomeCode.INSPECTION_COMPLETED,
                    outputs={"condition": "clear"},
                ),
            ),
        ],
    )

    stored_task = repository.get_task(task.task_id)
    stored_steps = repository.list_task_steps(task.task_id)

    assert result.final_status == TaskStatus.COMPLETED
    assert stored_task.status == TaskStatus.COMPLETED
    assert stored_task.outcome_code == OutcomeCode.TASK_COMPLETED
    assert len(stored_steps) == 2
    assert [step.tool_name for step in stored_steps] == ["resolve_target", "inspect_place"]
    assert all(step.step_state == StepState.SUCCEEDED for step in stored_steps)
    repository.close()


def test_runner_blocks_on_precondition_without_calling_operation() -> None:
    repository = make_repository()
    task = repository.create_task(Task(instruction="inspect the charging station"))
    runner = SupervisorRunner(repository)
    call_count = 0

    def operation(_context: object) -> StepExecutionResult:
        nonlocal call_count
        call_count += 1
        return StepExecutionResult.success(outcome_code=OutcomeCode.NAVIGATION_SUCCEEDED)

    result = runner.run_task(
        task.task_id,
        steps=[
            SupervisorStep(
                tool_name="navigate_to_place",
                precondition=lambda _context: PreconditionFailure(
                    status=TaskStatus.BLOCKED,
                    outcome_code=OutcomeCode.APPROVAL_REQUIRED,
                    message="Approval required before navigation.",
                    error_code="approval_required",
                ),
                operation=operation,
            )
        ],
    )

    stored_task = repository.get_task(task.task_id)
    stored_steps = repository.list_task_steps(task.task_id)

    assert call_count == 0
    assert result.final_status == TaskStatus.BLOCKED
    assert stored_task.status == TaskStatus.BLOCKED
    assert stored_task.outcome_code == OutcomeCode.APPROVAL_REQUIRED
    assert len(stored_steps) == 1
    assert stored_steps[0].step_state == StepState.BLOCKED
    assert stored_steps[0].error_code == "approval_required"
    repository.close()


def test_runner_relocalizes_then_retries_retryable_navigation_failure() -> None:
    repository = make_repository()
    task = repository.create_task(Task(instruction="go to the optics bench"))
    runner = SupervisorRunner(repository)
    navigation_attempts = 0
    recovery_attempts = 0

    def navigate(_context: object) -> StepExecutionResult:
        nonlocal navigation_attempts
        navigation_attempts += 1
        if navigation_attempts == 1:
            return StepExecutionResult.failed(
                outcome_code=OutcomeCode.NAVIGATION_FAILED,
                retryable=True,
                message="Localization drift detected.",
                error_code="navigation_failed",
            )
        return StepExecutionResult.success(outcome_code=OutcomeCode.NAVIGATION_SUCCEEDED)

    def relocalize(_context: object) -> StepExecutionResult:
        nonlocal recovery_attempts
        recovery_attempts += 1
        return StepExecutionResult.success(outcome_code=OutcomeCode.RELOCALIZATION_SUCCEEDED)

    result = runner.run_task(
        task.task_id,
        steps=[
            SupervisorStep(
                tool_name="navigate_to_place",
                operation=navigate,
                retry_limit=1,
                recovery_operation=relocalize,
            )
        ],
    )

    stored_task = repository.get_task(task.task_id)
    stored_steps = repository.list_task_steps(task.task_id)

    assert result.final_status == TaskStatus.COMPLETED
    assert stored_task.status == TaskStatus.COMPLETED
    assert navigation_attempts == 2
    assert recovery_attempts == 1
    assert [step.tool_name for step in stored_steps] == [
        "navigate_to_place",
        "relocalize",
        "navigate_to_place",
    ]
    assert stored_steps[0].step_state == StepState.FAILED
    assert stored_steps[1].step_state == StepState.SUCCEEDED
    assert stored_steps[2].step_state == StepState.SUCCEEDED
    repository.close()


def test_runner_marks_inconclusive_for_low_confidence_evidence() -> None:
    repository = make_repository()
    task = repository.create_task(Task(instruction="inspect the optics bench"))
    runner = SupervisorRunner(repository)

    result = runner.run_task(
        task.task_id,
        steps=[
            SupervisorStep(
                tool_name="inspect_place",
                operation=lambda _context: StepExecutionResult.inconclusive(
                    outcome_code=OutcomeCode.INSPECTION_INCONCLUSIVE,
                    message="Evidence confidence too low.",
                    confidence=0.32,
                ),
            )
        ],
    )

    stored_task = repository.get_task(task.task_id)
    stored_steps = repository.list_task_steps(task.task_id)

    assert result.final_status == TaskStatus.INCONCLUSIVE
    assert stored_task.status == TaskStatus.INCONCLUSIVE
    assert stored_task.outcome_code == OutcomeCode.INSPECTION_INCONCLUSIVE
    assert len(stored_steps) == 1
    assert stored_steps[0].step_state == StepState.INCONCLUSIVE
    repository.close()


def test_runner_applies_timeout_hook_to_step_execution() -> None:
    repository = make_repository()
    task = repository.create_task(Task(instruction="inspect the optics bench"))
    clock = _clock_sequence(
        [
            datetime(2026, 4, 7, 12, 0, tzinfo=UTC),
            datetime(2026, 4, 7, 12, 0, tzinfo=UTC),
            datetime(2026, 4, 7, 12, 0, 5, tzinfo=UTC),
            datetime(2026, 4, 7, 12, 0, 5, tzinfo=UTC),
        ]
    )
    runner = SupervisorRunner(repository, clock=clock)

    result = runner.run_task(
        task.task_id,
        steps=[
            SupervisorStep(
                tool_name="inspect_place",
                timeout_s=1,
                operation=lambda _context: StepExecutionResult.success(
                    outcome_code=OutcomeCode.OBSERVATION_CAPTURED
                ),
            )
        ],
    )

    stored_task = repository.get_task(task.task_id)
    stored_steps = repository.list_task_steps(task.task_id)

    assert result.final_status == TaskStatus.FAILED
    assert stored_task.status == TaskStatus.FAILED
    assert stored_steps[0].error_code == "timeout_exceeded"
    repository.close()


def test_runner_integrates_with_concrete_state_machine_and_policy_objects() -> None:
    repository = make_repository()
    task = repository.create_task(Task(instruction="navigate to optics bench"))
    navigation_attempts = 0
    recovery_attempts = 0

    def navigate(_context: object) -> StepExecutionResult:
        nonlocal navigation_attempts
        navigation_attempts += 1
        if navigation_attempts == 1:
            return StepExecutionResult.failed(
                outcome_code=OutcomeCode.NAVIGATION_FAILED,
                retryable=True,
                error_code="navigation_failed",
                message="Localization drift detected.",
            )
        return StepExecutionResult.success(outcome_code=OutcomeCode.NAVIGATION_SUCCEEDED)

    def relocalize(_context: object) -> StepExecutionResult:
        nonlocal recovery_attempts
        recovery_attempts += 1
        return StepExecutionResult.success(outcome_code=OutcomeCode.RELOCALIZATION_SUCCEEDED)

    runner = SupervisorRunner(
        repository,
        state_machine=SupervisorStateMachine,
        retry_policy=RetryPolicy(default_limit=1),
        timeout_policy=TimeoutPolicy(default_timeout_s=30),
        recovery_policy=RecoveryPolicy(),
        inconclusive_policy=InconclusivePolicy(minimum_confidence=0.7),
    )

    result = runner.run_task(
        task.task_id,
        steps=[
            SupervisorStep(
                tool_name="navigate_to_place",
                operation=navigate,
                recovery_operation=relocalize,
            )
        ],
    )

    assert result.final_status == TaskStatus.COMPLETED
    assert navigation_attempts == 2
    assert recovery_attempts == 1
    assert [step.tool_name for step in repository.list_task_steps(task.task_id)] == [
        "navigate_to_place",
        "relocalize",
        "navigate_to_place",
    ]
    repository.close()


def test_runner_inconclusive_policy_marks_low_confidence_success_as_inconclusive() -> None:
    repository = make_repository()
    task = repository.create_task(Task(instruction="inspect optics bench"))
    runner = SupervisorRunner(
        repository,
        state_machine=SupervisorStateMachine,
        inconclusive_policy=InconclusivePolicy(minimum_confidence=0.8),
    )

    result = runner.run_task(
        task.task_id,
        steps=[
            SupervisorStep(
                tool_name="inspect_place",
                operation=lambda _context: StepExecutionResult.success(
                    outcome_code=OutcomeCode.INSPECTION_COMPLETED,
                    confidence=0.2,
                ),
            )
        ],
    )

    assert result.final_status == TaskStatus.INCONCLUSIVE
    assert repository.get_task(task.task_id).status == TaskStatus.INCONCLUSIVE
    repository.close()


def _clock_sequence(values: list[datetime]) -> Iterator[datetime]:
    iterator = iter(values)
    last = values[-1]

    def next_value() -> datetime:
        nonlocal last
        try:
            last = next(iterator)
        except StopIteration:
            return last
        return last

    return next_value
