"""Task state machine definitions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from spot_train.models import TaskOutcome, TaskStatus


class InvalidTransitionError(ValueError):
    """Raised when a state transition violates the approved supervisor graph."""


class SupervisorEvent(str, Enum):
    """Named transition events used by the deterministic supervisor."""

    START_RESOLUTION = "start_resolution"
    TARGET_RESOLVED = "target_resolved"
    TARGET_UNRESOLVED = "target_unresolved"
    APPROVAL_REQUIRED = "approval_required"
    APPROVAL_GRANTED = "approval_granted"
    APPROVAL_DENIED = "approval_denied"
    START_EXECUTION = "start_execution"
    STEP_COMPLETED = "step_completed"
    RETRYABLE_FAILURE = "retryable_failure"
    NON_RETRYABLE_FAILURE = "non_retryable_failure"
    EXECUTION_COMPLETED = "execution_completed"
    EXECUTION_INCONCLUSIVE = "execution_inconclusive"
    RECOVERY_SUCCEEDED = "recovery_succeeded"
    RECOVERY_BLOCKED = "recovery_blocked"
    RETRY_EXHAUSTED = "retry_exhausted"
    SUMMARY_COMPLETED = "summary_completed"
    SUMMARY_INCONCLUSIVE = "summary_inconclusive"
    CANCEL = "cancel"


TERMINAL_STATUSES: frozenset[TaskStatus] = frozenset(
    {
        TaskStatus.COMPLETED,
        TaskStatus.INCONCLUSIVE,
        TaskStatus.BLOCKED,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
    }
)

ALLOWED_TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.CREATED: frozenset({TaskStatus.RESOLVING_TARGET, TaskStatus.CANCELLED}),
    TaskStatus.RESOLVING_TARGET: frozenset(
        {TaskStatus.READY, TaskStatus.BLOCKED, TaskStatus.CANCELLED}
    ),
    TaskStatus.READY: frozenset(
        {TaskStatus.AWAITING_APPROVAL, TaskStatus.EXECUTING, TaskStatus.CANCELLED}
    ),
    TaskStatus.AWAITING_APPROVAL: frozenset(
        {TaskStatus.EXECUTING, TaskStatus.BLOCKED, TaskStatus.CANCELLED}
    ),
    TaskStatus.EXECUTING: frozenset(
        {
            TaskStatus.EXECUTING,
            TaskStatus.RECOVERING,
            TaskStatus.SUMMARIZING,
            TaskStatus.INCONCLUSIVE,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        }
    ),
    TaskStatus.RECOVERING: frozenset(
        {TaskStatus.EXECUTING, TaskStatus.BLOCKED, TaskStatus.FAILED, TaskStatus.CANCELLED}
    ),
    TaskStatus.SUMMARIZING: frozenset(
        {TaskStatus.COMPLETED, TaskStatus.INCONCLUSIVE, TaskStatus.CANCELLED}
    ),
    TaskStatus.COMPLETED: frozenset(),
    TaskStatus.INCONCLUSIVE: frozenset(),
    TaskStatus.BLOCKED: frozenset(),
    TaskStatus.FAILED: frozenset(),
    TaskStatus.CANCELLED: frozenset(),
}

EVENT_TRANSITIONS: dict[TaskStatus, dict[SupervisorEvent, TaskStatus]] = {
    TaskStatus.CREATED: {
        SupervisorEvent.START_RESOLUTION: TaskStatus.RESOLVING_TARGET,
        SupervisorEvent.CANCEL: TaskStatus.CANCELLED,
    },
    TaskStatus.RESOLVING_TARGET: {
        SupervisorEvent.TARGET_RESOLVED: TaskStatus.READY,
        SupervisorEvent.TARGET_UNRESOLVED: TaskStatus.BLOCKED,
        SupervisorEvent.CANCEL: TaskStatus.CANCELLED,
    },
    TaskStatus.READY: {
        SupervisorEvent.APPROVAL_REQUIRED: TaskStatus.AWAITING_APPROVAL,
        SupervisorEvent.START_EXECUTION: TaskStatus.EXECUTING,
        SupervisorEvent.CANCEL: TaskStatus.CANCELLED,
    },
    TaskStatus.AWAITING_APPROVAL: {
        SupervisorEvent.APPROVAL_GRANTED: TaskStatus.EXECUTING,
        SupervisorEvent.APPROVAL_DENIED: TaskStatus.BLOCKED,
        SupervisorEvent.CANCEL: TaskStatus.CANCELLED,
    },
    TaskStatus.EXECUTING: {
        SupervisorEvent.STEP_COMPLETED: TaskStatus.EXECUTING,
        SupervisorEvent.RETRYABLE_FAILURE: TaskStatus.RECOVERING,
        SupervisorEvent.EXECUTION_COMPLETED: TaskStatus.SUMMARIZING,
        SupervisorEvent.EXECUTION_INCONCLUSIVE: TaskStatus.INCONCLUSIVE,
        SupervisorEvent.NON_RETRYABLE_FAILURE: TaskStatus.FAILED,
        SupervisorEvent.CANCEL: TaskStatus.CANCELLED,
    },
    TaskStatus.RECOVERING: {
        SupervisorEvent.RECOVERY_SUCCEEDED: TaskStatus.EXECUTING,
        SupervisorEvent.RECOVERY_BLOCKED: TaskStatus.BLOCKED,
        SupervisorEvent.RETRY_EXHAUSTED: TaskStatus.FAILED,
        SupervisorEvent.CANCEL: TaskStatus.CANCELLED,
    },
    TaskStatus.SUMMARIZING: {
        SupervisorEvent.SUMMARY_COMPLETED: TaskStatus.COMPLETED,
        SupervisorEvent.SUMMARY_INCONCLUSIVE: TaskStatus.INCONCLUSIVE,
        SupervisorEvent.CANCEL: TaskStatus.CANCELLED,
    },
}

TERMINAL_OUTCOMES: dict[TaskStatus, TaskOutcome] = {
    TaskStatus.COMPLETED: TaskOutcome.COMPLETED,
    TaskStatus.INCONCLUSIVE: TaskOutcome.INCONCLUSIVE,
    TaskStatus.BLOCKED: TaskOutcome.BLOCKED,
    TaskStatus.FAILED: TaskOutcome.FAILED,
    TaskStatus.CANCELLED: TaskOutcome.CANCELLED,
}


@dataclass(frozen=True, slots=True)
class Transition:
    """A validated supervisor state change."""

    previous: TaskStatus
    event: SupervisorEvent | None
    current: TaskStatus


class SupervisorStateMachine:
    """Deterministic task-state transition helper."""

    @staticmethod
    def is_terminal(status: TaskStatus) -> bool:
        return status in TERMINAL_STATUSES

    @staticmethod
    def outcome_for_status(status: TaskStatus) -> TaskOutcome | None:
        return TERMINAL_OUTCOMES.get(status)

    @staticmethod
    def can_transition(current: TaskStatus, new_status: TaskStatus) -> bool:
        return new_status in ALLOWED_TRANSITIONS.get(current, frozenset())

    @classmethod
    def validate_transition(cls, current: TaskStatus, new_status: TaskStatus) -> None:
        if not cls.can_transition(current, new_status):
            raise InvalidTransitionError(
                f"Invalid task transition: {current.value} -> {new_status.value}"
            )

    @classmethod
    def transition(cls, current: TaskStatus, new_status: TaskStatus) -> Transition:
        cls.validate_transition(current, new_status)
        return Transition(previous=current, event=None, current=new_status)

    @classmethod
    def apply_event(cls, current: TaskStatus, event: SupervisorEvent) -> Transition:
        next_status = EVENT_TRANSITIONS.get(current, {}).get(event)
        if next_status is None:
            raise InvalidTransitionError(
                f"Invalid supervisor event {event.value} from state {current.value}"
            )
        cls.validate_transition(current, next_status)
        return Transition(previous=current, event=event, current=next_status)

    @classmethod
    def start_resolution(cls, current: TaskStatus = TaskStatus.CREATED) -> Transition:
        return cls.apply_event(current, SupervisorEvent.START_RESOLUTION)

    @classmethod
    def target_resolved(cls, current: TaskStatus = TaskStatus.RESOLVING_TARGET) -> Transition:
        return cls.apply_event(current, SupervisorEvent.TARGET_RESOLVED)

    @classmethod
    def target_unresolved(cls, current: TaskStatus = TaskStatus.RESOLVING_TARGET) -> Transition:
        return cls.apply_event(current, SupervisorEvent.TARGET_UNRESOLVED)

    @classmethod
    def approval_required(cls, current: TaskStatus = TaskStatus.READY) -> Transition:
        return cls.apply_event(current, SupervisorEvent.APPROVAL_REQUIRED)

    @classmethod
    def approval_granted(cls, current: TaskStatus = TaskStatus.AWAITING_APPROVAL) -> Transition:
        return cls.apply_event(current, SupervisorEvent.APPROVAL_GRANTED)

    @classmethod
    def approval_denied(cls, current: TaskStatus = TaskStatus.AWAITING_APPROVAL) -> Transition:
        return cls.apply_event(current, SupervisorEvent.APPROVAL_DENIED)

    @classmethod
    def start_execution(cls, current: TaskStatus = TaskStatus.READY) -> Transition:
        return cls.apply_event(current, SupervisorEvent.START_EXECUTION)

    @classmethod
    def step_completed(cls, current: TaskStatus = TaskStatus.EXECUTING) -> Transition:
        return cls.apply_event(current, SupervisorEvent.STEP_COMPLETED)

    @classmethod
    def retryable_failure(cls, current: TaskStatus = TaskStatus.EXECUTING) -> Transition:
        return cls.apply_event(current, SupervisorEvent.RETRYABLE_FAILURE)

    @classmethod
    def non_retryable_failure(cls, current: TaskStatus = TaskStatus.EXECUTING) -> Transition:
        return cls.apply_event(current, SupervisorEvent.NON_RETRYABLE_FAILURE)

    @classmethod
    def execution_completed(cls, current: TaskStatus = TaskStatus.EXECUTING) -> Transition:
        return cls.apply_event(current, SupervisorEvent.EXECUTION_COMPLETED)

    @classmethod
    def execution_inconclusive(cls, current: TaskStatus = TaskStatus.EXECUTING) -> Transition:
        return cls.apply_event(current, SupervisorEvent.EXECUTION_INCONCLUSIVE)

    @classmethod
    def recovery_succeeded(cls, current: TaskStatus = TaskStatus.RECOVERING) -> Transition:
        return cls.apply_event(current, SupervisorEvent.RECOVERY_SUCCEEDED)

    @classmethod
    def recovery_blocked(cls, current: TaskStatus = TaskStatus.RECOVERING) -> Transition:
        return cls.apply_event(current, SupervisorEvent.RECOVERY_BLOCKED)

    @classmethod
    def retry_exhausted(cls, current: TaskStatus = TaskStatus.RECOVERING) -> Transition:
        return cls.apply_event(current, SupervisorEvent.RETRY_EXHAUSTED)

    @classmethod
    def summary_completed(cls, current: TaskStatus = TaskStatus.SUMMARIZING) -> Transition:
        return cls.apply_event(current, SupervisorEvent.SUMMARY_COMPLETED)

    @classmethod
    def summary_inconclusive(cls, current: TaskStatus = TaskStatus.SUMMARIZING) -> Transition:
        return cls.apply_event(current, SupervisorEvent.SUMMARY_INCONCLUSIVE)

    @classmethod
    def cancel(cls, current: TaskStatus) -> Transition:
        return cls.apply_event(current, SupervisorEvent.CANCEL)


__all__ = [
    "ALLOWED_TRANSITIONS",
    "EVENT_TRANSITIONS",
    "InvalidTransitionError",
    "SupervisorEvent",
    "SupervisorStateMachine",
    "TERMINAL_OUTCOMES",
    "TERMINAL_STATUSES",
    "Transition",
]
