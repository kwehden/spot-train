"""Supervisor execution runner."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Callable, Protocol

from spot_train.memory.repository import WorldRepository
from spot_train.models import OutcomeCode, StepState, Task, TaskStatus, TaskStep
from spot_train.observability import correlation_context, get_logger, timed
from spot_train.supervisor.policies import RecoveryAction, RecoveryPolicy
from spot_train.supervisor.state_machine import SupervisorEvent

JsonDict = dict[str, Any]

_log = get_logger(__name__)


class TransitionEngine(Protocol):
    """Optional state-machine hook used by the runner when available."""

    def apply_event(self, current: TaskStatus, event: SupervisorEvent) -> object:
        """Return a transition object with a `current` status."""


class RetryPolicyLike(Protocol):
    """Optional retry policy contract."""

    def limit_for(self, tool_name: str) -> int:
        """Return the allowed retry count for a tool."""

    def should_retry(
        self, tool_name: str, retry_count: int, *, error_code: str | None, retryable: bool
    ) -> bool:
        """Return whether another attempt should be made."""


class TimeoutPolicyLike(Protocol):
    """Optional timeout policy contract."""

    def timeout_for(self, tool_name: str, *, override_timeout_s: int | None = None) -> int:
        """Return the timeout budget for a tool."""

    def is_timed_out(
        self, tool_name: str, started_at: datetime, *, now: datetime, override_timeout_s: int | None
    ) -> bool:
        """Return whether a step exceeded its timeout."""


class RecoveryPolicyLike(Protocol):
    """Optional recovery policy contract."""

    def plan_recovery(
        self, tool_name: str, *, retry_allowed: bool, error_code: str | None, retryable: bool
    ) -> object:
        """Return a recovery decision object."""


class InconclusivePolicyLike(Protocol):
    """Optional inconclusive policy contract."""

    def is_inconclusive(self, confidence: float | None, *, minimum: float | None = None) -> bool:
        """Return whether the task should end as inconclusive."""


PreconditionCheck = Callable[["ExecutionContext"], object]
StepOperation = Callable[["ExecutionContext"], "StepExecutionResult"]


@dataclass(slots=True)
class ExecutionContext:
    """Context passed to supervisor step callables."""

    repository: WorldRepository
    task: Task
    step: "SupervisorStep"
    attempt_index: int
    started_at: datetime


@dataclass(slots=True)
class PreconditionFailure:
    """Structured precondition failure result."""

    status: TaskStatus = TaskStatus.BLOCKED
    outcome_code: OutcomeCode = OutcomeCode.TASK_BLOCKED
    message: str = "Precondition failed."
    error_code: str = "precondition_failed"
    details: JsonDict = field(default_factory=dict)


@dataclass(slots=True)
class StepExecutionResult:
    """Structured outcome of a single supervisor step execution."""

    step_state: StepState
    outcome_code: OutcomeCode | None = None
    outputs: JsonDict = field(default_factory=dict)
    error_code: str | None = None
    retryable: bool = False
    confidence: float | None = None
    message: str | None = None
    details: JsonDict = field(default_factory=dict)

    @classmethod
    def success(
        cls,
        *,
        outcome_code: OutcomeCode | None = None,
        outputs: JsonDict | None = None,
        confidence: float | None = None,
    ) -> "StepExecutionResult":
        return cls(
            step_state=StepState.SUCCEEDED,
            outcome_code=outcome_code,
            outputs=outputs or {},
            confidence=confidence,
        )

    @classmethod
    def blocked(
        cls,
        *,
        outcome_code: OutcomeCode | None = None,
        message: str | None = None,
        error_code: str | None = None,
        details: JsonDict | None = None,
    ) -> "StepExecutionResult":
        return cls(
            step_state=StepState.BLOCKED,
            outcome_code=outcome_code,
            message=message,
            error_code=error_code,
            details=details or {},
        )

    @classmethod
    def failed(
        cls,
        *,
        outcome_code: OutcomeCode | None = None,
        message: str | None = None,
        error_code: str | None = None,
        retryable: bool = False,
        details: JsonDict | None = None,
    ) -> "StepExecutionResult":
        return cls(
            step_state=StepState.FAILED,
            outcome_code=outcome_code,
            message=message,
            error_code=error_code,
            retryable=retryable,
            details=details or {},
        )

    @classmethod
    def inconclusive(
        cls,
        *,
        outcome_code: OutcomeCode | None = None,
        message: str | None = None,
        confidence: float | None = None,
        outputs: JsonDict | None = None,
    ) -> "StepExecutionResult":
        return cls(
            step_state=StepState.INCONCLUSIVE,
            outcome_code=outcome_code,
            message=message,
            confidence=confidence,
            outputs=outputs or {},
        )


@dataclass(slots=True)
class SupervisorStep:
    """One side-effectful or pure step under supervisor control."""

    tool_name: str
    operation: StepOperation
    precondition: PreconditionCheck | None = None
    timeout_s: int | None = None
    retry_limit: int | None = None
    recovery_operation: StepOperation | None = None


@dataclass(slots=True)
class TaskRunResult:
    """Aggregate result of a supervised task run."""

    task: Task
    final_status: TaskStatus
    steps: list[TaskStep]


class SupervisorRunner:
    """Persisted task runner that owns execution, retries, and recovery."""

    def __init__(
        self,
        repository: WorldRepository,
        *,
        state_machine: TransitionEngine | None = None,
        retry_policy: RetryPolicyLike | None = None,
        timeout_policy: TimeoutPolicyLike | None = None,
        recovery_policy: RecoveryPolicyLike | None = None,
        inconclusive_policy: InconclusivePolicyLike | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.repository = repository
        self.state_machine = state_machine
        self.retry_policy = retry_policy
        self.timeout_policy = timeout_policy
        self.recovery_policy = recovery_policy
        self.inconclusive_policy = inconclusive_policy
        self.clock = clock or (lambda: datetime.now(UTC))
        self._state_events: dict[str, SupervisorEvent] = {
            "begin_execution": SupervisorEvent.START_EXECUTION,
            "begin_summary": SupervisorEvent.EXECUTION_COMPLETED,
            "summary_completed": SupervisorEvent.SUMMARY_COMPLETED,
            "mark_inconclusive": SupervisorEvent.EXECUTION_INCONCLUSIVE,
            "mark_blocked": SupervisorEvent.APPROVAL_DENIED,
            "mark_failed": SupervisorEvent.NON_RETRYABLE_FAILURE,
            "begin_recovery": SupervisorEvent.RETRYABLE_FAILURE,
            "recovery_succeeded": SupervisorEvent.RECOVERY_SUCCEEDED,
            "recovery_blocked": SupervisorEvent.RECOVERY_BLOCKED,
            "cancel": SupervisorEvent.CANCEL,
        }

    def run_task(self, task_id: str, steps: list[SupervisorStep]) -> TaskRunResult:
        """Execute an ordered step list for a task."""
        task = self._require_task(task_id)
        started_at = task.started_at or self.clock()
        task = self.repository.update_task_status(
            task.task_id,
            status=self._next_status(task.status, "begin_execution", TaskStatus.EXECUTING),
            started_at=started_at,
        )
        _log.info("task %s -> %s", task.task_id, task.status.value)

        persisted_steps: list[TaskStep] = []
        for step in steps:
            task = self._require_task(task.task_id)
            with correlation_context(task_id=task.task_id):
                persisted_attempts, task = self._run_step(task, step)
            persisted_steps.extend(persisted_attempts)
            if task.status in _TERMINAL_STATUSES:
                _log.info("task %s -> %s (terminal)", task.task_id, task.status.value)
                return TaskRunResult(task=task, final_status=task.status, steps=persisted_steps)

        task = self.repository.update_task_status(
            task.task_id,
            status=self._next_status(task.status, "begin_summary", TaskStatus.SUMMARIZING),
        )
        _log.info("task %s -> %s", task.task_id, task.status.value)
        task = self.repository.update_task_status(
            task.task_id,
            status=self._next_status(task.status, "summary_completed", TaskStatus.COMPLETED),
            outcome_code=OutcomeCode.TASK_COMPLETED,
            ended_at=self.clock(),
        )
        _log.info("task %s -> %s", task.task_id, task.status.value)
        return TaskRunResult(task=task, final_status=task.status, steps=persisted_steps)

    def _run_step(self, task: Task, step: SupervisorStep) -> tuple[list[TaskStep], Task]:
        persisted_steps: list[TaskStep] = []
        limit = self._retry_limit_for(step)
        attempt_index = 0

        while True:
            started_at = self.clock()
            context = ExecutionContext(
                repository=self.repository,
                task=task,
                step=step,
                attempt_index=attempt_index,
                started_at=started_at,
            )
            precondition_failure = self._evaluate_precondition(context)
            if precondition_failure is not None:
                persisted_step = self._persist_step(
                    task=task,
                    step=step,
                    result=StepExecutionResult.blocked(
                        outcome_code=precondition_failure.outcome_code,
                        message=precondition_failure.message,
                        error_code=precondition_failure.error_code,
                        details=precondition_failure.details,
                    ),
                    attempt_index=attempt_index,
                    started_at=started_at,
                    ended_at=self.clock(),
                )
                task = self.repository.update_task_status(
                    task.task_id,
                    status=precondition_failure.status,
                    outcome_code=precondition_failure.outcome_code,
                    result_summary=precondition_failure.message,
                    ended_at=self.clock(),
                )
                return [persisted_step], task

            result = self._run_step_operation(task, step, context)
            ended_at = self.clock()
            result = self._apply_timeout_if_needed(step, started_at, ended_at, result)
            persisted_step = self._persist_step(
                task=task,
                step=step,
                result=result,
                attempt_index=attempt_index,
                started_at=started_at,
                ended_at=ended_at,
            )
            persisted_steps.append(persisted_step)

            if self._should_mark_inconclusive(step, result):
                task = self.repository.update_task_status(
                    task.task_id,
                    status=self._next_status(
                        task.status,
                        "mark_inconclusive",
                        TaskStatus.INCONCLUSIVE,
                    ),
                    outcome_code=result.outcome_code or OutcomeCode.TASK_INCONCLUSIVE,
                    result_summary=result.message,
                    ended_at=ended_at,
                )
                return persisted_steps, task

            if result.step_state == StepState.SUCCEEDED:
                task = self.repository.get_task(task.task_id) or task
                return persisted_steps, task

            if result.step_state == StepState.BLOCKED:
                task = self.repository.update_task_status(
                    task.task_id,
                    status=self._next_status(task.status, "mark_blocked", TaskStatus.BLOCKED),
                    outcome_code=result.outcome_code or OutcomeCode.TASK_BLOCKED,
                    result_summary=result.message,
                    ended_at=ended_at,
                )
                return persisted_steps, task

            if result.step_state == StepState.CANCELLED:
                task = self.repository.update_task_status(
                    task.task_id,
                    status=self._next_status(task.status, "cancel", TaskStatus.CANCELLED),
                    outcome_code=result.outcome_code or OutcomeCode.TASK_CANCELLED,
                    result_summary=result.message,
                    ended_at=ended_at,
                )
                return persisted_steps, task

            recovery_decision = self._recovery_decision(step, attempt_index, limit, result)
            if self._should_attempt_recovery(recovery_decision):
                task = self.repository.update_task_status(
                    task.task_id,
                    status=self._next_status(task.status, "begin_recovery", TaskStatus.RECOVERING),
                )
                recovery_result = step.recovery_operation(context)
                recovery_step = self._persist_step(
                    task=task,
                    step=SupervisorStep(tool_name="relocalize", operation=step.recovery_operation),
                    result=recovery_result,
                    attempt_index=attempt_index,
                    started_at=self.clock(),
                    ended_at=self.clock(),
                )
                persisted_steps.append(recovery_step)
                if recovery_result.step_state == StepState.SUCCEEDED:
                    task = self.repository.update_task_status(
                        task.task_id,
                        status=self._next_status(
                            task.status,
                            "recovery_succeeded",
                            TaskStatus.EXECUTING,
                        ),
                    )
                    attempt_index += 1
                    continue
                task = self.repository.update_task_status(
                    task.task_id,
                    status=self._next_status(task.status, "recovery_blocked", TaskStatus.BLOCKED),
                    outcome_code=recovery_result.outcome_code or OutcomeCode.RELOCALIZATION_FAILED,
                    result_summary=recovery_result.message,
                    ended_at=self.clock(),
                )
                return persisted_steps, task

            if recovery_decision is not None and recovery_decision.requires_human:
                task = self.repository.update_task_status(
                    task.task_id,
                    status=self._next_status(task.status, "mark_blocked", TaskStatus.BLOCKED),
                    outcome_code=result.outcome_code or OutcomeCode.TASK_BLOCKED,
                    result_summary=result.message or recovery_decision.reason,
                    ended_at=ended_at,
                )
                return persisted_steps, task

            if self._should_retry(step, attempt_index, limit, result):
                attempt_index += 1
                continue

            task = self.repository.update_task_status(
                task.task_id,
                status=self._next_status(task.status, "mark_failed", TaskStatus.FAILED),
                outcome_code=result.outcome_code or OutcomeCode.TASK_FAILED,
                result_summary=result.message,
                ended_at=ended_at,
            )
            return persisted_steps, task

    def _run_step_operation(
        self,
        task: Task,
        step: SupervisorStep,
        context: ExecutionContext,
    ) -> StepExecutionResult:
        with timed(step.tool_name, "supervisor", task_id=task.task_id):
            return step.operation(context)

    def _persist_step(
        self,
        *,
        task: Task,
        step: SupervisorStep,
        result: StepExecutionResult,
        attempt_index: int,
        started_at: datetime,
        ended_at: datetime,
    ) -> TaskStep:
        payload = dict(result.outputs)
        if result.confidence is not None:
            payload["confidence"] = result.confidence
        if result.message is not None:
            payload["message"] = result.message
        if result.details:
            payload["details"] = result.details
        return self.repository.append_task_step(
            TaskStep(
                task_id=task.task_id,
                sequence_no=1,
                tool_name=step.tool_name,
                step_state=result.step_state,
                inputs_json={"attempt_index": attempt_index},
                outputs_json=payload or None,
                error_code=result.error_code,
                retry_count=attempt_index,
                started_at=started_at,
                ended_at=ended_at,
            )
        )

    def _evaluate_precondition(self, context: ExecutionContext) -> PreconditionFailure | None:
        if context.step.precondition is None:
            return None
        outcome = context.step.precondition(context)
        if outcome is True:
            return None
        if outcome is False:
            return PreconditionFailure()
        return outcome

    def _apply_timeout_if_needed(
        self,
        step: SupervisorStep,
        started_at: datetime,
        ended_at: datetime,
        result: StepExecutionResult,
    ) -> StepExecutionResult:
        timeout_s = self._timeout_for(step)
        if timeout_s is None:
            return result
        if not self._is_timed_out(step.tool_name, started_at, ended_at, timeout_s):
            return result
        return StepExecutionResult.failed(
            outcome_code=result.outcome_code or OutcomeCode.TASK_FAILED,
            message=result.message or "Step execution exceeded timeout budget.",
            error_code="timeout_exceeded",
            retryable=result.retryable,
            details={"timeout_s": timeout_s},
        )

    def _retry_limit_for(self, step: SupervisorStep) -> int:
        if step.retry_limit is not None:
            return step.retry_limit
        if self.retry_policy is not None and hasattr(self.retry_policy, "limit_for"):
            return int(self.retry_policy.limit_for(step.tool_name))
        return 0

    def _should_retry(
        self,
        step: SupervisorStep,
        attempt_index: int,
        retry_limit: int,
        result: StepExecutionResult,
    ) -> bool:
        if self.retry_policy is not None and hasattr(self.retry_policy, "should_retry"):
            return bool(
                self.retry_policy.should_retry(
                    step.tool_name,
                    attempt_index,
                    error_code=result.error_code,
                    retryable=result.retryable,
                )
            )
        return result.retryable and attempt_index < retry_limit

    def _timeout_for(self, step: SupervisorStep) -> int | None:
        if self.timeout_policy is not None and hasattr(self.timeout_policy, "timeout_for"):
            return self.timeout_policy.timeout_for(
                step.tool_name,
                override_timeout_s=step.timeout_s,
            )
        return step.timeout_s

    def _is_timed_out(
        self,
        tool_name: str,
        started_at: datetime,
        ended_at: datetime,
        timeout_s: int,
    ) -> bool:
        if self.timeout_policy is not None and hasattr(self.timeout_policy, "is_timed_out"):
            return bool(
                self.timeout_policy.is_timed_out(
                    tool_name,
                    started_at,
                    now=ended_at,
                    override_timeout_s=timeout_s,
                )
            )
        return (ended_at - started_at).total_seconds() > timeout_s

    def _recovery_decision(
        self,
        step: SupervisorStep,
        attempt_index: int,
        retry_limit: int,
        result: StepExecutionResult,
    ) -> object | None:
        if step.recovery_operation is None:
            return None
        retry_allowed = attempt_index < retry_limit
        if self.recovery_policy is not None and hasattr(
            self.recovery_policy,
            "plan_recovery",
        ):
            return self.recovery_policy.plan_recovery(
                step.tool_name,
                retry_allowed=retry_allowed,
                error_code=result.error_code,
                retryable=result.retryable,
            )
        return RecoveryPolicy().plan_recovery(
            step.tool_name,
            retry_allowed=retry_allowed,
            error_code=result.error_code,
            retryable=result.retryable,
        )

    def _should_attempt_recovery(self, decision: object | None) -> bool:
        if decision is None:
            return False
        action = getattr(decision, "action", None)
        should_retry = bool(getattr(decision, "should_retry", False))
        return should_retry and action == RecoveryAction.RELOCALIZE_THEN_RETRY

    def _should_mark_inconclusive(
        self,
        step: SupervisorStep,
        result: StepExecutionResult,
    ) -> bool:
        if result.step_state == StepState.INCONCLUSIVE:
            return True
        if result.confidence is None:
            return False
        if self.inconclusive_policy is not None and hasattr(
            self.inconclusive_policy,
            "is_inconclusive",
        ):
            return bool(self.inconclusive_policy.is_inconclusive(result.confidence))
        return False

    def _require_task(self, task_id: str) -> Task:
        task = self.repository.get_task(task_id)
        if task is None:
            raise KeyError(f"Unknown task_id: {task_id}")
        return task

    def _next_status(self, current: TaskStatus, event: str, fallback: TaskStatus) -> TaskStatus:
        if self.state_machine is None:
            return fallback
        if hasattr(self.state_machine, "transition"):
            try:
                return self.state_machine.transition(current, event)
            except Exception:
                return fallback
        mapped_event = self._state_events.get(event)
        if mapped_event is None or not hasattr(self.state_machine, "apply_event"):
            return fallback
        try:
            transition = self.state_machine.apply_event(current, mapped_event)
        except Exception:
            return fallback
        return getattr(transition, "current", fallback)


_TERMINAL_STATUSES = {
    TaskStatus.COMPLETED,
    TaskStatus.INCONCLUSIVE,
    TaskStatus.BLOCKED,
    TaskStatus.FAILED,
    TaskStatus.CANCELLED,
}


__all__ = [
    "ExecutionContext",
    "PreconditionFailure",
    "StepExecutionResult",
    "SupervisorRunner",
    "SupervisorStep",
    "TaskRunResult",
]
