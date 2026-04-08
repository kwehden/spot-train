"""Perception adapter boundary."""

from __future__ import annotations

import json
from hashlib import sha256
from typing import Any, Protocol

from pydantic import Field

from spot_train.models import (
    ConditionVerdict,
    EntityType,
    OutcomeCode,
    SpotTrainModel,
)


class CaptureEvidenceRequest(SpotTrainModel):
    """Request to capture a specific evidence artifact."""

    task_id: str | None = None
    place_id: str
    capture_kind: str
    capture_profile: str | None = None


class ConditionVerificationRequest(SpotTrainModel):
    """Request to verify a named condition against evidence."""

    task_id: str | None = None
    target_type: EntityType
    target_id: str
    condition_id: str
    evidence_ids: list[str] = Field(default_factory=list)


class CapturedEvidence(SpotTrainModel):
    """Structured result for a perception capture operation."""

    observation_id: str
    task_id: str | None = None
    place_id: str
    capture_kind: str
    capture_profile: str | None = None
    artifact_uri: str
    summary: str
    confidence: float = Field(ge=0.0, le=1.0)
    outcome_code: OutcomeCode = OutcomeCode.OBSERVATION_CAPTURED
    structured_data_json: dict[str, Any] = Field(default_factory=dict)
    inconclusive_reason: str | None = None


class ConditionAnalysisResult(SpotTrainModel):
    """Structured result for a condition-verification operation."""

    task_id: str | None = None
    target_type: EntityType
    target_id: str
    condition_id: str
    result: ConditionVerdict
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str
    evidence_ids: list[str] = Field(default_factory=list)
    outcome_code: OutcomeCode = OutcomeCode.INSPECTION_COMPLETED
    structured_data_json: dict[str, Any] = Field(default_factory=dict)


class PerceptionAdapter(Protocol):
    """Minimal perception boundary used by the supervisor."""

    def capture_evidence(self, request: CaptureEvidenceRequest) -> CapturedEvidence:
        """Capture evidence for a place or asset."""

    def verify_condition(self, request: ConditionVerificationRequest) -> ConditionAnalysisResult:
        """Evaluate a named condition using evidence."""


class FakePerceptionAdapter:
    """Deterministic fake perception backend for local development and tests."""

    def __init__(self) -> None:
        self._capture_fixtures: dict[str, CapturedEvidence] = {}
        self._condition_fixtures: dict[str, ConditionAnalysisResult] = {}

    def register_capture_fixture(
        self,
        request: CaptureEvidenceRequest | dict[str, Any],
        result: CapturedEvidence | dict[str, Any],
    ) -> None:
        validated_request = self._ensure_capture_request(request)
        validated_result = result
        if not isinstance(validated_result, CapturedEvidence):
            validated_result = CapturedEvidence.model_validate(validated_result)
        self._capture_fixtures[_capture_request_key(validated_request)] = validated_result

    def register_condition_fixture(
        self,
        request: ConditionVerificationRequest | dict[str, Any],
        result: ConditionAnalysisResult | dict[str, Any],
    ) -> None:
        validated_request = self._ensure_condition_request(request)
        validated_result = (
            result
            if isinstance(result, ConditionAnalysisResult)
            else ConditionAnalysisResult.model_validate(result)
        )
        self._condition_fixtures[_condition_request_key(validated_request)] = validated_result

    def capture_evidence(
        self,
        request: CaptureEvidenceRequest | dict[str, Any],
    ) -> CapturedEvidence:
        validated = self._ensure_capture_request(request)
        key = _capture_request_key(validated)
        fixture = self._capture_fixtures.get(key)
        if fixture is not None:
            return fixture.model_copy(deep=True)
        return self._default_capture_result(validated)

    def verify_condition(
        self,
        request: ConditionVerificationRequest | dict[str, Any],
    ) -> ConditionAnalysisResult:
        validated = self._ensure_condition_request(request)
        key = _condition_request_key(validated)
        fixture = self._condition_fixtures.get(key)
        if fixture is not None:
            return fixture.model_copy(deep=True)
        return self._default_condition_result(validated)

    def _ensure_capture_request(
        self,
        request: CaptureEvidenceRequest | dict[str, Any],
    ) -> CaptureEvidenceRequest:
        if isinstance(request, CaptureEvidenceRequest):
            return request
        return CaptureEvidenceRequest.model_validate(request)

    def _ensure_condition_request(
        self,
        request: ConditionVerificationRequest | dict[str, Any],
    ) -> ConditionVerificationRequest:
        if isinstance(request, ConditionVerificationRequest):
            return request
        return ConditionVerificationRequest.model_validate(request)

    def _default_capture_result(self, request: CaptureEvidenceRequest) -> CapturedEvidence:
        key = _capture_request_key(request)
        digest = sha256(key.encode("utf-8")).hexdigest()
        confidence = _bounded_confidence(int(digest[:2], 16), lower=0.55, upper=0.95)
        stable_id = _stable_id("obs", key)
        artifact_uri = f"fake://perception/{stable_id}/{request.capture_kind}.json"

        if int(digest[2:4], 16) % 5 == 0:
            return CapturedEvidence(
                observation_id=stable_id,
                task_id=request.task_id,
                place_id=request.place_id,
                capture_kind=request.capture_kind,
                capture_profile=request.capture_profile,
                artifact_uri=artifact_uri,
                summary=(
                    f"Capture for {request.capture_kind} at {request.place_id} was inconclusive."
                ),
                confidence=confidence,
                outcome_code=OutcomeCode.PERCEPTION_INCONCLUSIVE,
                structured_data_json={
                    "capture_kind": request.capture_kind,
                    "place_id": request.place_id,
                    "inconclusive_reason": "insufficient_signal",
                },
                inconclusive_reason="insufficient_signal",
            )

        return CapturedEvidence(
            observation_id=stable_id,
            task_id=request.task_id,
            place_id=request.place_id,
            capture_kind=request.capture_kind,
            capture_profile=request.capture_profile,
            artifact_uri=artifact_uri,
            summary=f"Captured {request.capture_kind} at {request.place_id}.",
            confidence=confidence,
            outcome_code=OutcomeCode.OBSERVATION_CAPTURED,
            structured_data_json={
                "capture_kind": request.capture_kind,
                "place_id": request.place_id,
                "capture_profile": request.capture_profile,
            },
        )

    def _default_condition_result(
        self,
        request: ConditionVerificationRequest,
    ) -> ConditionAnalysisResult:
        key = _condition_request_key(request)
        digest = sha256(key.encode("utf-8")).hexdigest()
        confidence = _bounded_confidence(int(digest[:2], 16), lower=0.5, upper=0.99)
        selector = int(digest[2:4], 16) % 3
        if selector == 0:
            result = ConditionVerdict.TRUE
            rationale = "Condition verified from deterministic fake perception output."
            outcome_code = OutcomeCode.INSPECTION_COMPLETED
        elif selector == 1:
            result = ConditionVerdict.FALSE
            rationale = "Condition rejected from deterministic fake perception output."
            outcome_code = OutcomeCode.INSPECTION_COMPLETED
        else:
            result = ConditionVerdict.INCONCLUSIVE
            rationale = "Evidence was insufficient to verify the condition."
            outcome_code = OutcomeCode.INSPECTION_INCONCLUSIVE

        return ConditionAnalysisResult(
            task_id=request.task_id,
            target_type=request.target_type,
            target_id=request.target_id,
            condition_id=request.condition_id,
            result=result,
            confidence=confidence,
            rationale=rationale,
            evidence_ids=list(request.evidence_ids),
            outcome_code=outcome_code,
            structured_data_json={
                "evidence_count": len(request.evidence_ids),
                "selector": selector,
            },
        )


class RealPerceptionAdapter:
    """Live perception using Spot cameras + Bedrock Nova Lite for analysis.

    Design principle: Spot's onboard sensors are the source of truth.
    The VLM is an analysis layer — it interprets what the robot already
    captured, it does not drive the robot's actions.
    """

    # All 5 camera positions with their orientations relative to body frame.
    CAMERAS = {
        "frontleft": {
            "fisheye": "frontleft_fisheye_image",
            "depth": "frontleft_depth_in_visual_frame",
            "orientation": "forward-left, angled down ~25°",
        },
        "frontright": {
            "fisheye": "frontright_fisheye_image",
            "depth": "frontright_depth_in_visual_frame",
            "orientation": "forward-right, angled down ~25°",
        },
        "left": {
            "fisheye": "left_fisheye_image",
            "depth": "left_depth_in_visual_frame",
            "orientation": "left side, angled down ~25°",
        },
        "right": {
            "fisheye": "right_fisheye_image",
            "depth": "right_depth_in_visual_frame",
            "orientation": "right side, angled down ~25°",
        },
        "back": {
            "fisheye": "back_fisheye_image",
            "depth": "back_depth_in_visual_frame",
            "orientation": "rear, angled down ~25°",
        },
    }

    def __init__(
        self,
        image_client: Any,
        *,
        artifact_dir: str = "data/artifacts",
        vlm_model_id: str = "us.amazon.nova-lite-v1:0",
        vlm_region: str = "us-west-2",
    ) -> None:
        self._image_client = image_client
        self._artifact_dir = artifact_dir
        self._vlm_model_id = vlm_model_id
        self._vlm_region = vlm_region
        self._bedrock: Any | None = None

    @classmethod
    def from_robot(cls, robot: Any, **kwargs: Any) -> "RealPerceptionAdapter":
        """Create from a connected robot instance."""
        from bosdyn.client.image import ImageClient

        image_client = robot.ensure_client(ImageClient.default_service_name)
        return cls(image_client, **kwargs)

    def _get_bedrock(self) -> Any:
        if self._bedrock is None:
            import boto3

            self._bedrock = boto3.client("bedrock-runtime", region_name=self._vlm_region)
        return self._bedrock

    def _capture_all_cameras(self, task_id: str | None, place_id: str) -> dict[str, Any]:
        """Capture images + depth from all 5 cameras with point clouds."""
        import base64
        import os

        import numpy as _np

        from spot_train.perception.pointcloud import (
            build_transform_chain,
            compute_depth_stats,
            depth_to_points_camera_frame,
            save_ply,
            transform_points,
        )

        all_sources = []
        source_map: dict[str, str] = {}
        for position, sources in self.CAMERAS.items():
            all_sources.append(sources["fisheye"])
            all_sources.append(sources["depth"])
            source_map[sources["fisheye"]] = position
            source_map[sources["depth"]] = position

        images = self._image_client.get_image_from_sources(all_sources)

        captures: dict[str, Any] = {}
        task_dir = os.path.join(self._artifact_dir, task_id or "no_task")
        os.makedirs(task_dir, exist_ok=True)

        # Sort: fisheye images first so intrinsics are available for depth
        images_sorted = sorted(images, key=lambda r: 1 if "depth" in r.source.name else 0)

        for img_response in images_sorted:
            source_name = img_response.source.name
            position = source_map.get(source_name, "unknown")
            if position not in captures:
                captures[position] = {
                    "orientation": self.CAMERAS[position]["orientation"],
                }

            data = img_response.shot.image.data
            rows = img_response.shot.image.rows
            cols = img_response.shot.image.cols
            is_depth = "depth" in source_name
            suffix = "depth" if is_depth else "rgb"
            filepath = os.path.join(task_dir, f"{position}_{suffix}.bin")

            with open(filepath, "wb") as f:
                f.write(data)

            entry: dict[str, Any] = {
                "source": source_name,
                "path": filepath,
                "rows": rows,
                "cols": cols,
            }

            tf = img_response.shot.transforms_snapshot
            if tf and tf.child_to_parent_edge_map:
                entry["transforms_snapshot"] = tf

            if img_response.source.HasField("pinhole"):
                p = img_response.source.pinhole
                entry["intrinsics"] = {
                    "focal_length": (
                        p.intrinsics.focal_length.x,
                        p.intrinsics.focal_length.y,
                    ),
                    "principal_point": (
                        p.intrinsics.principal_point.x,
                        p.intrinsics.principal_point.y,
                    ),
                }

            if is_depth:
                # Decode depth and compute stats + point cloud
                if len(data) == rows * cols * 2:
                    depth_mm = _np.frombuffer(data, dtype=_np.uint16).reshape(rows, cols)
                    stats = compute_depth_stats(depth_mm)
                    entry["depth_stats"] = stats

                    # Generate point cloud in camera frame
                    intrinsics = entry.get("intrinsics") or captures[position].get("image", {}).get(
                        "intrinsics"
                    )
                    if intrinsics:
                        fx, fy = intrinsics["focal_length"]
                        cx, cy = intrinsics["principal_point"]
                        pts_cam = depth_to_points_camera_frame(depth_mm, fx, fy, cx, cy)

                        # Transform to body frame
                        camera_frame = f"{position}_fisheye"
                        if tf:
                            body_tf = build_transform_chain(tf, camera_frame, "body")
                            if body_tf:
                                pts_body = transform_points(pts_cam, body_tf[0], body_tf[1])
                            else:
                                pts_body = pts_cam
                        else:
                            pts_body = pts_cam

                        ply_path = os.path.join(task_dir, f"{position}_cloud.ply")
                        save_ply(ply_path, pts_body)
                        entry["pointcloud_path"] = ply_path
                        entry["pointcloud_points"] = len(pts_body)

                captures[position]["depth"] = entry
            else:
                captures[position]["image"] = entry
                # Detect actual format via JPEG magic bytes
                is_jpeg = data[:2] == b"\xff\xd8"
                if is_jpeg:
                    captures[position]["image_b64"] = base64.b64encode(data).decode()
                    captures[position]["image_format"] = "jpeg"
                else:
                    try:
                        import cv2

                        # Try imdecode first (handles PNG, etc.)
                        arr = cv2.imdecode(
                            _np.frombuffer(data, dtype=_np.uint8),
                            cv2.IMREAD_COLOR,
                        )
                        if arr is None and len(data) == rows * cols:
                            # Raw greyscale U8
                            arr = _np.frombuffer(data, dtype=_np.uint8).reshape(rows, cols)
                        if arr is not None:
                            _, jpeg = cv2.imencode(".jpg", arr)
                            captures[position]["image_b64"] = base64.b64encode(
                                jpeg.tobytes()
                            ).decode()
                            captures[position]["image_format"] = "jpeg"
                    except ImportError:
                        pass  # skip VLM for this camera if no cv2

        return captures

    def _depth_context_summary(self, captures: dict[str, Any]) -> str:
        """Build a text summary of depth data for VLM context."""
        lines = []
        for position in sorted(captures):
            depth = captures[position].get("depth", {})
            stats = depth.get("depth_stats")
            if stats:
                lines.append(
                    f"  {position} ({captures[position]['orientation']}): "
                    f"nearest={stats.min_mm}mm, farthest={stats.max_mm}mm, "
                    f"mean={stats.mean_mm}mm, coverage={stats.coverage:.0%}"
                )
                n_pts = depth.get("pointcloud_points", 0)
                if n_pts:
                    lines.append(f"    point cloud: {n_pts} points")
        return "\n".join(lines) if lines else "  (no depth data)"

    def _vlm_analyze(self, prompt: str, image_b64_list: list[tuple[str, str]]) -> dict[str, Any]:
        """Send images to Nova Lite with a prompt. Returns parsed response."""
        content: list[dict[str, Any]] = []
        for label, b64 in image_b64_list:
            content.append({"text": f"[Camera: {label}]"})
            content.append(
                {
                    "image": {
                        "format": "jpeg",
                        "source": {"bytes": __import__("base64").b64decode(b64)},
                    }
                }
            )
        content.append({"text": prompt})

        response = self._get_bedrock().converse(
            modelId=self._vlm_model_id,
            messages=[{"role": "user", "content": content}],
            inferenceConfig={"maxTokens": 1024, "temperature": 0.1},
        )

        text = ""
        for block in response["output"]["message"]["content"]:
            if "text" in block:
                text += block["text"]

        return {"raw_text": text, "model_id": self._vlm_model_id}

    def capture_evidence(
        self,
        request: CaptureEvidenceRequest | dict[str, Any],
    ) -> CapturedEvidence:
        """Capture from all Spot cameras and generate a VLM summary."""
        if not isinstance(request, CaptureEvidenceRequest):
            request = CaptureEvidenceRequest.model_validate(request)

        captures = self._capture_all_cameras(request.task_id, request.place_id)

        # Build image list for VLM (only verified JPEG images)
        image_list: list[tuple[str, str]] = []
        for position, data in sorted(captures.items()):
            b64 = data.get("image_b64")
            if b64 and data.get("image_format") == "jpeg":
                orientation = data.get("orientation", "unknown")
                image_list.append((f"{position} ({orientation})", b64))

        # Ask VLM to describe what the robot sees
        depth_ctx = self._depth_context_summary(captures)
        prompt = (
            f"You are analyzing images from a Boston Dynamics Spot robot at location "
            f"'{request.place_id}'. Each image is labeled with its camera position and "
            f"orientation on the robot body. The robot has 5 fisheye cameras providing "
            f"near-360° coverage.\n\n"
            f"Capture type requested: {request.capture_kind}\n\n"
            f"Depth sensor readings per camera:\n{depth_ctx}\n\n"
            f"Describe what you observe across all cameras. Note any equipment, objects, "
            f"people, obstacles, or notable conditions. Reference distances from the "
            f"depth data where relevant. Be factual and specific."
        )

        vlm_result = self._vlm_analyze(prompt, image_list)

        key = f"{request.place_id}:{request.task_id}:{request.capture_kind}"
        stable_id = _stable_id("obs", key)
        artifact_dir = f"{self._artifact_dir}/{request.task_id or 'no_task'}"

        # Build structured data with per-camera metadata
        camera_meta = {}
        for position, data in captures.items():
            meta: dict[str, Any] = {"orientation": data.get("orientation")}
            if "image" in data:
                meta["image_path"] = data["image"]["path"]
                meta["resolution"] = f"{data['image']['rows']}x{data['image']['cols']}"
                if "intrinsics" in data["image"]:
                    meta["intrinsics"] = data["image"]["intrinsics"]
            if "depth" in data:
                meta["depth_path"] = data["depth"]["path"]
                stats = data["depth"].get("depth_stats")
                if stats:
                    meta["depth_stats"] = {
                        "min_mm": stats.min_mm,
                        "max_mm": stats.max_mm,
                        "mean_mm": stats.mean_mm,
                        "coverage": stats.coverage,
                    }
                if "pointcloud_path" in data["depth"]:
                    meta["pointcloud_path"] = data["depth"]["pointcloud_path"]
                    meta["pointcloud_points"] = data["depth"]["pointcloud_points"]
            camera_meta[position] = meta

        return CapturedEvidence(
            observation_id=stable_id,
            task_id=request.task_id,
            place_id=request.place_id,
            capture_kind=request.capture_kind,
            capture_profile=request.capture_profile,
            artifact_uri=f"file://{artifact_dir}",
            summary=vlm_result["raw_text"][:500],
            confidence=0.85,
            outcome_code=OutcomeCode.OBSERVATION_CAPTURED,
            structured_data_json={
                "cameras": camera_meta,
                "vlm_model": vlm_result["model_id"],
                "capture_kind": request.capture_kind,
            },
        )

    def verify_condition(
        self,
        request: ConditionVerificationRequest | dict[str, Any],
    ) -> ConditionAnalysisResult:
        """Capture fresh images and ask the VLM to evaluate a condition."""
        if not isinstance(request, ConditionVerificationRequest):
            request = ConditionVerificationRequest.model_validate(request)

        captures = self._capture_all_cameras(request.task_id, request.target_id)

        image_list: list[tuple[str, str]] = []
        for position, data in sorted(captures.items()):
            b64 = data.get("image_b64")
            if b64 and data.get("image_format") == "jpeg":
                orientation = data.get("orientation", "unknown")
                image_list.append((f"{position} ({orientation})", b64))

        depth_ctx = self._depth_context_summary(captures)
        prompt = (
            f"You are analyzing images from a Boston Dynamics Spot robot to verify "
            f"a condition.\n\n"
            f"Target: {request.target_type.value} '{request.target_id}'\n"
            f"Condition to verify: '{request.condition_id}'\n\n"
            f"Depth sensor readings per camera:\n{depth_ctx}\n\n"
            f"Based on what you can see across all cameras, answer:\n"
            f"1. VERDICT: Is the condition TRUE, FALSE, or INCONCLUSIVE?\n"
            f"2. CONFIDENCE: A number from 0.0 to 1.0\n"
            f"3. RATIONALE: Brief explanation of what you observed\n\n"
            f"Respond in exactly this format:\n"
            f"VERDICT: <TRUE|FALSE|INCONCLUSIVE>\n"
            f"CONFIDENCE: <0.0-1.0>\n"
            f"RATIONALE: <explanation>"
        )

        vlm_result = self._vlm_analyze(prompt, image_list)
        text = vlm_result["raw_text"]

        # Parse structured response
        verdict = ConditionVerdict.INCONCLUSIVE
        confidence = 0.5
        rationale = text

        for line in text.split("\n"):
            line = line.strip()
            if line.startswith("VERDICT:"):
                v = line.split(":", 1)[1].strip().upper()
                if "TRUE" in v:
                    verdict = ConditionVerdict.TRUE
                elif "FALSE" in v:
                    verdict = ConditionVerdict.FALSE
                else:
                    verdict = ConditionVerdict.INCONCLUSIVE
            elif line.startswith("CONFIDENCE:"):
                try:
                    confidence = float(line.split(":", 1)[1].strip())
                    confidence = max(0.0, min(1.0, confidence))
                except ValueError:
                    pass
            elif line.startswith("RATIONALE:"):
                rationale = line.split(":", 1)[1].strip()

        outcome = (
            OutcomeCode.INSPECTION_COMPLETED
            if verdict != ConditionVerdict.INCONCLUSIVE
            else OutcomeCode.INSPECTION_INCONCLUSIVE
        )

        return ConditionAnalysisResult(
            task_id=request.task_id,
            target_type=request.target_type,
            target_id=request.target_id,
            condition_id=request.condition_id,
            result=verdict,
            confidence=confidence,
            rationale=rationale,
            evidence_ids=list(request.evidence_ids),
            outcome_code=outcome,
            structured_data_json={
                "vlm_model": vlm_result["model_id"],
                "vlm_raw": text[:500],
            },
        )


def _capture_request_key(request: CaptureEvidenceRequest) -> str:
    return json.dumps(request.model_dump(mode="json"), sort_keys=True)


def _condition_request_key(request: ConditionVerificationRequest) -> str:
    return json.dumps(request.model_dump(mode="json"), sort_keys=True)


def _stable_id(prefix: str, key: str) -> str:
    digest = sha256(key.encode("utf-8")).hexdigest()
    return f"{prefix}_{digest[:16]}"


def _bounded_confidence(seed: int, *, lower: float, upper: float) -> float:
    span = upper - lower
    scaled = lower + (seed / 255.0) * span
    return round(min(upper, max(lower, scaled)), 3)


__all__ = [
    "CaptureEvidenceRequest",
    "CapturedEvidence",
    "ConditionAnalysisResult",
    "ConditionVerificationRequest",
    "FakePerceptionAdapter",
    "PerceptionAdapter",
    "RealPerceptionAdapter",
]
