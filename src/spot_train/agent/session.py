"""Agent session bootstrap."""

from __future__ import annotations

import os

from spot_train.adapters.approval import FakeApprovalAdapter
from spot_train.adapters.perception import FakePerceptionAdapter
from spot_train.adapters.spot import FakeSpotAdapter
from spot_train.agent import tools as agent_tools
from spot_train.memory.repository import WorldRepository
from spot_train.memory.schema import create_schema
from spot_train.observability import configure_logging
from spot_train.safety.operator_event_router import OperatorEventRouter
from spot_train.supervisor.policies import (
    InconclusivePolicy,
    RecoveryPolicy,
    RetryPolicy,
    TimeoutPolicy,
)
from spot_train.supervisor.runner import SupervisorRunner
from spot_train.supervisor.state_machine import SupervisorStateMachine
from spot_train.tools.handlers import ToolHandlerService


def create_dry_run_session() -> dict:
    """Bootstrap a complete dry-run session with fake adapters."""
    configure_logging()
    db_path = os.environ.get("SPOT_TRAIN_DB_PATH", ":memory:")
    repo = WorldRepository.connect(db_path, initialize=False)
    create_schema(repo.connection)
    repo.seed_minimal_lab_world()

    spot = FakeSpotAdapter()
    perception = FakePerceptionAdapter()
    approval = FakeApprovalAdapter()
    runner = SupervisorRunner(
        repo,
        state_machine=SupervisorStateMachine,
        retry_policy=RetryPolicy(),
        timeout_policy=TimeoutPolicy(),
        recovery_policy=RecoveryPolicy(),
        inconclusive_policy=InconclusivePolicy(),
    )
    handler = ToolHandlerService(
        repo, runner=runner, spot_adapter=spot, perception_adapter=perception
    )
    agent_tools.configure(handler)
    event_router = OperatorEventRouter(repository=repo, runner=runner)

    return {
        "repository": repo,
        "spot_adapter": spot,
        "perception_adapter": perception,
        "approval_adapter": approval,
        "runner": runner,
        "handler": handler,
        "event_router": event_router,
    }
