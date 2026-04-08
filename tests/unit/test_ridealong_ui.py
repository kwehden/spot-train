from __future__ import annotations

from spot_train.adapters.spot import FakeSpotAdapter, SpotStopState
from spot_train.memory.repository import WorldRepository
from spot_train.memory.schema import create_schema
from spot_train.models import Task, TaskStatus
from spot_train.ui.ridealong import RidealongUI


def _make_repo() -> WorldRepository:
    repo = WorldRepository.connect(initialize=False)
    create_schema(repo.connection)
    return repo


def test_render_status_no_task() -> None:
    repo = _make_repo()
    ui = RidealongUI(repository=repo)

    output = ui.render_status(None)

    assert "No active task" in output


def test_render_status_missing_task() -> None:
    repo = _make_repo()
    ui = RidealongUI(repository=repo)

    output = ui.render_status("nonexistent")

    assert "not found" in output


def test_render_status_shows_task_info() -> None:
    repo = _make_repo()
    task = repo.create_task(Task(instruction="check the optics bench"))
    ui = RidealongUI(repository=repo)

    output = ui.render_status(task.task_id)

    assert "check the optics bench" in output
    assert str(task.status) in output


def test_render_status_shows_approval_pending() -> None:
    repo = _make_repo()
    task = repo.create_task(Task(instruction="test", status=TaskStatus.AWAITING_APPROVAL))
    ui = RidealongUI(repository=repo)

    output = ui.render_status(task.task_id)

    assert "APPROVAL PENDING" in output


def test_render_status_shows_stop_state() -> None:
    repo = _make_repo()
    adapter = FakeSpotAdapter()
    adapter.request_stop(reason="emergency")
    task = repo.create_task(Task(instruction="test"))
    ui = RidealongUI(repository=repo, spot_adapter=adapter)

    # Adapter is in STOP_REQUESTED state.
    assert adapter.stop_state == SpotStopState.STOP_REQUESTED

    output = ui.render_status(task.task_id)

    assert "STOP REQUESTED" in output
