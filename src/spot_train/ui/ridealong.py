"""Ridealong status view entrypoints."""

from __future__ import annotations

import os
import time
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from spot_train.memory.repository import WorldRepository
from spot_train.models import TaskStatus

if TYPE_CHECKING:
    from spot_train.adapters.spot import SpotStopState


@runtime_checkable
class _StopStateProvider(Protocol):
    @property
    def stop_state(self) -> SpotStopState: ...


class RidealongUI:
    """Minimal terminal-based ridealong UI for live task monitoring."""

    def __init__(
        self,
        repository: WorldRepository,
        spot_adapter: _StopStateProvider | None = None,
    ) -> None:
        self.repository = repository
        self.spot_adapter = spot_adapter

    def render_status(self, task_id: str | None) -> str:
        """Build a text-based status display for the given task."""
        lines: list[str] = ["=== Spot-Train Ridealong ===", ""]

        # Stop state
        if self.spot_adapter is not None:
            state = self.spot_adapter.stop_state
            label = "** STOP REQUESTED **" if state.value == "stop_requested" else "CLEAR"
            lines.append(f"Stop state: {label}")
        else:
            lines.append("Stop state: N/A (no adapter)")
        lines.append("")

        if task_id is None:
            lines.append("No active task.")
            return "\n".join(lines)

        task = self.repository.get_task(task_id)
        if task is None:
            lines.append(f"Task {task_id} not found.")
            return "\n".join(lines)

        # Task info
        lines.append(f"Task:        {task.task_id}")
        lines.append(f"Instruction: {task.instruction}")
        lines.append(f"Status:      {task.status}")
        lines.append("")

        # Resolved target
        if task.resolved_target_type and task.resolved_target_id:
            lines.append(f"Target:      {task.resolved_target_type}:{task.resolved_target_id}")
        else:
            lines.append("Target:      (unresolved)")
        lines.append("")

        # Supervisor state
        lines.append(f"Supervisor:  {task.status}")

        # Approval pending
        if task.status == TaskStatus.AWAITING_APPROVAL:
            lines.append(">>> APPROVAL PENDING <<<")
        lines.append("")

        # Latest step
        steps = self.repository.list_task_steps(task_id)
        if steps:
            latest = steps[-1]
            lines.append(f"Latest step: {latest.tool_name} [{latest.step_state}]")
        else:
            lines.append("Latest step: (none)")
        lines.append("")

        # Recent evidence
        observations = self.repository.list_observations(task_id)
        recent_ids = [o.observation_id for o in observations[-5:]]
        lines.append(f"Evidence ({len(observations)} total):")
        if recent_ids:
            for oid in recent_ids:
                lines.append(f"  - {oid}")
        else:
            lines.append("  (none)")
        lines.append("")

        # Condition results
        conditions = self.repository.list_condition_results(task_id)
        lines.append(f"Conditions ({len(conditions)}):")
        if conditions:
            for cr in conditions[-5:]:
                lines.append(f"  - {cr.condition_id}: {cr.result}")
        else:
            lines.append("  (none)")

        return "\n".join(lines)

    def render_once(self, task_id: str | None) -> None:
        """Print status once (useful for scripting)."""
        print(self.render_status(task_id))

    def run_loop(self, task_id: str | None, refresh_interval: float = 2.0) -> None:
        """Clear-and-redraw loop until KeyboardInterrupt."""
        try:
            while True:
                os.system("clear")  # noqa: S605
                print(self.render_status(task_id))
                time.sleep(refresh_interval)
        except KeyboardInterrupt:
            print("\nRidealong exited.")


__all__ = ["RidealongUI"]
