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
        """Spatial context for agent prompt injection."""
        pose = f"({self.x:.1f},{self.y:.1f}) {self.yaw_deg:.0f}° {self.heading_cardinal}"
        lines = [f"Pose: {pose}"]
        if self.scene_description and self.description_age_s < 30:
            lines.append(f"View: {self.scene_description}")
        elif self.scene_description:
            lines.append(f"View (stale {self.description_age_s:.0f}s): {self.scene_description}")
        return "\n".join(lines)

    @property
    def yaw_deg(self) -> float:
        return math.degrees(self.yaw) % 360

    def is_blocked(self, v_x: float, v_y: float, threshold_mm: int = 300) -> str | None:
        """Spot's native obstacle avoidance handles collision prevention."""
        return None  # defer to robot's built-in safety


_CARDINALS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]

# Front cameras only — depth handled by Spot's native obstacle avoidance
_POLL_SOURCES = [
    "frontleft_fisheye_image",
    "frontright_fisheye_image",
]


def _quadrant_from_depth(depth_mm: np.ndarray, col_start: int, col_end: int) -> QuadrantDepth:
    """Compute depth stats for a column slice of a depth image.

    Minimum valid depth is 350mm — at standing height (~0.5m body),
    the downward-angled cameras see ground at ~400mm. Objects closer
    than 350mm are real obstacles. Maximum 8m filters ceiling noise.
    """
    region = depth_mm[:, col_start:col_end]
    valid = region[(region > 350) & (region < 8000)]
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

        # Only poll cameras when standing
        if self._is_standing():
            responses = self._image_client.get_image_from_sources(_POLL_SOURCES)
            for resp in responses:
                name = resp.source.name
                data = resp.shot.image.data
                if "fisheye" in name:
                    is_jpeg = data[:2] == b"\xff\xd8"
                    if is_jpeg:
                        self._front_b64[name] = base64.b64encode(data).decode()
                    else:
                        try:
                            import cv2

                            arr = cv2.imdecode(
                                np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR
                            )
                            if arr is not None:
                                _, jpeg = cv2.imencode(
                                    ".jpg", arr, [int(cv2.IMWRITE_JPEG_QUALITY), 50]
                                )
                                self._front_b64[name] = base64.b64encode(jpeg.tobytes()).decode()
                        except ImportError:
                            pass

        # Robot pose
        scene = LocalScene(timestamp=time.time())
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

        # Carry over VLM description
        with self._lock:
            scene.scene_description = self._scene.scene_description
            scene.description_age_s = time.time() - self._last_vlm_time
            self._scene = scene

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
