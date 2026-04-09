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
        self._localized_wp = ""

    def download_graph(self):
        return self._graph

    def upload_graph(self, **kw):
        pass

    def upload_waypoint_snapshot(self, snap):
        pass

    def upload_edge_snapshot(self, snap):
        pass

    def set_localization(self, **kw):
        raise Exception("mock")

    def get_localization_state(self):
        return types.SimpleNamespace(
            localization=types.SimpleNamespace(waypoint_id=self._localized_wp)
        )


class MockRecordingClient:
    def __init__(self):
        self._seq = 0

    def create_waypoint(self, waypoint_name=None, **kw):
        self._seq += 1
        wp_id = f"mock_wp_{self._seq}"
        wp = types.SimpleNamespace(id=wp_id, annotations=types.SimpleNamespace(name=waypoint_name))
        return types.SimpleNamespace(created_waypoint=wp)

    def create_edge(self, **kw):
        pass


def _make_wp(wp_id: str, name: str) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        id=wp_id, annotations=types.SimpleNamespace(name=name), snapshot_id=None
    )


def _make_repo() -> WorldRepository:
    repo = WorldRepository.connect(initialize=False)
    create_schema(repo.connection)
    return repo


def _make_manager(repo, waypoints=None, recording=True):
    gn = MockGraphNavClient(waypoints=waypoints)
    rec = MockRecordingClient() if recording else None
    mm = MapManager(repo, gn, rec, None, map_dir="/tmp/test_maps")
    return mm, gn


def test_sync_from_robot_imports_named_waypoints():
    repo = _make_repo()
    wps = [
        _make_wp("wp_1", "home"),
        _make_wp("wp_2", "office"),
        _make_wp("wp_3", "waypoint_1"),
    ]
    mm, _gn = _make_manager(repo, waypoints=wps)
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

    mm, _gn = _make_manager(repo)
    try:
        mm.remove_location("plc_x")
        assert repo.list_graph_refs("plc_x") == []
    finally:
        mm.stop()


def test_relocalize_best_effort_returns_none_when_no_candidates():
    repo = _make_repo()
    mm, _gn = _make_manager(repo)
    try:
        result = mm.relocalize_best_effort()
        assert result is None
    finally:
        mm.stop()


def test_stop_terminates_save_thread():
    repo = _make_repo()
    mm, _gn = _make_manager(repo)
    assert mm._save_thread.is_alive()
    mm.stop()
    assert not mm._save_thread.is_alive()


def test_create_waypoint_here_creates_place_and_ref():
    repo = _make_repo()
    mm, gn = _make_manager(repo)
    ref = mm.create_waypoint_here("break room")
    assert ref.place_id == "plc_break_room"
    assert ref.waypoint_id.startswith("mock_wp_")
    # Place created
    place = repo.get_place("plc_break_room")
    assert place is not None
    assert place.canonical_name == "break room"
    # Graph ref created
    refs = repo.list_graph_refs("plc_break_room")
    assert len(refs) == 1
    assert refs[0].waypoint_id == ref.waypoint_id
    # Alias created
    aliases = repo.list_place_aliases("plc_break_room")
    assert any(a.alias == "break room" for a in aliases)
    mm.stop()


def test_create_waypoint_here_updates_existing_place():
    repo = _make_repo()
    mm, gn = _make_manager(repo)
    ref1 = mm.create_waypoint_here("lab")
    ref2 = mm.create_waypoint_here("lab")
    # Old ref deactivated, new ref active
    assert ref1.waypoint_id != ref2.waypoint_id
    refs = repo.list_graph_refs("plc_lab")
    assert len(refs) == 1
    assert refs[0].waypoint_id == ref2.waypoint_id
    mm.stop()


def test_sync_to_robot_uploads_when_empty(tmp_path):
    import os

    # Create a minimal saved graph
    graph_dir = str(tmp_path / "maps")
    os.makedirs(graph_dir)
    # Write an empty graph file
    from bosdyn.api.graph_nav import map_pb2

    graph = map_pb2.Graph()
    with open(os.path.join(graph_dir, "graph"), "wb") as f:
        f.write(graph.SerializeToString())

    repo = _make_repo()
    gn = MockGraphNavClient(waypoints=[])
    rec = MockRecordingClient()
    mm = MapManager(repo, gn, rec, None, map_dir=graph_dir)
    mm.sync_to_robot()
    # No error raised — upload path exercised
    mm.stop()
