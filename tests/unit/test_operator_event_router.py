from __future__ import annotations

import types

from spot_train.memory.repository import WorldRepository
from spot_train.memory.schema import create_schema
from spot_train.models import (
    ModelSource,
    OperatorEventType,
    Task,
    TaskStatus,
)
from spot_train.safety.operator_event_router import OperatorEventRouter
from spot_train.supervisor.state_machine import SupervisorStateMachine


def _make_repo() -> WorldRepository:
    repo = WorldRepository.connect(initialize=False)
    create_schema(repo.connection)
    return repo


def _make_runner() -> types.SimpleNamespace:
    return types.SimpleNamespace(state_machine=SupervisorStateMachine)


def test_route_event_persists_operator_event() -> None:
    repo = _make_repo()
    router = OperatorEventRouter(repository=repo)
    from spot_train.models import OperatorEvent

    task = repo.create_task(Task(instruction="test"))
    event = OperatorEvent(
        event_type=OperatorEventType.APPROVAL_GRANTED,
        task_id=task.task_id,
        source=ModelSource.TERMINAL,
    )
    router.route_event(event)

    events = repo.list_operator_events(task_id=task.task_id)
    assert len(events) == 1
    assert events[0].event_type == OperatorEventType.APPROVAL_GRANTED


def test_route_approval_granted_transitions_task_to_executing() -> None:
    repo = _make_repo()
    task = repo.create_task(Task(instruction="test", status=TaskStatus.AWAITING_APPROVAL))
    router = OperatorEventRouter(repository=repo, runner=_make_runner())

    from spot_train.models import OperatorEvent

    router.route_event(
        OperatorEvent(
            event_type=OperatorEventType.APPROVAL_GRANTED,
            task_id=task.task_id,
            source=ModelSource.TERMINAL,
        )
    )

    assert repo.get_task(task.task_id).status == TaskStatus.EXECUTING


def test_route_approval_denied_transitions_task_to_blocked() -> None:
    repo = _make_repo()
    task = repo.create_task(Task(instruction="test", status=TaskStatus.AWAITING_APPROVAL))
    router = OperatorEventRouter(repository=repo, runner=_make_runner())

    from spot_train.models import OperatorEvent

    router.route_event(
        OperatorEvent(
            event_type=OperatorEventType.APPROVAL_DENIED,
            task_id=task.task_id,
            source=ModelSource.TERMINAL,
        )
    )

    assert repo.get_task(task.task_id).status == TaskStatus.BLOCKED


def test_route_stop_requested_cancels_task() -> None:
    repo = _make_repo()
    task = repo.create_task(Task(instruction="test", status=TaskStatus.EXECUTING))
    router = OperatorEventRouter(repository=repo, runner=_make_runner())

    from spot_train.models import OperatorEvent

    router.route_event(
        OperatorEvent(
            event_type=OperatorEventType.STOP_REQUESTED,
            task_id=task.task_id,
            source=ModelSource.TERMINAL,
        )
    )

    assert repo.get_task(task.task_id).status == TaskStatus.CANCELLED


def test_route_cancel_requested_cancels_task() -> None:
    repo = _make_repo()
    task = repo.create_task(Task(instruction="test", status=TaskStatus.EXECUTING))
    router = OperatorEventRouter(repository=repo, runner=_make_runner())

    from spot_train.models import OperatorEvent

    router.route_event(
        OperatorEvent(
            event_type=OperatorEventType.TASK_CANCEL_REQUESTED,
            task_id=task.task_id,
            source=ModelSource.TERMINAL,
        )
    )

    assert repo.get_task(task.task_id).status == TaskStatus.CANCELLED


def test_create_and_route_convenience_method() -> None:
    repo = _make_repo()
    router = OperatorEventRouter(repository=repo)
    task = repo.create_task(Task(instruction="test"))

    event = router.create_and_route(
        event_type=OperatorEventType.APPROVAL_GRANTED,
        task_id=task.task_id,
        operator_id="op_1",
    )

    assert event.event_type == OperatorEventType.APPROVAL_GRANTED
    assert event.task_id == task.task_id
    assert event.operator_id == "op_1"
    events = repo.list_operator_events(task_id=task.task_id)
    assert len(events) == 1
