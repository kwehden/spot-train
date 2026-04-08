"""Terminal-based stop-control entrypoints."""

from __future__ import annotations

import sys
from typing import Callable, Protocol

from spot_train.adapters.spot import SpotStopOutcome, SpotStopState
from spot_train.models import ModelSource, OperatorEvent, OperatorEventType


class _StopAdapter(Protocol):
    def request_stop(self, *, reason: str | None = None) -> SpotStopOutcome: ...
    def clear_stop(self) -> SpotStopOutcome: ...
    @property
    def stop_state(self) -> SpotStopState: ...


class _EventRepo(Protocol):
    def create_operator_event(self, event: OperatorEvent) -> OperatorEvent: ...


class TerminalStopController:
    """Standalone stop-control that works independently of the main agent loop."""

    def __init__(
        self,
        adapter: _StopAdapter,
        repository: _EventRepo,
        supervisor_callback: Callable[[], None] | None = None,
    ) -> None:
        self._adapter = adapter
        self._repository = repository
        self._supervisor_callback = supervisor_callback

    def request_stop(
        self,
        reason: str,
        operator_id: str | None = None,
        task_id: str | None = None,
    ) -> SpotStopOutcome:
        """Request stop, persist event, and optionally signal supervisor."""
        outcome = self._adapter.request_stop(reason=reason)
        self._repository.create_operator_event(
            OperatorEvent(
                task_id=task_id,
                event_type=OperatorEventType.STOP_REQUESTED,
                operator_id=operator_id,
                source=ModelSource.TERMINAL,
                details_json={"reason": reason},
            )
        )
        if self._supervisor_callback is not None:
            self._supervisor_callback()
        return outcome

    def clear_stop(self) -> SpotStopOutcome:
        """Clear the adapter stop state."""
        return self._adapter.clear_stop()

    def status(self) -> SpotStopState:
        """Return current stop state."""
        return self._adapter.stop_state

    def run_interactive(
        self,
        operator_id: str | None = None,
        task_id: str | None = None,
    ) -> None:
        """Run a blocking stdin loop for independent stop control (NFR-011)."""
        _write = sys.stdout.write
        _flush = sys.stdout.flush
        _write("Stop controller ready. Commands: stop, clear, status, quit\n")
        _flush()
        for line in sys.stdin:
            cmd = line.strip().lower()
            if cmd == "stop":
                outcome = self.request_stop("operator terminal stop", operator_id, task_id)
                _write(f"{outcome.message}\n")
            elif cmd == "clear":
                outcome = self.clear_stop()
                _write(f"{outcome.message}\n")
            elif cmd == "status":
                _write(f"{self.status().value}\n")
            elif cmd == "quit":
                break
            _flush()


__all__ = ["TerminalStopController"]
