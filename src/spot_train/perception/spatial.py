"""Spatial awareness actor — continuous lightweight perception."""

from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np


@dataclass(slots=True)
class QuadrantDepth:
    """Obstacle summary for one direction."""

    min_mm: int = 0
    mean_mm: int = 0
    max_mm: int = 0
    coverage: float = 0.0


@dataclass
class LocalScene:
    """Lightweight spatial snapshot — updated at ~1-2 Hz."""

    timestamp: float = 0.0
    front: QuadrantDepth = field(default_factory=QuadrantDepth)
    left: QuadrantDepth = field(default_factory=QuadrantDepth)
    right: QuadrantDepth = field(default_factory=QuadrantDepth)
    back: QuadrantDepth = field(default_factory=QuadrantDepth)
    nearest_obstacle_m: float = 99.0
    nearest_obstacle_bearing: float = 0.0
    clearest_path_bearing: float = 0.0
    clearest_path_distance: float = 0.0
    x: float = 0.0
    y: float = 0.0
    yaw: float = 0.0
    heading_cardinal: str = "?"
    scene_description: str = ""
    description_age_s: float = 999.0

    def format_compact(self) -> str:
        """One-line spatial context for agent prompt injection."""

        def _q(name: str, q: QuadrantDepth) -> str:
            if q.coverage < 0.01:
                return f"{name}: no data"
            return f"{name}: {q.min_mm / 1000:.1f}m"

        parts = [
            _q("front", self.front),
            _q("left", self.left),
            _q("right", self.right),
            _q("back", self.back),
        ]
        nearest = f"nearest {self.nearest_obstacle_m:.1f}m at {self.nearest_obstacle_bearing:.0f}°"
        pose = f"({self.x:.1f},{self.y:.1f}) {self.yaw_deg:.0f}° {self.heading_cardinal}"
        lines = [
            f"Scene: {' | '.join(parts)}",
            f"Pose: {pose} | {nearest}",
        ]
        if self.scene_description and self.description_age_s < 30:
            lines.append(f"View: {self.scene_description}")
        elif self.scene_description:
            lines.append(f"View (stale {self.description_age_s:.0f}s): {self.scene_description}")
        return "\n".join(lines)

    @property
    def yaw_deg(self) -> float:
        return math.degrees(self.yaw) % 360

    def is_blocked(self, v_x: float, v_y: float, threshold_mm: int = 300) -> str | None:
        """Return a reason string if movement would hit an obstacle, else None."""
        if v_x > 0 and self.front.coverage > 0.05 and self.front.min_mm < threshold_mm:
            return f"Obstacle {self.front.min_mm}mm ahead"
        if v_x < 0 and self.back.coverage > 0.05 and self.back.min_mm < threshold_mm:
            return f"Obstacle {self.back.min_mm}mm behind"
        if v_y > 0 and self.left.coverage > 0.05 and self.left.min_mm < threshold_mm:
            return f"Obstacle {self.left.min_mm}mm to the left"
        if v_y < 0 and self.right.coverage > 0.05 and self.right.min_mm < threshold_mm:
            return f"Obstacle {self.right.min_mm}mm to the right"
        return None


_CARDINALS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]

# Front cameras + depth for lightweight polling
_POLL_SOURCES = [
    "frontleft_fisheye_image",
    "frontright_fisheye_image",
    "frontleft_depth_in_visual_frame",
    "frontright_depth_in_visual_frame",
]


def _quadrant_from_depth(depth_mm: np.ndarray, col_start: int, col_end: int) -> QuadrantDepth:
    """Compute depth stats for a column slice of a depth image.

    Uses only the top 60% of rows to exclude ground-plane readings
    from the downward-angled cameras. Minimum valid depth is 300mm
    to filter out noise and near-field ground reflections.
    """
    # Exclude bottom 40% of image (ground plane at camera tilt angle)
    row_cutoff = int(depth_mm.shape[0] * 0.6)
    region = depth_mm[:row_cutoff, col_start:col_end]
    valid = region[region > 300]
    if valid.size == 0:
        return QuadrantDepth()
    return QuadrantDepth(
        min_mm=int(valid.min()),
        mean_mm=int(valid.mean()),
        max_mm=int(valid.max()),
        coverage=round(valid.size / region.size, 3),
    )


class SpatialAwarenessActor:
    """Background thread maintaining a LocalScene at ~1-2 Hz."""

    def __init__(
        self,
        image_client: Any,
        state_client: Any,
        *,
        bedrock_client: Any = None,
        vlm_model_id: str = "us.amazon.nova-lite-v1:0",
        vlm_interval_s: float = 10.0,
        viewer: Any = None,
    ) -> None:
        self._image_client = image_client
        self._state_client = state_client
        self._bedrock = bedrock_client
        self._vlm_model_id = vlm_model_id
        self._vlm_interval = vlm_interval_s
        self._viewer = viewer
        self._scene = LocalScene()
        self._lock = threading.Lock()
        self._running = False
        self._last_vlm_time: float = 0
        self._front_b64: dict[str, str] = {}

    def start(self) -> None:
        self._running = True
        threading.Thread(target=self._loop, daemon=True).start()

    def stop(self) -> None:
        self._running = False

    def get_scene(self) -> LocalScene:
        with self._lock:
            # Update description age
            self._scene.description_age_s = time.time() - self._last_vlm_time
            return self._scene

    def _loop(self) -> None:
        while self._running:
            try:
                self._poll_sensors()
                self._maybe_vlm()
            except Exception:
                pass
            time.sleep(0.5)

    def _is_standing(self) -> bool:
        """Check if the robot is powered on and standing."""
        try:
            state = self._state_client.get_robot_state()
            # motor_power_state: 1=off, 2=on, 3=powering_on, 4=powering_off, 5=error
            return state.power_state.motor_power_state == 2
        except Exception:
            return False

    def _poll_sensors(self) -> None:
        import base64

        from bosdyn.client.frame_helpers import get_odom_tform_body

        standing = self._is_standing()

        # Only poll depth when standing — cameras see the ground otherwise
        sources = list(_POLL_SOURCES) if standing else [
            s for s in _POLL_SOURCES if "depth" not in s
        ]
        if not sources:
            return
        responses = self._image_client.get_image_from_sources(sources)

        depth_left: np.ndarray | None = None
        depth_right: np.ndarray | None = None

        for resp in responses:
            name = resp.source.name
            data = resp.shot.image.data
            rows = resp.shot.image.rows
            cols = resp.shot.image.cols

            if name == "frontleft_depth_in_visual_frame":
                if len(data) == rows * cols * 2:
                    depth_left = np.frombuffer(data, dtype=np.uint16).reshape(rows, cols)
            elif name == "frontright_depth_in_visual_frame":
                if len(data) == rows * cols * 2:
                    depth_right = np.frombuffer(data, dtype=np.uint16).reshape(rows, cols)
            elif "fisheye" in name:
                # Cache b64 for VLM
                is_jpeg = data[:2] == b"\xff\xd8"
                if is_jpeg:
                    self._front_b64[name] = base64.b64encode(data).decode()
                else:
                    try:
                        import cv2

                        arr = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
                        if arr is not None:
                            _, jpeg = cv2.imencode(".jpg", arr, [int(cv2.IMWRITE_JPEG_QUALITY), 50])
                            self._front_b64[name] = base64.b64encode(jpeg.tobytes()).decode()
                    except ImportError:
                        pass

        # Build quadrant depths from the two front depth images
        # Front-left covers left-of-center, front-right covers right-of-center
        scene = LocalScene(timestamp=time.time())

        if depth_left is not None:
            cols_l = depth_left.shape[1]
            scene.front = _quadrant_from_depth(depth_left, cols_l // 4, 3 * cols_l // 4)
            scene.left = _quadrant_from_depth(depth_left, 0, cols_l // 4)

        if depth_right is not None:
            cols_r = depth_right.shape[1]
            if scene.front.coverage == 0:
                scene.front = _quadrant_from_depth(depth_right, cols_r // 4, 3 * cols_r // 4)
            else:
                # Merge: take the closer reading
                fr = _quadrant_from_depth(depth_right, cols_r // 4, 3 * cols_r // 4)
                if fr.coverage > 0 and fr.min_mm < scene.front.min_mm:
                    scene.front.min_mm = fr.min_mm
            scene.right = _quadrant_from_depth(depth_right, 3 * cols_r // 4, cols_r)

        # Back quadrant: not polled in lightweight mode, leave as default

        # Nearest obstacle
        all_quads = [
            (scene.front, 0),
            (scene.left, 90),
            (scene.right, 270),
        ]
        nearest_mm = 99000
        nearest_bearing = 0.0
        for q, bearing in all_quads:
            if q.coverage > 0.01 and q.min_mm < nearest_mm:
                nearest_mm = q.min_mm
                nearest_bearing = bearing
        scene.nearest_obstacle_m = nearest_mm / 1000.0
        scene.nearest_obstacle_bearing = nearest_bearing

        # Clearest path: quadrant with largest min_mm
        best_dist = 0
        best_bearing = 0.0
        for q, bearing in all_quads:
            if q.coverage > 0.01 and q.min_mm > best_dist:
                best_dist = q.min_mm
                best_bearing = bearing
        scene.clearest_path_bearing = best_bearing
        scene.clearest_path_distance = best_dist / 1000.0

        # Robot pose
        try:
            state = self._state_client.get_robot_state()
            odom = get_odom_tform_body(state.kinematic_state.transforms_snapshot)
            scene.x = odom.x
            scene.y = odom.y
            scene.yaw = odom.rot.to_yaw()
            yaw_deg = scene.yaw_deg
            scene.heading_cardinal = _CARDINALS[int((yaw_deg + 22.5) / 45) % 8]
        except Exception:
            pass

        # Carry over VLM description from previous scene
        with self._lock:
            scene.scene_description = self._scene.scene_description
            scene.description_age_s = time.time() - self._last_vlm_time
            self._scene = scene

        # Push to viewer if available
        if self._viewer and self._front_b64:
            for name, b64 in self._front_b64.items():
                # Viewer gets the raw frames from the video loop, not from here
                pass

    def _maybe_vlm(self) -> None:
        """Run lightweight VLM description if interval has elapsed."""
        if self._bedrock is None:
            return
        now = time.time()
        if now - self._last_vlm_time < self._vlm_interval:
            return
        if not self._front_b64:
            return

        import base64

        content: list[dict[str, Any]] = []
        for name in ("frontleft_fisheye_image", "frontright_fisheye_image"):
            b64 = self._front_b64.get(name)
            if b64:
                label = "front-left" if "left" in name else "front-right"
                content.append({"text": f"[{label}]"})
                content.append(
                    {
                        "image": {
                            "format": "jpeg",
                            "source": {"bytes": base64.b64decode(b64)},
                        }
                    }
                )

        if not content:
            return

        content.append(
            {
                "text": (
                    "2 sentences: describe obstacles and notable objects with "
                    "body-frame bearings and distances. 0°=forward, 90°=left, "
                    "270°=right."
                )
            }
        )

        try:
            resp = self._bedrock.converse(
                modelId=self._vlm_model_id,
                messages=[{"role": "user", "content": content}],
                inferenceConfig={"maxTokens": 150, "temperature": 0.2},
            )
            text = ""
            for block in resp["output"]["message"]["content"]:
                if "text" in block:
                    text += block["text"]

            with self._lock:
                self._scene.scene_description = text.strip()
            self._last_vlm_time = now

            if self._viewer:
                self._viewer.push_description(text.strip())
        except Exception:
            pass
