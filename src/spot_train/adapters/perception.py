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
    """Stable interface stub for the eventual live perception integration."""

    def capture_evidence(
        self,
        request: CaptureEvidenceRequest | dict[str, Any],
    ) -> CapturedEvidence:
        raise NotImplementedError(
            "Real perception capture is not implemented yet; use FakePerceptionAdapter."
        )

    def verify_condition(
        self,
        request: ConditionVerificationRequest | dict[str, Any],
    ) -> ConditionAnalysisResult:
        raise NotImplementedError(
            "Real condition verification is not implemented yet; use FakePerceptionAdapter."
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
