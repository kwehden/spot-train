"""Operator approval integration boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from spot_train.models import ApprovalProfile


@dataclass(frozen=True, slots=True)
class ApprovalOutcome:
    """Result of an approval request."""

    approved: bool
    operator_id: str | None = None
    reason: str | None = None


@runtime_checkable
class ApprovalAdapter(Protocol):
    """Protocol for approval integration adapters."""

    @property
    def pending_approvals(self) -> list[str]:
        """Return task IDs with pending approval requests."""
        ...

    def request_approval(
        self,
        task_id: str,
        action_description: str,
        profile: ApprovalProfile | None = None,
    ) -> ApprovalOutcome:
        """Request operator approval for a task action."""
        ...


class FakeApprovalAdapter:
    """Test adapter that auto-approves by default."""

    def __init__(self, *, auto_approve: bool = True, operator_id: str = "fake-operator") -> None:
        self._auto_approve = auto_approve
        self._operator_id = operator_id
        self._pending: list[str] = []

    @property
    def pending_approvals(self) -> list[str]:
        return list(self._pending)

    def request_approval(
        self,
        task_id: str,
        action_description: str,
        profile: ApprovalProfile | None = None,
    ) -> ApprovalOutcome:
        if self._auto_approve:
            return ApprovalOutcome(approved=True, operator_id=self._operator_id)
        self._pending.append(task_id)
        return ApprovalOutcome(
            approved=False,
            operator_id=self._operator_id,
            reason="Denied by fake adapter",
        )


__all__ = ["ApprovalAdapter", "ApprovalOutcome", "FakeApprovalAdapter"]
