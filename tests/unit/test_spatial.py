"""Tests for spatial awareness (LocalScene, QuadrantDepth)."""

from __future__ import annotations

import numpy as np

from spot_train.perception.spatial import (
    LocalScene,
    QuadrantDepth,
    _quadrant_from_depth,
)


def test_local_scene_format_compact():
    scene = LocalScene(
        x=1.0,
        y=-0.5,
        yaw=0.26,
        heading_cardinal="NNE",
        scene_description="desk ahead",
        description_age_s=5.0,
    )
    text = scene.format_compact()
    assert "NNE" in text
    assert "desk ahead" in text
    assert "Pose:" in text


def test_local_scene_is_blocked_defers_to_robot():
    """is_blocked always returns None — Spot handles obstacle avoidance."""
    scene = LocalScene(
        front=QuadrantDepth(min_mm=200, mean_mm=300, max_mm=500, coverage=0.1),
    )
    assert scene.is_blocked(v_x=0.5, v_y=0) is None


def test_local_scene_is_blocked_returns_none_when_clear():
    scene = LocalScene(
        front=QuadrantDepth(min_mm=2000, mean_mm=3000, max_mm=5000, coverage=0.1),
    )
    assert scene.is_blocked(v_x=0.5, v_y=0) is None


def test_quadrant_from_depth():
    arr = np.array(
        [[600, 700, 800, 900, 1000, 1100], [650, 750, 850, 950, 1050, 1150], [0, 0, 0, 0, 0, 0]],
        dtype=np.uint16,
    )
    q = _quadrant_from_depth(arr, 0, 3)
    assert q.min_mm == 600
    assert q.coverage > 0
