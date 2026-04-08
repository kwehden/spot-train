"""Tests for LocalScene and QuadrantDepth."""

from __future__ import annotations

import numpy as np

from spot_train.perception.spatial import (
    LocalScene,
    QuadrantDepth,
    _quadrant_from_depth,
)


def _make_scene(**overrides) -> LocalScene:
    defaults = dict(
        front=QuadrantDepth(min_mm=2000, mean_mm=3000, max_mm=5000, coverage=0.5),
        left=QuadrantDepth(min_mm=2000, mean_mm=3000, max_mm=5000, coverage=0.5),
        right=QuadrantDepth(min_mm=2000, mean_mm=3000, max_mm=5000, coverage=0.5),
        back=QuadrantDepth(min_mm=2000, mean_mm=3000, max_mm=5000, coverage=0.5),
        x=0.0,
        y=0.0,
        yaw=0.0,
        heading_cardinal="N",
        scene_description="",
    )
    defaults.update(overrides)
    return LocalScene(**defaults)


def test_local_scene_format_compact():
    scene = LocalScene(
        front=QuadrantDepth(min_mm=1200, mean_mm=2000, max_mm=5000, coverage=0.5),
        left=QuadrantDepth(min_mm=800, mean_mm=1500, max_mm=3000, coverage=0.4),
        right=QuadrantDepth(min_mm=5000, mean_mm=6000, max_mm=8000, coverage=0.3),
        back=QuadrantDepth(min_mm=3000, mean_mm=4000, max_mm=6000, coverage=0.2),
        x=1.0,
        y=-0.5,
        yaw=0.26,
        heading_cardinal="NNE",
        scene_description="desk ahead",
        description_age_s=5.0,
    )
    text = scene.format_compact()
    assert "front: 1.2m" in text
    assert "left: 0.8m" in text
    assert "NNE" in text
    assert "desk ahead" in text


def test_local_scene_is_blocked_forward():
    scene = _make_scene(
        front=QuadrantDepth(min_mm=200, mean_mm=500, max_mm=1000, coverage=0.1),
    )
    result = scene.is_blocked(v_x=0.5, v_y=0)
    assert result is not None
    assert "200mm" in result


def test_local_scene_is_blocked_returns_none_when_clear():
    scene = _make_scene(
        front=QuadrantDepth(min_mm=2000, mean_mm=3000, max_mm=5000, coverage=0.1),
    )
    result = scene.is_blocked(v_x=0.5, v_y=0)
    assert result is None


def test_local_scene_is_blocked_backward():
    scene = _make_scene(
        back=QuadrantDepth(min_mm=150, mean_mm=400, max_mm=800, coverage=0.1),
    )
    result = scene.is_blocked(v_x=-0.5, v_y=0)
    assert result is not None


def test_quadrant_from_depth():
    # Use values > 300mm to pass the ground-plane filter
    arr = np.array(
        [[400, 500, 600, 700, 800, 900], [450, 550, 650, 750, 850, 950], [0, 0, 0, 0, 0, 0]],
        dtype=np.uint16,
    )
    # Top 60% of 3 rows = first 1 row (int(3*0.6)=1), cols 0:3 = [400, 500, 600]
    q = _quadrant_from_depth(arr, 0, 3)
    assert q.min_mm == 400
    assert q.coverage > 0
