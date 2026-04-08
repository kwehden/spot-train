"""Tests for SpotTrainViewer non-GUI parts."""

from __future__ import annotations

import numpy as np

from spot_train.ui.viewer import (
    CAMERA_ROTATIONS,
    CAMERA_SOURCES,
    SpotTrainViewer,
    _depth_colormap,
)


def test_depth_colormap_produces_rgba():
    arr = np.array([[0, 1000, 5000], [0, 1000, 5000], [0, 1000, 5000]], dtype=np.uint16)
    raw = arr.tobytes()
    img = _depth_colormap(raw, 3, 3)
    assert img.mode == "RGBA"
    assert img.size == (3, 3)


def test_push_description_appends_to_buffer():
    viewer = SpotTrainViewer(frame_callback=None)
    viewer.push_description("test desc")
    assert len(viewer._desc_buffer) == 1
    assert viewer._desc_buffer[0][1] == "test desc"


def test_push_trace_appends_to_buffer():
    viewer = SpotTrainViewer(frame_callback=None)
    viewer.push_trace("tool call")
    assert len(viewer._trace_buffer) == 1
    assert viewer._trace_buffer[0][1] == "tool call"


def test_camera_rotations_defined_for_all_sources():
    for source in CAMERA_SOURCES:
        assert source in CAMERA_ROTATIONS, f"Missing rotation for {source}"
