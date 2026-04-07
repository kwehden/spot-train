"""Typed tool request and response contracts."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import Field

from spot_train.models import (
    ConditionVerdict,
    EntityType,
    LookupTargetType,
    OutcomeCode,
    ResolutionMode,
    SpotTrainModel,
    TaskStatus,
)

JsonDict = dict[str, Any]


class ToolResponseStatus(str, Enum):
    """Top-level tool response status values."""

    SUCCESS = "success"
    BLOCKED = "blocked"
    FAILED = "failed"
    INCONCLUSIVE = "inconclusive"


class ToolErrorCategory(str, Enum):
    """Structured error categories for contract-level rejections."""

    SCHEMA_VALIDATION = "schema_validation"
    POLICY_ENFORCEMENT = "policy_enforcement"


class ToolRequest(SpotTrainModel):
    """Base class for all agent-facing tool requests."""


class ResolveTargetRequest(ToolRequest):
    name: str = Field(min_length=1)
    target_type: LookupTargetType = LookupTargetType.AUTO
    min_confidence: float = Field(default=0.70, ge=0.0, le=1.0)


class GetPlaceContextRequest(ToolRequest):
    place_id: str = Field(min_length=1)


class NavigateToPlaceRequest(ToolRequest):
    place_id: str = Field(min_length=1)
    route_policy: str = Field(default="default", min_length=1)
    approval_profile_id: str | None = None
    timeout_s: int | None = Field(default=None, ge=0)


class InspectPlaceRequest(ToolRequest):
    place_id: str = Field(min_length=1)
    inspection_profile_id: str = Field(min_length=1)


class CaptureEvidenceRequest(ToolRequest):
    place_id: str = Field(min_length=1)
    capture_kind: str = Field(min_length=1)
    capture_profile: str | None = None


class VerifyConditionRequest(ToolRequest):
    target_type: EntityType
    target_id: str = Field(min_length=1)
    condition_id: str = Field(min_length=1)
    evidence_ids: list[str] | None = None


class RelocalizeRequest(ToolRequest):
    place_id: str | None = None
    strategy: str = Field(default="nearest_hint", min_length=1)


class GetOperatorStatusRequest(ToolRequest):
    task_id: str | None = None


class SummarizeTaskRequest(ToolRequest):
    task_id: str = Field(min_length=1)


class RankedTargetCandidate(SpotTrainModel):
    target_type: EntityType
    target_id: str
    target_name: str
    confidence: float = Field(ge=0.0, le=1.0)


class ResolveTargetData(SpotTrainModel):
    selected_target_type: EntityType
    selected_target_id: str
    selected_target_name: str
    resolution_mode: ResolutionMode
    ranked_candidates: list[RankedTargetCandidate] = Field(default_factory=list)


class PlaceContextData(SpotTrainModel):
    canonical_name: str
    aliases: list[str] = Field(default_factory=list)
    zone: str | None = None
    last_visited_at: str | None = None
    last_observed_at: str | None = None
    explicit_familiarity: JsonDict | None = None
    derived_familiarity: JsonDict | None = None
    known_assets: list[JsonDict] = Field(default_factory=list)
    known_risks: list[str] = Field(default_factory=list)


class NavigateToPlaceData(SpotTrainModel):
    place_id: str
    route_policy: str
    approval_profile_id: str | None = None
    visit_status: str | None = None


class InspectPlaceData(SpotTrainModel):
    observation_ids: list[str] = Field(default_factory=list)
    condition_results: list[JsonDict] = Field(default_factory=list)
    inspection_summary: str | None = None


class CaptureEvidenceData(SpotTrainModel):
    observation_id: str
    artifact_uri: str | None = None
    summary: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class VerifyConditionData(SpotTrainModel):
    result: ConditionVerdict
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    rationale: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)


class RelocalizeData(SpotTrainModel):
    strategy: str
    place_id: str | None = None


class OperatorStatusData(SpotTrainModel):
    active_task: JsonDict | None = None
    supervisor_state: TaskStatus | None = None
    latest_step: JsonDict | None = None
    approval_pending: bool = False
    stop_state: str | None = None
    recent_evidence_ids: list[str] = Field(default_factory=list)


class TaskSummaryData(SpotTrainModel):
    status: TaskStatus
    resolved_target: JsonDict | None = None
    result_summary: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    condition_results: list[JsonDict] = Field(default_factory=list)


class ToolResponse(SpotTrainModel):
    status: ToolResponseStatus
    outcome_code: OutcomeCode
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    data: JsonDict = Field(default_factory=dict)
    evidence_ids: list[str] = Field(default_factory=list)


class ToolSuccessResponse(ToolResponse):
    status: Literal[ToolResponseStatus.SUCCESS] = ToolResponseStatus.SUCCESS
    next_recommended_actions: list[str] = Field(default_factory=list)


class ToolBlockedResponse(ToolResponse):
    status: Literal[ToolResponseStatus.BLOCKED] = ToolResponseStatus.BLOCKED
    retryable: bool = False
    message: str
    details: JsonDict = Field(default_factory=dict)


class ToolFailedResponse(ToolResponse):
    status: Literal[ToolResponseStatus.FAILED] = ToolResponseStatus.FAILED
    retryable: bool = False
    message: str
    details: JsonDict = Field(default_factory=dict)


class ToolInconclusiveResponse(ToolResponse):
    status: Literal[ToolResponseStatus.INCONCLUSIVE] = ToolResponseStatus.INCONCLUSIVE
    retryable: bool = False
    message: str
    details: JsonDict = Field(default_factory=dict)


class ToolError(SpotTrainModel):
    category: ToolErrorCategory
    code: str
    message: str
    field_errors: dict[str, list[str]] = Field(default_factory=dict)
    details: JsonDict = Field(default_factory=dict)


class ToolErrorEnvelope(SpotTrainModel):
    status: Literal["error"] = "error"
    error: ToolError


class RequestEnvelope(SpotTrainModel):
    tool_name: str
    request: ToolRequest


class ResponseEnvelope(SpotTrainModel):
    tool_name: str
    response: (
        ToolSuccessResponse
        | ToolBlockedResponse
        | ToolFailedResponse
        | ToolInconclusiveResponse
    )


ResponseLike = (
    ToolSuccessResponse | ToolBlockedResponse | ToolFailedResponse | ToolInconclusiveResponse
)


REQUEST_MODEL_BY_TOOL: dict[str, type[ToolRequest]] = {
    "resolve_target": ResolveTargetRequest,
    "get_place_context": GetPlaceContextRequest,
    "navigate_to_place": NavigateToPlaceRequest,
    "inspect_place": InspectPlaceRequest,
    "capture_evidence": CaptureEvidenceRequest,
    "verify_condition": VerifyConditionRequest,
    "relocalize": RelocalizeRequest,
    "get_operator_status": GetOperatorStatusRequest,
    "summarize_task": SummarizeTaskRequest,
}


def success_response(
    *,
    outcome_code: OutcomeCode,
    data: SpotTrainModel | JsonDict | None = None,
    confidence: float | None = None,
    evidence_ids: list[str] | None = None,
    next_recommended_actions: list[str] | None = None,
) -> ToolSuccessResponse:
    return ToolSuccessResponse(
        outcome_code=outcome_code,
        confidence=confidence,
        data=_serialize_data(data),
        evidence_ids=evidence_ids or [],
        next_recommended_actions=next_recommended_actions or [],
    )


def blocked_response(
    *,
    outcome_code: OutcomeCode,
    message: str,
    data: SpotTrainModel | JsonDict | None = None,
    confidence: float | None = None,
    evidence_ids: list[str] | None = None,
    retryable: bool = False,
    details: JsonDict | None = None,
) -> ToolBlockedResponse:
    return ToolBlockedResponse(
        outcome_code=outcome_code,
        message=message,
        confidence=confidence,
        data=_serialize_data(data),
        evidence_ids=evidence_ids or [],
        retryable=retryable,
        details=details or {},
    )


def failed_response(
    *,
    outcome_code: OutcomeCode,
    message: str,
    data: SpotTrainModel | JsonDict | None = None,
    confidence: float | None = None,
    evidence_ids: list[str] | None = None,
    retryable: bool = False,
    details: JsonDict | None = None,
) -> ToolFailedResponse:
    return ToolFailedResponse(
        outcome_code=outcome_code,
        message=message,
        confidence=confidence,
        data=_serialize_data(data),
        evidence_ids=evidence_ids or [],
        retryable=retryable,
        details=details or {},
    )


def inconclusive_response(
    *,
    outcome_code: OutcomeCode,
    message: str,
    data: SpotTrainModel | JsonDict | None = None,
    confidence: float | None = None,
    evidence_ids: list[str] | None = None,
    retryable: bool = False,
    details: JsonDict | None = None,
) -> ToolInconclusiveResponse:
    return ToolInconclusiveResponse(
        outcome_code=outcome_code,
        message=message,
        confidence=confidence,
        data=_serialize_data(data),
        evidence_ids=evidence_ids or [],
        retryable=retryable,
        details=details or {},
    )


def schema_validation_error(
    *,
    code: str = "invalid_tool_request",
    message: str = "Tool request failed schema validation.",
    field_errors: dict[str, list[str]] | None = None,
    details: JsonDict | None = None,
) -> ToolErrorEnvelope:
    return ToolErrorEnvelope(
        error=ToolError(
            category=ToolErrorCategory.SCHEMA_VALIDATION,
            code=code,
            message=message,
            field_errors=field_errors or {},
            details=details or {},
        )
    )


def policy_rejection_error(
    *,
    code: str = "tool_request_rejected",
    message: str = "Tool request violated policy.",
    field_errors: dict[str, list[str]] | None = None,
    details: JsonDict | None = None,
) -> ToolErrorEnvelope:
    return ToolErrorEnvelope(
        error=ToolError(
            category=ToolErrorCategory.POLICY_ENFORCEMENT,
            code=code,
            message=message,
            field_errors=field_errors or {},
            details=details or {},
        )
    )


def request_model_for_tool(tool_name: str) -> type[ToolRequest]:
    try:
        return REQUEST_MODEL_BY_TOOL[tool_name]
    except KeyError as exc:
        raise KeyError(f"Unknown tool contract: {tool_name}") from exc


def _serialize_data(data: SpotTrainModel | JsonDict | None) -> JsonDict:
    if data is None:
        return {}
    if isinstance(data, SpotTrainModel):
        return data.model_dump(mode="json")
    return data


__all__ = [
    "CaptureEvidenceData",
    "CaptureEvidenceRequest",
    "GetOperatorStatusRequest",
    "GetPlaceContextRequest",
    "InspectPlaceData",
    "InspectPlaceRequest",
    "NavigateToPlaceData",
    "NavigateToPlaceRequest",
    "OperatorStatusData",
    "RankedTargetCandidate",
    "RelocalizeData",
    "RelocalizeRequest",
    "REQUEST_MODEL_BY_TOOL",
    "RequestEnvelope",
    "ResolveTargetData",
    "ResolveTargetRequest",
    "ResponseEnvelope",
    "ResponseLike",
    "SummarizeTaskRequest",
    "TaskSummaryData",
    "ToolBlockedResponse",
    "ToolError",
    "ToolErrorCategory",
    "ToolErrorEnvelope",
    "ToolFailedResponse",
    "ToolInconclusiveResponse",
    "ToolRequest",
    "ToolResponse",
    "ToolResponseStatus",
    "ToolSuccessResponse",
    "VerifyConditionData",
    "VerifyConditionRequest",
    "blocked_response",
    "failed_response",
    "inconclusive_response",
    "policy_rejection_error",
    "request_model_for_tool",
    "schema_validation_error",
    "success_response",
]
