"""Tests for MapManager."""

from __future__ import annotations

import types

from spot_train.memory.map_manager import MapManager
from spot_train.memory.repository import WorldRepository
from spot_train.memory.schema import create_schema
from spot_train.models import GraphRef, Place


class MockGraphNavClient:
    def __init__(self, waypoints=None):
        self._graph = types.SimpleNamespace(waypoints=waypoints or [], edges=[])

    def download_graph(self):
        return self._graph

    def upload_graph(self, **kw):
        pass

    def set_localization(self, **kw):
        raise Exception("mock")

    def get_localization_state(self):
        return types.SimpleNamespace(localization=types.SimpleNamespace(waypoint_id=""))


def _make_wp(wp_id: str, name: str) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        id=wp_id, annotations=types.SimpleNamespace(name=name), snapshot_id=None
    )


def _make_repo() -> WorldRepository:
    repo = WorldRepository.connect(initialize=False)
    create_schema(repo.connection)
    return repo


def _make_manager(repo, waypoints=None):
    gn = MockGraphNavClient(waypoints=waypoints)
    mm = MapManager(repo, gn, None, None, map_dir="/tmp/test_maps")
    return mm


def test_sync_from_robot_imports_named_waypoints():
    repo = _make_repo()
    wps = [
        _make_wp("wp_1", "home"),
        _make_wp("wp_2", "office"),
        _make_wp("wp_3", "waypoint_1"),
    ]
    mm = _make_manager(repo, waypoints=wps)
    try:
        created = mm.sync_from_robot()
        assert len(created) == 2
        assert repo.get_place("plc_home") is not None
        assert repo.get_place("plc_office") is not None
        assert repo.get_place("plc_waypoint_1") is None
    finally:
        mm.stop()


def test_remove_location_deactivates_refs():
    repo = _make_repo()
    repo.create_place(Place(place_id="plc_x", canonical_name="X"))
    repo.create_graph_ref(GraphRef(place_id="plc_x", waypoint_id="wp_99", anchor_hint="X"))
    assert len(repo.list_graph_refs("plc_x")) == 1

    mm = _make_manager(repo)
    try:
        mm.remove_location("plc_x")
        assert repo.list_graph_refs("plc_x") == []
    finally:
        mm.stop()


def test_relocalize_best_effort_returns_none_when_no_candidates():
    repo = _make_repo()
    mm = _make_manager(repo)
    try:
        result = mm.relocalize_best_effort()
        assert result is None
    finally:
        mm.stop()


def test_stop_terminates_save_thread():
    repo = _make_repo()
    mm = _make_manager(repo)
    assert mm._save_thread.is_alive()
    mm.stop()
    assert not mm._save_thread.is_alive()
