from __future__ import annotations

import pytest
from pydantic import ValidationError

from spot_train.models import ConditionVerdict, EntityType, OutcomeCode, ResolutionMode
from spot_train.tools.contracts import (
    CaptureEvidenceRequest,
    NavigateToPlaceRequest,
    RankedTargetCandidate,
    ResolveTargetData,
    ResolveTargetRequest,
    ToolBlockedResponse,
    ToolErrorCategory,
    ToolErrorEnvelope,
    ToolFailedResponse,
    ToolInconclusiveResponse,
    ToolSuccessResponse,
    VerifyConditionRequest,
    blocked_response,
    failed_response,
    inconclusive_response,
    policy_rejection_error,
    request_model_for_tool,
    schema_validation_error,
    success_response,
)


def test_request_models_validate_expected_fields() -> None:
    resolve_request = ResolveTargetRequest(name="optics bench")
    navigate_request = NavigateToPlaceRequest(place_id="plc_optics_bench", timeout_s=30)
    verify_request = VerifyConditionRequest(
        target_type=EntityType.PLACE,
        target_id="plc_optics_bench",
        condition_id="area_clear",
        evidence_ids=["obs_123"],
    )
    capture_request = CaptureEvidenceRequest(
        place_id="plc_optics_bench",
        capture_kind="overview_image",
    )

    assert resolve_request.min_confidence == 0.70
    assert navigate_request.route_policy == "default"
    assert verify_request.evidence_ids == ["obs_123"]
    assert capture_request.capture_kind == "overview_image"


def test_request_models_reject_invalid_input() -> None:
    with pytest.raises(ValidationError):
        ResolveTargetRequest(name="", min_confidence=1.2)

    with pytest.raises(ValidationError):
        NavigateToPlaceRequest(place_id="", timeout_s=-1)

    with pytest.raises(ValidationError):
        VerifyConditionRequest(
            target_type=EntityType.PLACE,
            target_id="",
            condition_id="",
        )


def test_success_response_serializes_typed_payload() -> None:
    payload = ResolveTargetData(
        selected_target_type=EntityType.PLACE,
        selected_target_id="plc_optics_bench",
        selected_target_name="Optics Bench",
        resolution_mode=ResolutionMode.EXACT,
        ranked_candidates=[
            RankedTargetCandidate(
                target_type=EntityType.PLACE,
                target_id="plc_optics_bench",
                target_name="Optics Bench",
                confidence=0.99,
            )
        ],
    )

    response = success_response(
        outcome_code=OutcomeCode.RESOLVED_EXACT,
        data=payload,
        confidence=0.99,
        evidence_ids=["obs_001"],
        next_recommended_actions=["get_place_context"],
    )

    assert isinstance(response, ToolSuccessResponse)
    assert response.status.value == "success"
    assert response.data["selected_target_id"] == "plc_optics_bench"
    assert response.evidence_ids == ["obs_001"]
    assert response.next_recommended_actions == ["get_place_context"]


def test_non_success_envelopes_include_required_fields() -> None:
    blocked = blocked_response(
        outcome_code=OutcomeCode.AMBIGUOUS_LOW_CONFIDENCE,
        message="No candidate met minimum confidence.",
        confidence=0.42,
        details={"ranked_candidates": ["optics bench", "bench alpha"]},
    )
    failed = failed_response(
        outcome_code=OutcomeCode.NAVIGATION_FAILED,
        message="Navigation failed.",
        retryable=True,
        details={"error_code": "navigation_failed"},
    )
    inconclusive = inconclusive_response(
        outcome_code=OutcomeCode.INSPECTION_INCONCLUSIVE,
        message="Evidence confidence too low.",
        confidence=0.31,
    )

    assert isinstance(blocked, ToolBlockedResponse)
    assert isinstance(failed, ToolFailedResponse)
    assert isinstance(inconclusive, ToolInconclusiveResponse)
    assert blocked.retryable is False
    assert failed.retryable is True
    assert inconclusive.confidence == 0.31


def test_structured_error_helpers_emit_expected_shape() -> None:
    schema_error = schema_validation_error(
        field_errors={"place_id": ["Field required"]},
        details={"tool_name": "navigate_to_place"},
    )
    policy_error = policy_rejection_error(
        code="approval_required",
        message="Navigation requires operator approval.",
        details={"approval_profile_id": "apr_default_dry_run"},
    )

    assert isinstance(schema_error, ToolErrorEnvelope)
    assert schema_error.status == "error"
    assert schema_error.error.category == ToolErrorCategory.SCHEMA_VALIDATION
    assert schema_error.error.field_errors["place_id"] == ["Field required"]
    assert policy_error.error.category == ToolErrorCategory.POLICY_ENFORCEMENT
    assert policy_error.error.code == "approval_required"
    assert policy_error.error.details["approval_profile_id"] == "apr_default_dry_run"


def test_request_model_lookup_covers_supported_tools() -> None:
    assert request_model_for_tool("resolve_target") is ResolveTargetRequest
    assert request_model_for_tool("verify_condition") is VerifyConditionRequest

    with pytest.raises(KeyError):
        request_model_for_tool("unsupported_tool")


def test_response_models_round_trip_with_verdict_payloads() -> None:
    verdict_response = success_response(
        outcome_code=OutcomeCode.INSPECTION_COMPLETED,
        data={
            "result": ConditionVerdict.TRUE.value,
            "confidence": 0.9,
            "evidence_ids": ["obs_1"],
        },
    )

    assert verdict_response.data["result"] == ConditionVerdict.TRUE.value
    assert verdict_response.data["confidence"] == 0.9
