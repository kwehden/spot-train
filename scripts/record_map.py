#!/usr/bin/env python3
"""Record a GraphNav map by walking Spot around with the keyboard.

Usage:
    1. Start estop_control.py in another terminal and release the e-stop
    2. Run this script: python scripts/record_map.py
    3. Use keyboard to walk Spot and press 'n' to create named waypoints
    4. The map is saved to data/maps/<name>/

No fiducials required — uses visual features for localization.
"""

from __future__ import annotations

import os
import threading
import time

import bosdyn.client
import bosdyn.client.util
import cv2
import numpy as np
from bosdyn.api import image_pb2
from bosdyn.client.graph_nav import GraphNavClient
from bosdyn.client.image import ImageClient
from bosdyn.client.lease import LeaseClient, LeaseKeepAlive
from bosdyn.client.recording import GraphNavRecordingServiceClient
from bosdyn.client.robot_command import RobotCommandBuilder, RobotCommandClient


def connect():
    hostname = os.environ["SPOT_HOSTNAME"]
    username = os.environ["SPOT_USERNAME"]
    password = os.environ["SPOT_PASSWORD"]
    os.environ.setdefault("BOSDYN_CLIENT_USERNAME", username)
    os.environ.setdefault("BOSDYN_CLIENT_PASSWORD", password)

    sdk = bosdyn.client.create_standard_sdk("record_map")
    robot = sdk.create_robot(hostname)
    bosdyn.client.util.authenticate(robot)
    robot.sync_with_directory()
    robot.time_sync.wait_for_sync()
    return robot


class CameraViewer:
    """Background thread that streams Spot camera images to an OpenCV window."""

    def __init__(self, image_client: ImageClient, source: str = "frontleft_fisheye_image"):
        self._client = image_client
        self._source = source
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        cv2.destroyAllWindows()

    def _loop(self):
        while self._running:
            try:
                images = self._client.get_image_from_sources([self._source])
                if not images:
                    time.sleep(0.5)
                    continue
                img = images[0]
                if img.shot.image.pixel_format == image_pb2.Image.PIXEL_FORMAT_GREYSCALE_U8:
                    frame = np.frombuffer(img.shot.image.data, dtype=np.uint8).reshape(
                        img.shot.image.rows, img.shot.image.cols
                    )
                else:
                    frame = cv2.imdecode(
                        np.frombuffer(img.shot.image.data, dtype=np.uint8),
                        cv2.IMREAD_COLOR,
                    )
                if frame is not None:
                    cv2.imshow("Spot Camera", frame)
                    cv2.waitKey(1)
            except Exception:
                time.sleep(0.5)


def _walk(command_client, vx, vy, vrot):
    """Send a short velocity command."""
    cmd = RobotCommandBuilder.synchro_velocity_command(vx, vy, vrot)
    command_client.robot_command(cmd, end_time_secs=time.time() + 0.6)
    time.sleep(0.6)
    stop = RobotCommandBuilder.stop_command()
    command_client.robot_command(stop)


def main():
    import sys
    import termios
    import tty

    robot = connect()
    print("✅ Connected")

    lease_client = robot.ensure_client(LeaseClient.default_service_name)
    recording_client = robot.ensure_client(GraphNavRecordingServiceClient.default_service_name)
    graph_nav_client = robot.ensure_client(GraphNavClient.default_service_name)
    command_client = robot.ensure_client(RobotCommandClient.default_service_name)
    image_client = robot.ensure_client(ImageClient.default_service_name)

    lease_client.take()
    lease_keepalive = LeaseKeepAlive(lease_client, must_acquire=True, return_at_exit=True)
    print("✅ Lease acquired")

    graph_nav_client.clear_graph()
    print("✅ Graph cleared")

    robot.power_on(timeout_sec=20)
    print("✅ Powered on")

    blocking_stand = RobotCommandBuilder.synchro_stand_command()
    command_client.robot_command(blocking_stand, timeout=10)
    time.sleep(1)
    print("✅ Standing")

    # Start camera viewer
    sources = image_client.list_image_sources()
    source_names = [s.name for s in sources]
    preferred = "frontleft_fisheye_image"
    if preferred not in source_names and source_names:
        preferred = source_names[0]
    print(f"📷 Camera: {preferred}")

    viewer = CameraViewer(image_client, preferred)
    viewer.start()

    # Start recording
    recording_env = recording_client.make_recording_environment(name="lab_map")
    recording_client.start_recording(recording_environment=recording_env, require_fiducials=[])
    print("✅ Recording started")
    print()
    print("Controls (no Enter needed):")
    print("  w/a/s/d — walk    q/e — turn    n — name waypoint    x — stop & save")
    print()

    waypoint_count = 0
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)

    try:
        while True:
            tty.setraw(fd)
            ch = sys.stdin.read(1)
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

            if ch == "w":
                _walk(command_client, 0.5, 0.0, 0.0)
            elif ch == "s":
                _walk(command_client, -0.5, 0.0, 0.0)
            elif ch == "a":
                _walk(command_client, 0.0, 0.5, 0.0)
            elif ch == "d":
                _walk(command_client, 0.0, -0.5, 0.0)
            elif ch == "q":
                _walk(command_client, 0.0, 0.0, 0.5)
            elif ch == "e":
                _walk(command_client, 0.0, 0.0, -0.5)
            elif ch == "n":
                name = input("Waypoint name: ").strip()
                if name:
                    recording_client.create_waypoint(waypoint_name=name)
                    waypoint_count += 1
                    print(f"  📍 '{name}' ({waypoint_count} total)")
            elif ch == "x":
                break
            elif ch == "\x03":  # Ctrl+C
                break

    except KeyboardInterrupt:
        pass
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

    viewer.stop()
    print("\nStopping recording...")
    recording_client.stop_recording()

    # Download and save
    graph = graph_nav_client.download_graph()
    waypoints = list(graph.waypoints)
    print(f"Graph: {len(waypoints)} waypoints, {len(graph.edges)} edges")

    map_dir = os.path.join("data", "maps", "lab_map")
    os.makedirs(map_dir, exist_ok=True)

    with open(os.path.join(map_dir, "graph"), "wb") as f:
        f.write(graph.SerializeToString())

    for wp in waypoints:
        if wp.snapshot_id:
            snapshot = graph_nav_client.download_waypoint_snapshot(wp.snapshot_id)
            with open(os.path.join(map_dir, f"waypoint_snapshot_{wp.snapshot_id}"), "wb") as f:
                f.write(snapshot.SerializeToString())

    for edge in graph.edges:
        if edge.snapshot_id:
            try:
                snapshot = graph_nav_client.download_edge_snapshot(edge.snapshot_id)
                with open(os.path.join(map_dir, f"edge_snapshot_{edge.snapshot_id}"), "wb") as f:
                    f.write(snapshot.SerializeToString())
            except Exception:
                pass

    print(f"✅ Map saved to {map_dir}/")
    print("\nNamed waypoints:")
    for wp in waypoints:
        name = wp.annotations.name or ""
        if name and not name.startswith("waypoint_") and not name.startswith("lab_map_"):
            print(f"  {name} -> {wp.id[:24]}...")

    # Sit and power off
    sit = RobotCommandBuilder.synchro_sit_command()
    command_client.robot_command(sit, timeout=10)
    time.sleep(2)
    robot.power_off(cut_immediately=False, timeout_sec=20)
    print("✅ Powered off")
    lease_keepalive.shutdown()


if __name__ == "__main__":
    main()
