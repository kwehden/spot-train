"""Tests for spot_train.agent.tools wiring."""

from __future__ import annotations

from spot_train.adapters.spot import (
    FakeSpotAdapter,
    SpotNavigationIntent,
    SpotStopState,
)
from spot_train.agent.session import _sync_navigation_bindings
from spot_train.agent.tools import (
    clear_stop,
    configure,
    get_active_task,
    power_on_robot,
    request_stop,
    resolve_target,
    set_active_task,
)
from spot_train.memory.repository import WorldRepository
from spot_train.memory.schema import create_schema
from spot_train.models import GraphRef, Task
from spot_train.tools.handlers import ToolHandlerService


def _make_repo():
    repo = WorldRepository.connect(initialize=False)
    create_schema(repo.connection)
    repo.seed_minimal_lab_world()
    return repo


def test_set_and_get_active_task():
    set_active_task("t1")
    assert get_active_task() == "t1"
    set_active_task(None)
    assert get_active_task() is None


def test_resolve_target_passes_task_id():
    repo = _make_repo()
    handler = ToolHandlerService(repo)
    configure(handler)
    set_active_task("task-1")
    result = resolve_target(name="optics bench")
    assert result["status"] == "success"
    repo.close()


def test_request_stop_tool_with_fake_adapter():
    set_active_task(None)
    repo = _make_repo()
    adapter = FakeSpotAdapter()
    from spot_train.supervisor.runner import SupervisorRunner
    from spot_train.supervisor.state_machine import SupervisorStateMachine

    runner = SupervisorRunner(repo, state_machine=SupervisorStateMachine)
    handler = ToolHandlerService(repo, runner=runner, spot_adapter=adapter)
    configure(handler)
    task = repo.create_task(Task(instruction="stop test"))
    set_active_task(task.task_id)
    result = request_stop()
    assert result.get("data", {}).get("stop_state") == "stop_requested" or "stop" in str(result)
    assert adapter.stop_state is SpotStopState.STOP_REQUESTED
    set_active_task(None)
    repo.close()


def test_clear_stop_tool_with_fake_adapter():
    set_active_task(None)
    repo = _make_repo()
    adapter = FakeSpotAdapter()
    from spot_train.supervisor.runner import SupervisorRunner
    from spot_train.supervisor.state_machine import SupervisorStateMachine

    runner = SupervisorRunner(repo, state_machine=SupervisorStateMachine)
    handler = ToolHandlerService(repo, runner=runner, spot_adapter=adapter)
    configure(handler)
    task = repo.create_task(Task(instruction="clear test"))
    set_active_task(task.task_id)
    adapter.request_stop(reason="test")
    clear_stop()
    assert adapter.stop_state is SpotStopState.CLEAR
    set_active_task(None)
    repo.close()


def test_power_tools_route_through_supervisor():
    """Power tools go through handler/supervisor — require runner + task_id."""
    set_active_task(None)
    repo = _make_repo()
    handler = ToolHandlerService(repo)
    configure(handler)
    result = power_on_robot()
    # No runner configured → policy rejection
    assert result["status"] == "error"
    assert "runner" in result["error"]["code"]
    repo.close()


def test_sync_navigation_bindings_wires_graph_refs():
    repo = _make_repo()
    repo.create_graph_ref(
        GraphRef(
            graph_ref_id="gref_1",
            place_id="plc_optics_bench",
            graph_id="graph_1",
            waypoint_id="wp_42",
            anchor_hint="bench_anchor",
        )
    )
    adapter = FakeSpotAdapter()
    _sync_navigation_bindings(repo, adapter)
    binding = adapter.map_navigation_intent(SpotNavigationIntent(place_id="plc_optics_bench"))
    assert binding.waypoint_id == "wp_42"
    repo.close()
