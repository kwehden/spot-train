from __future__ import annotations

from spot_train.adapters.spot import FakeSpotAdapter, SpotStopState
from spot_train.memory.repository import WorldRepository
from spot_train.memory.schema import create_schema
from spot_train.models import ModelSource, OperatorEventType, Task
from spot_train.safety.terminal_estop import TerminalStopController


def _make_repo() -> WorldRepository:
    repo = WorldRepository.connect(initialize=False)
    create_schema(repo.connection)
    return repo


def test_request_stop_calls_adapter_and_persists_event() -> None:
    adapter = FakeSpotAdapter()
    repo = _make_repo()
    task = repo.create_task(Task(instruction="test"))
    controller = TerminalStopController(adapter=adapter, repository=repo)

    controller.request_stop("safety concern", "op1", task.task_id)

    assert adapter.stop_state == SpotStopState.STOP_REQUESTED
    events = repo.list_operator_events(task_id=task.task_id)
    assert len(events) == 1
    assert events[0].event_type == OperatorEventType.STOP_REQUESTED
    assert events[0].source == ModelSource.TERMINAL


def test_request_stop_fires_supervisor_callback() -> None:
    adapter = FakeSpotAdapter()
    repo = _make_repo()
    task = repo.create_task(Task(instruction="test"))
    called = []
    controller = TerminalStopController(
        adapter=adapter, repository=repo, supervisor_callback=lambda: called.append(True)
    )

    controller.request_stop("reason", "op1", task.task_id)

    assert called == [True]


def test_clear_stop_resets_adapter_state() -> None:
    adapter = FakeSpotAdapter()
    repo = _make_repo()
    controller = TerminalStopController(adapter=adapter, repository=repo)

    controller.request_stop("reason")
    controller.clear_stop()

    assert adapter.stop_state == SpotStopState.CLEAR


def test_status_reflects_adapter_stop_state() -> None:
    adapter = FakeSpotAdapter()
    repo = _make_repo()
    controller = TerminalStopController(adapter=adapter, repository=repo)

    assert controller.status() == SpotStopState.CLEAR

    controller.request_stop("reason")

    assert controller.status() == SpotStopState.STOP_REQUESTED
