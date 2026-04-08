"""Tests for spot_train.perception.pointcloud."""

from __future__ import annotations

import numpy as np

from spot_train.perception.pointcloud import (
    compute_depth_stats,
    depth_to_points_camera_frame,
    quat_to_rotation_matrix,
    save_ply,
    transform_points,
)


def test_depth_to_points_camera_frame():
    depth = np.zeros((3, 3), dtype=np.uint16)
    depth[1, 1] = 2000  # center pixel only
    pts = depth_to_points_camera_frame(depth, fx=100, fy=100, cx=1, cy=1)
    assert pts.shape == (1, 3)
    z = 2000 / 1000.0
    np.testing.assert_allclose(pts[0], [(1 - 1) * z / 100, (1 - 1) * z / 100, z], atol=1e-5)


def test_depth_to_points_filters_min_max():
    depth = np.array([[30, 100, 15000]], dtype=np.uint16)
    pts = depth_to_points_camera_frame(
        depth, fx=1, fy=1, cx=0, cy=0, min_depth_mm=50, max_depth_mm=10000
    )
    assert pts.shape[0] == 1
    np.testing.assert_allclose(pts[0, 2], 0.1, atol=1e-5)


def test_compute_depth_stats():
    depth = np.array([[0, 100, 200, 0, 300]], dtype=np.uint16)
    stats = compute_depth_stats(depth, min_valid=50)
    assert stats.min_mm == 100
    assert stats.max_mm == 300
    assert stats.mean_mm == 200
    assert stats.valid_pixels == 3
    assert stats.total_pixels == 5
    assert stats.coverage == 0.6


def test_quat_to_rotation_matrix_identity():
    R = quat_to_rotation_matrix(0, 0, 0, 1)
    np.testing.assert_allclose(R, np.eye(3), atol=1e-6)


def test_transform_points_translation_only():
    pts = np.array([[1, 0, 0], [0, 1, 0]], dtype=np.float32)
    result = transform_points(pts, position=(1, 2, 3), rotation=(0, 0, 0, 1))
    np.testing.assert_allclose(result, [[2, 2, 3], [1, 3, 3]], atol=1e-5)


def test_save_ply_writes_valid_file(tmp_path):
    pts = np.array([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0], [7.0, 8.0, 9.0]], dtype=np.float32)
    path = str(tmp_path / "test.ply")
    save_ply(path, pts)
    text = open(path).read()
    assert "element vertex 3" in text
    lines = text.strip().split("\n")
    header_end = lines.index("end_header")
    data_lines = lines[header_end + 1 :]
    assert len(data_lines) == 3
    assert data_lines[0].startswith("1.0000 2.0000 3.0000")
