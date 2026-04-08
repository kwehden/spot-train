"""Point cloud generation from Spot depth images + camera intrinsics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np


@dataclass(slots=True)
class DepthStats:
    """Summary statistics for a depth image."""

    min_mm: int
    max_mm: int
    mean_mm: int
    valid_pixels: int
    total_pixels: int
    coverage: float  # fraction of pixels with valid depth


@dataclass(slots=True)
class CameraPointCloud:
    """Point cloud from a single camera in the body frame."""

    camera: str
    orientation: str
    points: np.ndarray  # (N, 3) float32 in body frame, meters
    depth_stats: DepthStats


def depth_to_points_camera_frame(
    depth_mm: np.ndarray,
    fx: float,
    fy: float,
    cx: float,
    cy: float,
    min_depth_mm: int = 50,
    max_depth_mm: int = 10000,
) -> np.ndarray:
    """Project a depth image into 3D points in the camera's optical frame.

    Returns (N, 3) float32 array in meters.
    """
    rows, cols = depth_mm.shape
    mask = (depth_mm > min_depth_mm) & (depth_mm < max_depth_mm)
    v, u = np.where(mask)
    z = depth_mm[v, u].astype(np.float32) / 1000.0
    x = (u.astype(np.float32) - cx) * z / fx
    y = (v.astype(np.float32) - cy) * z / fy
    return np.column_stack((x, y, z))


def quat_to_rotation_matrix(qx: float, qy: float, qz: float, qw: float) -> np.ndarray:
    """Convert quaternion (x, y, z, w) to a 3x3 rotation matrix."""
    r = np.array(
        [
            [1 - 2 * (qy * qy + qz * qz), 2 * (qx * qy - qz * qw), 2 * (qx * qz + qy * qw)],
            [2 * (qx * qy + qz * qw), 1 - 2 * (qx * qx + qz * qz), 2 * (qy * qz - qx * qw)],
            [2 * (qx * qz - qy * qw), 2 * (qy * qz + qx * qw), 1 - 2 * (qx * qx + qy * qy)],
        ],
        dtype=np.float32,
    )
    return r


def transform_points(
    points: np.ndarray,
    position: tuple[float, float, float],
    rotation: tuple[float, float, float, float],
) -> np.ndarray:
    """Apply a rigid transform (position + quaternion) to points.

    Args:
        points: (N, 3) array
        position: (x, y, z) translation
        rotation: (qx, qy, qz, qw) quaternion
    """
    rot = quat_to_rotation_matrix(*rotation)
    return (rot @ points.T).T + np.array(position, dtype=np.float32)


def build_transform_chain(
    transforms_snapshot: Any,
    source_frame: str,
    target_frame: str = "body",
) -> tuple[tuple[float, float, float], tuple[float, float, float, float]] | None:
    """Walk the frame tree from source_frame to target_frame.

    Returns (position, quaternion) of the composed transform, or None if
    the chain cannot be resolved.
    """
    edge_map = transforms_snapshot.child_to_parent_edge_map
    # Collect chain from source up to target
    chain = []
    current = source_frame
    visited = set()
    while current and current != target_frame and current not in visited:
        visited.add(current)
        if current not in edge_map:
            return None
        edge = edge_map[current]
        chain.append(edge.parent_tform_child)
        current = edge.parent_frame_name

    if current != target_frame:
        return None

    # Compose transforms
    pos = np.array([0.0, 0.0, 0.0], dtype=np.float64)
    rot = np.eye(3, dtype=np.float64)

    for tf in chain:
        p = np.array([tf.position.x, tf.position.y, tf.position.z])
        r = quat_to_rotation_matrix(
            tf.rotation.x, tf.rotation.y, tf.rotation.z, tf.rotation.w
        ).astype(np.float64)
        pos = r @ pos + p
        rot = r @ rot

    # Extract quaternion from composed rotation
    m = rot
    tr = m[0, 0] + m[1, 1] + m[2, 2]
    if tr > 0:
        s = 0.5 / np.sqrt(tr + 1.0)
        qw = 0.25 / s
        qx = (m[2, 1] - m[1, 2]) * s
        qy = (m[0, 2] - m[2, 0]) * s
        qz = (m[1, 0] - m[0, 1]) * s
    elif m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
        s = 2.0 * np.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2])
        qw = (m[2, 1] - m[1, 2]) / s
        qx = 0.25 * s
        qy = (m[0, 1] + m[1, 0]) / s
        qz = (m[0, 2] + m[2, 0]) / s
    elif m[1, 1] > m[2, 2]:
        s = 2.0 * np.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2])
        qw = (m[0, 2] - m[2, 0]) / s
        qx = (m[0, 1] + m[1, 0]) / s
        qy = 0.25 * s
        qz = (m[1, 2] + m[2, 1]) / s
    else:
        s = 2.0 * np.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1])
        qw = (m[1, 0] - m[0, 1]) / s
        qx = (m[0, 2] + m[2, 0]) / s
        qy = (m[1, 2] + m[2, 1]) / s
        qz = 0.25 * s

    return (float(pos[0]), float(pos[1]), float(pos[2])), (
        float(qx),
        float(qy),
        float(qz),
        float(qw),
    )


def compute_depth_stats(depth_mm: np.ndarray, min_valid: int = 50) -> DepthStats:
    """Compute summary statistics for a depth image."""
    valid = depth_mm[depth_mm > min_valid]
    total = depth_mm.size
    return DepthStats(
        min_mm=int(valid.min()) if valid.size > 0 else 0,
        max_mm=int(valid.max()) if valid.size > 0 else 0,
        mean_mm=int(valid.mean()) if valid.size > 0 else 0,
        valid_pixels=int(valid.size),
        total_pixels=total,
        coverage=round(valid.size / total, 3) if total > 0 else 0.0,
    )


def save_ply(path: str, points: np.ndarray) -> None:
    """Write a point cloud to a PLY file."""
    n = len(points)
    with open(path, "w") as f:
        f.write("ply\n")
        f.write("format ascii 1.0\n")
        f.write(f"element vertex {n}\n")
        f.write("property float x\n")
        f.write("property float y\n")
        f.write("property float z\n")
        f.write("end_header\n")
        for p in points:
            f.write(f"{p[0]:.4f} {p[1]:.4f} {p[2]:.4f}\n")
