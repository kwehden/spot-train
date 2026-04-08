"""Dynamic map manager — world model as map authority."""

from __future__ import annotations

import os
import queue
import threading
from typing import Any

from spot_train.adapters.spot import (
    SpotNavigationBinding,
    SpotNavigationSurface,
)
from spot_train.memory.repository import WorldRepository
from spot_train.models import AliasType, GraphRef, Place, PlaceAlias


class MapManager:
    """Bidirectional sync between the world DB and GraphNav.

    The world model is the source of truth for named locations.
    GraphNav is the execution substrate for navigation.
    """

    def __init__(
        self,
        repository: WorldRepository,
        graph_nav_client: Any,
        recording_client: Any,
        robot: Any,
        *,
        spot_adapter: Any = None,
        map_dir: str = "data/maps/lab_map",
    ) -> None:
        self.repository = repository
        self._gn = graph_nav_client
        self._rec = recording_client
        self._robot = robot
        self._adapter = spot_adapter
        self._map_dir = map_dir
        self._save_queue: queue.Queue[str] = queue.Queue()
        self._save_thread = threading.Thread(target=self._save_loop, daemon=True)
        self._save_thread.start()

    # -- Public API -------------------------------------------------------

    def create_waypoint_here(self, name: str) -> GraphRef:
        """Record a waypoint at the robot's current position.

        Creates or updates the Place + GraphRef in the world DB and
        registers the navigation binding on the adapter.
        """
        # Create waypoint on the robot
        resp = self._rec.create_waypoint(waypoint_name=name)
        wp_id = resp.created_waypoint.id

        # Auto-create edge to nearest localized waypoint
        self._auto_edge(wp_id)

        # Upsert place in world DB
        alias = name.lower().strip()
        place_id = f"plc_{alias.replace(' ', '_')}"
        existing = self.repository.get_place(place_id)
        if existing is None:
            self.repository.create_place(Place(place_id=place_id, canonical_name=name))
            self.repository.create_place_alias(
                PlaceAlias(
                    place_id=place_id,
                    alias=alias,
                    alias_type=AliasType.OPERATOR_DEFINED,
                )
            )

        # Deactivate old graph refs for this place
        for old_ref in self.repository.list_graph_refs(place_id):
            if old_ref.waypoint_id != wp_id:
                self.repository.connection.execute(
                    "UPDATE graph_refs SET active = 0 WHERE graph_ref_id = ?",
                    (old_ref.graph_ref_id,),
                )
        self.repository.connection.commit()

        # Create new graph ref
        ref = self.repository.create_graph_ref(
            GraphRef(
                place_id=place_id,
                waypoint_id=wp_id,
                anchor_hint=name,
            )
        )

        # Update adapter binding
        if self._adapter is not None:
            self._adapter.register_navigation_binding(
                SpotNavigationBinding(
                    place_id=place_id,
                    surface=SpotNavigationSurface.WAYPOINT,
                    waypoint_id=wp_id,
                    anchor_hint=name,
                )
            )

        self._enqueue_save()
        return ref

    def update_location(self, place_id: str) -> GraphRef | None:
        """Re-record a waypoint at the current position for an existing place."""
        place = self.repository.get_place(place_id)
        if place is None:
            return None
        return self.create_waypoint_here(place.canonical_name)

    def remove_location(self, place_id: str) -> bool:
        """Deactivate all navigation bindings for a place."""
        refs = self.repository.list_graph_refs(place_id)
        if not refs:
            return False
        for ref in refs:
            self.repository.connection.execute(
                "UPDATE graph_refs SET active = 0 WHERE graph_ref_id = ?",
                (ref.graph_ref_id,),
            )
        self.repository.connection.commit()
        self._enqueue_save()
        return True

    def relocalize_best_effort(self, hint_place_id: str | None = None) -> str | None:
        """Try to localize using fiducials, then known waypoints.

        Returns the waypoint_id if successful, None if all fail.
        """
        from bosdyn.api.graph_nav import graph_nav_pb2, nav_pb2
        from bosdyn.client.frame_helpers import get_odom_tform_body
        from bosdyn.client.robot_state import RobotStateClient

        try:
            sc = self._robot.ensure_client(RobotStateClient.default_service_name)
            state = sc.get_robot_state()
            odom = get_odom_tform_body(state.kinematic_state.transforms_snapshot)
        except Exception:
            return None

        set_loc = graph_nav_pb2.SetLocalizationRequest

        # Build ordered list of waypoints to try
        candidates: list[tuple[str, str]] = []  # (wp_id, name)
        if hint_place_id:
            for ref in self.repository.list_graph_refs(hint_place_id):
                if ref.waypoint_id:
                    place = self.repository.get_place(hint_place_id)
                    candidates.append((ref.waypoint_id, place.canonical_name if place else ""))

        # Add all other known waypoints
        for place in self.repository.list_places():
            for ref in self.repository.list_graph_refs(place.place_id):
                if ref.waypoint_id and not any(c[0] == ref.waypoint_id for c in candidates):
                    candidates.append((ref.waypoint_id, place.canonical_name))

        # Strategy 1: fiducials (no waypoint hint needed)
        for fiducial_init in (
            set_loc.FIDUCIAL_INIT_NEAREST,
            set_loc.FIDUCIAL_INIT_NO_FIDUCIAL,
        ):
            for wp_id, _name in candidates or [("", "")]:
                loc = nav_pb2.Localization()
                if wp_id:
                    loc.waypoint_id = wp_id
                    loc.waypoint_tform_body.rotation.w = 1.0
                try:
                    self._gn.set_localization(
                        initial_guess_localization=loc,
                        ko_tform_body=odom.to_proto(),
                        max_distance=20.0,
                        max_yaw=3.14159,
                        fiducial_init=fiducial_init,
                    )
                    result = self._gn.get_localization_state()
                    if result.localization.waypoint_id:
                        return result.localization.waypoint_id
                except Exception:
                    continue

        return None

    def sync_to_robot(self) -> None:
        """Ensure the robot's graph is loaded and bindings are registered."""
        self._upload_if_needed()
        self._sync_bindings()

    def sync_from_robot(self) -> list[str]:
        """Import named waypoints from the robot graph into the world DB."""
        graph = self._gn.download_graph()
        created = []
        for wp in graph.waypoints:
            name = wp.annotations.name
            if not name or name.startswith("waypoint_") or name.startswith("lab_map_"):
                continue
            alias = name.lower().strip()
            place_id = f"plc_{alias.replace(' ', '_')}"
            if self.repository.get_place(place_id) is not None:
                continue
            self.repository.create_place(Place(place_id=place_id, canonical_name=name))
            self.repository.create_place_alias(
                PlaceAlias(
                    place_id=place_id,
                    alias=alias,
                    alias_type=AliasType.OPERATOR_DEFINED,
                )
            )
            self.repository.create_graph_ref(
                GraphRef(
                    place_id=place_id,
                    waypoint_id=wp.id,
                    anchor_hint=name,
                )
            )
            created.append(place_id)
        return created

    # -- Internal ---------------------------------------------------------

    def _auto_edge(self, new_wp_id: str) -> None:
        """Create an edge between the new waypoint and the current localized waypoint."""
        try:
            state = self._gn.get_localization_state()
            current_wp = state.localization.waypoint_id
            if current_wp and current_wp != new_wp_id:
                from bosdyn.api.graph_nav import map_pb2

                edge = map_pb2.Edge()
                edge.id.from_waypoint = current_wp
                edge.id.to_waypoint = new_wp_id
                self._rec.create_edge(edge=edge)
        except Exception:
            pass  # best-effort

    def _upload_if_needed(self) -> None:
        """Upload saved graph if robot has none loaded."""
        from bosdyn.api.graph_nav import map_pb2

        try:
            graph = self._gn.download_graph()
            if list(graph.waypoints):
                return
        except Exception:
            pass

        graph_path = os.path.join(self._map_dir, "graph")
        if not os.path.exists(graph_path):
            return

        with open(graph_path, "rb") as f:
            saved = map_pb2.Graph()
            saved.ParseFromString(f.read())

        print(f"  Uploading graph: {len(saved.waypoints)} waypoints...")
        self._gn.upload_graph(graph=saved, generate_new_anchoring=True)

        for fname in os.listdir(self._map_dir):
            path = os.path.join(self._map_dir, fname)
            try:
                if fname.startswith("waypoint_snapshot_"):
                    with open(path, "rb") as f:
                        snap = map_pb2.WaypointSnapshot()
                        snap.ParseFromString(f.read())
                        self._gn.upload_waypoint_snapshot(snap)
                elif fname.startswith("edge_snapshot_"):
                    with open(path, "rb") as f:
                        snap = map_pb2.EdgeSnapshot()
                        snap.ParseFromString(f.read())
                        self._gn.upload_edge_snapshot(snap)
            except Exception:
                pass

    def _sync_bindings(self) -> None:
        """Register all active graph refs as adapter navigation bindings."""
        if self._adapter is None:
            return
        for place in self.repository.list_places():
            for ref in self.repository.list_graph_refs(place.place_id):
                if ref.waypoint_id:
                    self._adapter.register_navigation_binding(
                        SpotNavigationBinding(
                            place_id=place.place_id,
                            surface=SpotNavigationSurface.WAYPOINT,
                            waypoint_id=ref.waypoint_id,
                            anchor_hint=ref.anchor_hint,
                            relocalization_hint=ref.relocalization_hint_json or {},
                        )
                    )

    def _enqueue_save(self) -> None:
        """Enqueue an async graph save to disk."""
        self._save_queue.put("save")

    def _save_loop(self) -> None:
        """Background thread: saves graph to disk when enqueued."""

        while True:
            try:
                self._save_queue.get(timeout=5)
            except queue.Empty:
                continue

            # Drain any additional queued saves
            while not self._save_queue.empty():
                try:
                    self._save_queue.get_nowait()
                except queue.Empty:
                    break

            try:
                os.makedirs(self._map_dir, exist_ok=True)
                graph = self._gn.download_graph()
                with open(os.path.join(self._map_dir, "graph"), "wb") as f:
                    f.write(graph.SerializeToString())

                for wp in graph.waypoints:
                    if wp.snapshot_id:
                        try:
                            snap = self._gn.download_waypoint_snapshot(wp.snapshot_id)
                            path = os.path.join(
                                self._map_dir,
                                f"waypoint_snapshot_{wp.snapshot_id}",
                            )
                            with open(path, "wb") as f:
                                f.write(snap.SerializeToString())
                        except Exception:
                            pass

                for edge in graph.edges:
                    if edge.snapshot_id:
                        try:
                            snap = self._gn.download_edge_snapshot(edge.snapshot_id)
                            path = os.path.join(
                                self._map_dir,
                                f"edge_snapshot_{edge.snapshot_id}",
                            )
                            with open(path, "wb") as f:
                                f.write(snap.SerializeToString())
                        except Exception:
                            pass
            except Exception:
                pass  # best-effort save
