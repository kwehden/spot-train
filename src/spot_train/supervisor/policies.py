"""Retry, timeout, approval, and recovery policies."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum


class RecoveryAction(str, Enum):
    """Recovery actions recommended by the deterministic supervisor."""

    RELOCALIZE_THEN_RETRY = "relocalize_then_retry"
    RETRY_STEP = "retry_step"
    BLOCK_FOR_OPERATOR = "block_for_operator"
    FAIL_TASK = "fail_task"


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Retry limits and retryability checks for supervisor steps."""

    default_limit: int = 1
    per_tool_limits: dict[str, int] = field(default_factory=dict)
    retryable_error_codes: frozenset[str] = field(
        default_factory=lambda: frozenset(
            {
                "navigation_failed",
                "relocalization_required",
                "capture_failed",
                "timeout",
            }
        )
    )

    def limit_for(self, tool_name: str) -> int:
        return self.per_tool_limits.get(tool_name, self.default_limit)

    def has_budget(self, tool_name: str, retry_count: int) -> bool:
        return retry_count < self.limit_for(tool_name)

    def should_retry(
        self,
        tool_name: str,
        retry_count: int,
        *,
        error_code: str | None = None,
        retryable: bool = True,
    ) -> bool:
        if not retryable:
            return False
        if error_code is not None and error_code not in self.retryable_error_codes:
            return False
        return self.has_budget(tool_name, retry_count)


@dataclass(frozen=True, slots=True)
class TimeoutPolicy:
    """Timeout selection and elapsed-time evaluation for supervisor steps."""

    default_timeout_s: int = 300
    per_tool_timeouts_s: dict[str, int] = field(default_factory=dict)

    def timeout_for(self, tool_name: str, *, override_timeout_s: int | None = None) -> int:
        if override_timeout_s is not None:
            return override_timeout_s
        return self.per_tool_timeouts_s.get(tool_name, self.default_timeout_s)

    def is_timed_out(
        self,
        tool_name: str,
        started_at: datetime,
        *,
        now: datetime | None = None,
        override_timeout_s: int | None = None,
    ) -> bool:
        current = now or datetime.now(timezone.utc)
        elapsed = current - started_at
        timeout_s = self.timeout_for(tool_name, override_timeout_s=override_timeout_s)
        return elapsed >= timedelta(seconds=timeout_s)


@dataclass(frozen=True, slots=True)
class RecoveryDecision:
    """A concrete recovery recommendation for a failed supervisor step."""

    action: RecoveryAction
    requires_human: bool
    should_retry: bool
    reason: str


@dataclass(frozen=True, slots=True)
class RecoveryPolicy:
    """Recovery guidance with relocalization-first navigation handling."""

    relocalize_first_tools: frozenset[str] = field(
        default_factory=lambda: frozenset({"navigate_to_place"})
    )
    human_intervention_error_codes: frozenset[str] = field(
        default_factory=lambda: frozenset({"approval_denied", "stop_requested"})
    )

    def plan_recovery(
        self,
        tool_name: str,
        *,
        retry_allowed: bool,
        error_code: str | None = None,
        retryable: bool = True,
    ) -> RecoveryDecision:
        if error_code in self.human_intervention_error_codes:
            return RecoveryDecision(
                action=RecoveryAction.BLOCK_FOR_OPERATOR,
                requires_human=True,
                should_retry=False,
                reason="Failure requires operator intervention.",
            )
        if not retryable or not retry_allowed:
            return RecoveryDecision(
                action=RecoveryAction.FAIL_TASK,
                requires_human=False,
                should_retry=False,
                reason="Retry budget exhausted or failure is not retryable.",
            )
        if tool_name in self.relocalize_first_tools:
            return RecoveryDecision(
                action=RecoveryAction.RELOCALIZE_THEN_RETRY,
                requires_human=False,
                should_retry=True,
                reason="Retryable navigation failure should relocalize before retry.",
            )
        return RecoveryDecision(
            action=RecoveryAction.RETRY_STEP,
            requires_human=False,
            should_retry=True,
            reason="Retryable step failure can retry directly.",
        )


@dataclass(frozen=True, slots=True)
class InconclusivePolicy:
    """Threshold checks for low-confidence evidence handling."""

    minimum_confidence: float = 0.7

    def is_inconclusive(self, confidence: float | None, *, minimum: float | None = None) -> bool:
        if confidence is None:
            return True
        threshold = self.minimum_confidence if minimum is None else minimum
        return confidence < threshold


__all__ = [
    "InconclusivePolicy",
    "RecoveryAction",
    "RecoveryDecision",
    "RecoveryPolicy",
    "RetryPolicy",
    "TimeoutPolicy",
]
