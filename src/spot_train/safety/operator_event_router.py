"""Operator event router — maps operator actions to supervisor transitions."""

from __future__ import annotations

from spot_train.memory.repository import WorldRepository
from spot_train.models import ModelSource, OperatorEvent, OperatorEventType
from spot_train.supervisor.runner import SupervisorRunner
from spot_train.supervisor.state_machine import SupervisorEvent

_EVENT_MAP: dict[OperatorEventType, SupervisorEvent] = {
    OperatorEventType.APPROVAL_GRANTED: SupervisorEvent.APPROVAL_GRANTED,
    OperatorEventType.APPROVAL_DENIED: SupervisorEvent.APPROVAL_DENIED,
    OperatorEventType.STOP_REQUESTED: SupervisorEvent.CANCEL,
    OperatorEventType.TASK_CANCEL_REQUESTED: SupervisorEvent.CANCEL,
}


class OperatorEventRouter:
    """Persists operator events and routes them into supervisor state transitions."""

    def __init__(
        self,
        repository: WorldRepository,
        runner: SupervisorRunner | None = None,
    ) -> None:
        self.repository = repository
        self.runner = runner

    def route_event(self, event: OperatorEvent) -> OperatorEvent:
        """Persist *event* and, when a runner is attached, apply the mapped transition."""
        event = self.repository.create_operator_event(event)
        supervisor_event = _EVENT_MAP.get(event.event_type)
        if supervisor_event is not None and self.runner is not None and event.task_id is not None:
            task = self.repository.get_task(event.task_id)
            if task is not None and self.runner.state_machine is not None:
                transition = self.runner.state_machine.apply_event(task.status, supervisor_event)
                self.repository.update_task_status(task.task_id, status=transition.current)
        return event

    def create_and_route(
        self,
        event_type: OperatorEventType,
        task_id: str | None = None,
        operator_id: str | None = None,
        source: ModelSource | str = ModelSource.TERMINAL,
        details: dict | None = None,
    ) -> OperatorEvent:
        """Build an :class:`OperatorEvent` and route it in one call."""
        event = OperatorEvent(
            event_type=event_type,
            task_id=task_id,
            operator_id=operator_id,
            source=source,
            details_json=details or {},
        )
        return self.route_event(event)


__all__ = ["OperatorEventRouter"]
