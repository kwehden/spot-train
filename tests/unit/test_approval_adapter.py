from __future__ import annotations

from spot_train.adapters.approval import FakeApprovalAdapter


def test_fake_approval_adapter_auto_approves_by_default() -> None:
    adapter = FakeApprovalAdapter()
    outcome = adapter.request_approval("task_1", "navigate to bench")

    assert outcome.approved is True


def test_fake_approval_adapter_denies_when_configured() -> None:
    adapter = FakeApprovalAdapter(auto_approve=False)
    outcome = adapter.request_approval("task_1", "navigate to bench")

    assert outcome.approved is False
    assert "task_1" in adapter.pending_approvals


def test_fake_approval_adapter_pending_list_starts_empty() -> None:
    adapter = FakeApprovalAdapter()

    assert adapter.pending_approvals == []
