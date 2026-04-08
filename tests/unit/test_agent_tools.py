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
from spot_train.models import GraphRef
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
    repo = _make_repo()
    adapter = FakeSpotAdapter()
    handler = ToolHandlerService(repo)
    configure(handler, spot_adapter=adapter)
    result = request_stop()
    assert result["stop_state"] == "stop_requested"
    assert adapter.stop_state is SpotStopState.STOP_REQUESTED
    repo.close()


def test_clear_stop_tool_with_fake_adapter():
    repo = _make_repo()
    adapter = FakeSpotAdapter()
    handler = ToolHandlerService(repo)
    configure(handler, spot_adapter=adapter)
    request_stop()
    result = clear_stop()
    assert result["stop_state"] == "clear"
    assert adapter.stop_state is SpotStopState.CLEAR
    repo.close()


def test_power_tools_return_error_in_dry_run():
    repo = _make_repo()
    adapter = FakeSpotAdapter()
    handler = ToolHandlerService(repo)
    configure(handler, spot_adapter=adapter)
    result = power_on_robot()
    assert result["status"] == "error"
    assert "dry-run" in result["message"].lower()
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
