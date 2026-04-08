from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from spot_train.models import TaskOutcome, TaskStatus
from spot_train.supervisor.policies import (
    InconclusivePolicy,
    RecoveryAction,
    RecoveryPolicy,
    RetryPolicy,
    TimeoutPolicy,
)
from spot_train.supervisor.state_machine import (
    InvalidTransitionError,
    SupervisorEvent,
    SupervisorStateMachine,
)


def test_state_machine_accepts_spec_success_path() -> None:
    transition = SupervisorStateMachine.start_resolution()
    assert transition.current == TaskStatus.RESOLVING_TARGET

    transition = SupervisorStateMachine.target_resolved(transition.current)
    assert transition.current == TaskStatus.READY

    transition = SupervisorStateMachine.start_execution(transition.current)
    assert transition.current == TaskStatus.EXECUTING

    transition = SupervisorStateMachine.execution_completed(transition.current)
    assert transition.current == TaskStatus.SUMMARIZING

    transition = SupervisorStateMachine.summary_completed(transition.current)
    assert transition.current == TaskStatus.COMPLETED
    assert SupervisorStateMachine.outcome_for_status(transition.current) == TaskOutcome.COMPLETED
    assert SupervisorStateMachine.is_terminal(transition.current) is True


def test_state_machine_handles_blocked_inconclusive_failed_and_cancelled() -> None:
    assert (
        SupervisorStateMachine.target_unresolved(TaskStatus.RESOLVING_TARGET).current
        == TaskStatus.BLOCKED
    )
    assert (
        SupervisorStateMachine.execution_inconclusive(TaskStatus.EXECUTING).current
        == TaskStatus.INCONCLUSIVE
    )
    assert (
        SupervisorStateMachine.non_retryable_failure(TaskStatus.EXECUTING).current
        == TaskStatus.FAILED
    )
    assert SupervisorStateMachine.cancel(TaskStatus.READY).current == TaskStatus.CANCELLED


def test_state_machine_rejects_invalid_transitions_and_events() -> None:
    with pytest.raises(InvalidTransitionError):
        SupervisorStateMachine.transition(TaskStatus.CREATED, TaskStatus.EXECUTING)

    with pytest.raises(InvalidTransitionError):
        SupervisorStateMachine.apply_event(TaskStatus.CREATED, SupervisorEvent.APPROVAL_GRANTED)


def test_state_machine_models_recovery_and_approval_paths() -> None:
    assert (
        SupervisorStateMachine.approval_required(TaskStatus.READY).current
        == TaskStatus.AWAITING_APPROVAL
    )
    assert (
        SupervisorStateMachine.approval_granted(TaskStatus.AWAITING_APPROVAL).current
        == TaskStatus.EXECUTING
    )
    assert (
        SupervisorStateMachine.retryable_failure(TaskStatus.EXECUTING).current
        == TaskStatus.RECOVERING
    )
    assert (
        SupervisorStateMachine.recovery_succeeded(TaskStatus.RECOVERING).current
        == TaskStatus.EXECUTING
    )
    assert (
        SupervisorStateMachine.retry_exhausted(TaskStatus.RECOVERING).current == TaskStatus.FAILED
    )


def test_retry_policy_honors_budget_and_error_codes() -> None:
    policy = RetryPolicy(default_limit=1, per_tool_limits={"capture_evidence": 2})

    assert policy.should_retry("navigate_to_place", 0, error_code="navigation_failed") is True
    assert policy.should_retry("navigate_to_place", 1, error_code="navigation_failed") is False
    assert policy.should_retry("capture_evidence", 1, error_code="capture_failed") is True
    assert policy.should_retry("capture_evidence", 0, error_code="approval_denied") is False


def test_timeout_policy_uses_overrides_and_elapsed_time() -> None:
    now = datetime.now(timezone.utc)
    policy = TimeoutPolicy(default_timeout_s=30, per_tool_timeouts_s={"inspect_place": 120})

    assert policy.timeout_for("inspect_place") == 120
    assert policy.timeout_for("resolve_target", override_timeout_s=10) == 10
    assert (
        policy.is_timed_out(
            "inspect_place",
            now - timedelta(seconds=121),
            now=now,
        )
        is True
    )
    assert policy.is_timed_out("inspect_place", now - timedelta(seconds=30), now=now) is False


def test_recovery_and_inconclusive_policies_follow_spec() -> None:
    recovery = RecoveryPolicy()
    inconclusive = InconclusivePolicy(minimum_confidence=0.75)

    navigation_plan = recovery.plan_recovery(
        "navigate_to_place",
        retry_allowed=True,
        error_code="navigation_failed",
        retryable=True,
    )
    blocked_plan = recovery.plan_recovery(
        "navigate_to_place",
        retry_allowed=True,
        error_code="approval_denied",
        retryable=False,
    )
    failed_plan = recovery.plan_recovery(
        "capture_evidence",
        retry_allowed=False,
        error_code="capture_failed",
        retryable=True,
    )

    assert navigation_plan.action == RecoveryAction.RELOCALIZE_THEN_RETRY
    assert navigation_plan.should_retry is True
    assert blocked_plan.action == RecoveryAction.BLOCK_FOR_OPERATOR
    assert blocked_plan.requires_human is True
    assert failed_plan.action == RecoveryAction.FAIL_TASK
    assert inconclusive.is_inconclusive(0.6) is True
    assert inconclusive.is_inconclusive(0.9) is False
    assert inconclusive.is_inconclusive(None) is True
