"""Agent session bootstrap."""

from __future__ import annotations

import os

from spot_train.adapters.approval import FakeApprovalAdapter
from spot_train.adapters.perception import FakePerceptionAdapter, RealPerceptionAdapter
from spot_train.adapters.spot import FakeSpotAdapter, SpotNavigationBinding, SpotNavigationSurface
from spot_train.agent import tools as agent_tools
from spot_train.memory.repository import WorldRepository
from spot_train.memory.schema import create_schema
from spot_train.observability import configure_logging
from spot_train.safety.operator_event_router import OperatorEventRouter
from spot_train.supervisor.policies import (
    InconclusivePolicy,
    RecoveryPolicy,
    RetryPolicy,
    TimeoutPolicy,
)
from spot_train.supervisor.runner import SupervisorRunner
from spot_train.supervisor.state_machine import SupervisorStateMachine
from spot_train.tools.handlers import ToolHandlerService


def _make_runner_and_handler(repo, *, spot, perception):
    runner = SupervisorRunner(
        repo,
        state_machine=SupervisorStateMachine,
        retry_policy=RetryPolicy(),
        timeout_policy=TimeoutPolicy(),
        recovery_policy=RecoveryPolicy(),
        inconclusive_policy=InconclusivePolicy(),
    )
    handler = ToolHandlerService(
        repo, runner=runner, spot_adapter=spot, perception_adapter=perception
    )
    agent_tools.configure(handler, spot_adapter=spot)
    event_router = OperatorEventRouter(repository=repo, runner=runner)
    return runner, handler, event_router


def _sync_navigation_bindings(repo, spot_adapter):
    """Register navigation bindings on the adapter from repository graph refs."""
    for place in repo.list_places():
        refs = repo.list_graph_refs(place.place_id)
        for ref in refs:
            if ref.waypoint_id:
                spot_adapter.register_navigation_binding(
                    SpotNavigationBinding(
                        place_id=place.place_id,
                        surface=SpotNavigationSurface.WAYPOINT,
                        waypoint_id=ref.waypoint_id,
                        mission_id=ref.graph_id,
                        anchor_hint=ref.anchor_hint,
                        relocalization_hint=ref.relocalization_hint_json or {},
                    )
                )


def _upload_graph_if_needed(spot_adapter):
    """Upload the saved GraphNav map if the robot has no graph loaded."""
    import os

    from bosdyn.api.graph_nav import map_pb2

    try:
        graph = spot_adapter._graph_nav.download_graph()
        wp_count = len(list(graph.waypoints))
        if wp_count > 0:
            print(f"  Graph already loaded: {wp_count} waypoints")
            return
    except Exception:
        pass

    map_dir = os.path.join("data", "maps", "lab_map")
    graph_path = os.path.join(map_dir, "graph")
    if not os.path.exists(graph_path):
        print("  No saved map at data/maps/lab_map/")
        return

    with open(graph_path, "rb") as f:
        saved = map_pb2.Graph()
        saved.ParseFromString(f.read())

    print(f"  Uploading graph: {len(saved.waypoints)} waypoints...")
    gn = spot_adapter._graph_nav
    gn.upload_graph(graph=saved, generate_new_anchoring=True)

    wp_uploaded = 0
    edge_uploaded = 0
    for fname in os.listdir(map_dir):
        path = os.path.join(map_dir, fname)
        if fname.startswith("waypoint_snapshot_"):
            with open(path, "rb") as f:
                snap = map_pb2.WaypointSnapshot()
                snap.ParseFromString(f.read())
                try:
                    gn.upload_waypoint_snapshot(snap)
                    wp_uploaded += 1
                except Exception:
                    pass
        elif fname.startswith("edge_snapshot_"):
            with open(path, "rb") as f:
                snap = map_pb2.EdgeSnapshot()
                snap.ParseFromString(f.read())
                try:
                    gn.upload_edge_snapshot(snap)
                    edge_uploaded += 1
                except Exception:
                    pass
    print(f"  Uploaded {wp_uploaded} waypoint + {edge_uploaded} edge snapshots")


def create_dry_run_session() -> dict:
    """Bootstrap a complete dry-run session with fake adapters."""
    configure_logging()
    db_path = os.environ.get("SPOT_TRAIN_DB_PATH", ":memory:")
    repo = WorldRepository.connect(db_path, initialize=False)
    create_schema(repo.connection)
    repo.seed_minimal_lab_world()

    spot = FakeSpotAdapter()
    perception = FakePerceptionAdapter()
    approval = FakeApprovalAdapter()
    runner, handler, event_router = _make_runner_and_handler(repo, spot=spot, perception=perception)
    _sync_navigation_bindings(repo, spot)

    return {
        "repository": repo,
        "spot_adapter": spot,
        "perception_adapter": perception,
        "approval_adapter": approval,
        "runner": runner,
        "handler": handler,
        "event_router": event_router,
    }


def create_robot_session() -> dict:
    """Bootstrap a session connected to the real Spot robot.

    Requires SPOT_HOSTNAME, SPOT_USERNAME, SPOT_PASSWORD in the environment.
    Perception remains fake until a real adapter is implemented.
    """
    from spot_train.adapters.spot import RealSpotAdapter
    from spot_train.memory.map_manager import MapManager

    configure_logging(console=False)
    db_path = os.environ.get("SPOT_TRAIN_DB_PATH", "data/world.sqlite")
    repo = WorldRepository.connect(db_path, initialize=False)
    create_schema(repo.connection)
    if not repo.list_places():
        repo.seed_minimal_lab_world()

    spot = RealSpotAdapter.connect()
    spot.acquire_lease()

    from bosdyn.client.graph_nav import GraphNavClient
    from bosdyn.client.recording import GraphNavRecordingServiceClient

    gn = spot._robot.ensure_client(GraphNavClient.default_service_name)
    rec = spot._robot.ensure_client(GraphNavRecordingServiceClient.default_service_name)
    map_mgr = MapManager(repo, gn, rec, spot._robot, spot_adapter=spot)
    map_mgr.sync_to_robot()
    map_mgr.sync_from_robot()

    # Attempt relocalization at startup
    wp = map_mgr.relocalize_best_effort()
    if wp:
        print(f"  Relocalized at {wp}")
    else:
        print("  ⚠️  Not localized — use 'relocalize' or 'mark location'")

    perception = RealPerceptionAdapter.from_robot(spot._robot)
    approval = FakeApprovalAdapter()
    runner, handler, event_router = _make_runner_and_handler(repo, spot=spot, perception=perception)
    agent_tools.set_map_manager(map_mgr)

    # Start viewer with live video feed
    from bosdyn.client.image import ImageClient

    from spot_train.ui.viewer import CAMERA_SOURCES, DEPTH_SOURCES, SpotTrainViewer

    img_client = spot._robot.ensure_client(ImageClient.default_service_name)
    all_sources = list(CAMERA_SOURCES) + list(DEPTH_SOURCES)

    def _fetch_frames() -> dict:
        try:
            responses = img_client.get_image_from_sources(all_sources)
            result = {}
            for resp in responses:
                shot = resp.shot
                if shot and shot.image and shot.image.data:
                    result[resp.source.name] = (
                        shot.image.data,
                        shot.image.rows,
                        shot.image.cols,
                        shot.image.pixel_format,
                    )
            return result
        except Exception:
            return {}

    viewer = SpotTrainViewer(
        frame_callback=_fetch_frames,
        title=f"☀️ {spot._robot.get_id().nickname or 'Spot'} Viewer",
    )
    viewer.start()

    # Start spatial awareness actor
    import boto3
    from bosdyn.client.robot_state import RobotStateClient

    from spot_train.perception.spatial import SpatialAwarenessActor

    state_client = spot._robot.ensure_client(RobotStateClient.default_service_name)
    bedrock_rt = boto3.client("bedrock-runtime", region_name="us-west-2")
    spatial_actor = SpatialAwarenessActor(
        img_client,
        state_client,
        bedrock_client=bedrock_rt,
        viewer=viewer,
    )
    spatial_actor.start()
    agent_tools.set_spatial_actor(spatial_actor)

    return {
        "repository": repo,
        "spot_adapter": spot,
        "perception_adapter": perception,
        "approval_adapter": approval,
        "runner": runner,
        "handler": handler,
        "event_router": event_router,
        "map_manager": map_mgr,
        "viewer": viewer,
        "spatial_actor": spatial_actor,
    }
