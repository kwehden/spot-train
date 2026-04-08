"""Core domain models for tasks, places, observations, and profiles."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from spot_train.ids import (
    generate_alias_id,
    generate_approval_profile_id,
    generate_asset_id,
    generate_condition_result_id,
    generate_graph_ref_id,
    generate_inspection_profile_id,
    generate_observation_id,
    generate_operator_event_id,
    generate_place_id,
    generate_step_id,
    generate_task_id,
)

JsonDict = dict[str, Any]
JsonList = list[Any]


class StringEnum(str, Enum):
    """Base enum that serializes as a plain string."""

    def __str__(self) -> str:
        return str(self.value)


class EntityType(StringEnum):
    PLACE = "place"
    ASSET = "asset"


class LookupTargetType(StringEnum):
    PLACE = "place"
    ASSET = "asset"
    AUTO = "auto"


class AliasType(StringEnum):
    OPERATOR_DEFINED = "operator_defined"
    IMPORTED = "imported"
    LEARNED = "learned"


class FamiliarityBand(StringEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ResolutionMode(StringEnum):
    EXACT = "exact"
    BEST_EFFORT = "best_effort"


class TaskStatus(StringEnum):
    CREATED = "created"
    RESOLVING_TARGET = "resolving_target"
    READY = "ready"
    AWAITING_APPROVAL = "awaiting_approval"
    EXECUTING = "executing"
    RECOVERING = "recovering"
    SUMMARIZING = "summarizing"
    COMPLETED = "completed"
    INCONCLUSIVE = "inconclusive"
    BLOCKED = "blocked"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskOutcome(StringEnum):
    COMPLETED = "completed"
    INCONCLUSIVE = "inconclusive"
    BLOCKED = "blocked"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StepState(StringEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    BLOCKED = "blocked"
    INCONCLUSIVE = "inconclusive"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ConditionVerdict(StringEnum):
    TRUE = "true"
    FALSE = "false"
    INCONCLUSIVE = "inconclusive"


class OutcomeCode(StringEnum):
    RESOLVED_EXACT = "resolved_exact"
    RESOLVED_BEST_EFFORT = "resolved_best_effort"
    AMBIGUOUS_LOW_CONFIDENCE = "ambiguous_low_confidence"
    UNKNOWN_TARGET = "unknown_target"
    NAVIGATION_STARTED = "navigation_started"
    NAVIGATION_SUCCEEDED = "navigation_succeeded"
    APPROVAL_REQUIRED = "approval_required"
    APPROVAL_DENIED = "approval_denied"
    NAVIGATION_FAILED = "navigation_failed"
    RELOCALIZATION_REQUIRED = "relocalization_required"
    INSPECTION_COMPLETED = "inspection_completed"
    INSPECTION_INCONCLUSIVE = "inspection_inconclusive"
    EVIDENCE_CAPTURE_FAILED = "evidence_capture_failed"
    OBSERVATION_CAPTURED = "observation_captured"
    PERCEPTION_INCONCLUSIVE = "perception_inconclusive"
    CAPTURE_FAILED = "capture_failed"
    RELOCALIZATION_SUCCEEDED = "relocalization_succeeded"
    RELOCALIZATION_FAILED = "relocalization_failed"
    TASK_COMPLETED = "task_completed"
    TASK_INCONCLUSIVE = "task_inconclusive"
    TASK_BLOCKED = "task_blocked"
    TASK_FAILED = "task_failed"
    TASK_CANCELLED = "task_cancelled"


class OperatorEventType(StringEnum):
    APPROVAL_GRANTED = "approval_granted"
    APPROVAL_DENIED = "approval_denied"
    STOP_REQUESTED = "stop_requested"
    TASK_CANCEL_REQUESTED = "task_cancel_requested"
    POWER_ON = "power_on"
    POWER_OFF = "power_off"
    SIT = "sit"


class ModelSource(StringEnum):
    TERMINAL = "terminal"
    RIDEALONG_UI = "ridealong_ui"
    AGENT = "agent"
    SUPERVISOR = "supervisor"
    SYSTEM = "system"


class SpotTrainModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class TimestampedModel(SpotTrainModel):
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Place(TimestampedModel):
    place_id: str = Field(default_factory=generate_place_id)
    canonical_name: str
    zone: str | None = None
    tags_json: list[str] = Field(default_factory=list)
    active: bool = True
    explicit_familiarity_score: float | None = Field(default=None, ge=0.0, le=1.0)
    explicit_familiarity_band: FamiliarityBand | None = None
    last_visited_at: datetime | None = None
    last_observed_at: datetime | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def infer_familiarity_band(self) -> "Place":
        if self.explicit_familiarity_band is None and self.explicit_familiarity_score is not None:
            if self.explicit_familiarity_score >= 0.8:
                self.explicit_familiarity_band = FamiliarityBand.HIGH
            elif self.explicit_familiarity_score >= 0.4:
                self.explicit_familiarity_band = FamiliarityBand.MEDIUM
            else:
                self.explicit_familiarity_band = FamiliarityBand.LOW
        return self


class PlaceAlias(SpotTrainModel):
    alias_id: str = Field(default_factory=generate_alias_id)
    place_id: str
    alias: str
    alias_type: AliasType = AliasType.OPERATOR_DEFINED
    confidence_hint: float | None = Field(default=None, ge=0.0, le=1.0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class GraphRef(TimestampedModel):
    graph_ref_id: str = Field(default_factory=generate_graph_ref_id)
    place_id: str
    graph_id: str | None = None
    waypoint_id: str | None = None
    waypoint_snapshot_id: str | None = None
    anchor_hint: str | None = None
    route_policy: str | None = None
    relocalization_hint_json: JsonDict = Field(default_factory=dict)
    active: bool = True


class Asset(TimestampedModel):
    asset_id: str = Field(default_factory=generate_asset_id)
    place_id: str
    canonical_name: str
    asset_type: str
    tags_json: list[str] = Field(default_factory=list)
    status_hint: str | None = None
    last_observed_at: datetime | None = None
    notes: str | None = None


class AssetAlias(SpotTrainModel):
    alias_id: str = Field(default_factory=generate_alias_id)
    asset_id: str
    alias: str
    alias_type: AliasType = AliasType.OPERATOR_DEFINED
    confidence_hint: float | None = Field(default=None, ge=0.0, le=1.0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class CaptureSpec(SpotTrainModel):
    capture_kind: str
    capture_profile: str | None = None
    description: str | None = None
    parameters: JsonDict = Field(default_factory=dict)


class ConditionSpec(SpotTrainModel):
    condition_id: str
    target_type: EntityType = EntityType.PLACE
    target_id: str | None = None
    description: str | None = None
    parameters: JsonDict = Field(default_factory=dict)


class InspectionProfile(TimestampedModel):
    profile_id: str = Field(default_factory=generate_inspection_profile_id)
    name: str
    description: str | None = None
    required_evidence_json: list[str] = Field(default_factory=list)
    conditions_json: list[ConditionSpec] = Field(default_factory=list)
    capture_plan_json: list[CaptureSpec] = Field(default_factory=list)
    approval_profile_id: str | None = None
    timeout_s: int | None = Field(default=None, ge=0)
    retry_limit: int | None = Field(default=None, ge=0)
    active: bool = True


class ApprovalProfile(TimestampedModel):
    approval_profile_id: str = Field(default_factory=generate_approval_profile_id)
    name: str
    requires_navigation_approval: bool = False
    requires_inspection_approval: bool = False
    requires_retry_approval: bool = False
    notes: str | None = None


class Task(SpotTrainModel):
    task_id: str = Field(default_factory=generate_task_id)
    instruction: str
    operator_session_id: str | None = None
    resolved_target_type: EntityType | None = None
    resolved_target_id: str | None = None
    resolution_mode: ResolutionMode | None = None
    resolution_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    inspection_profile_id: str | None = None
    status: TaskStatus = TaskStatus.CREATED
    outcome_code: OutcomeCode | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: datetime | None = None
    ended_at: datetime | None = None
    result_summary: str | None = None


class TaskStep(SpotTrainModel):
    step_id: str = Field(default_factory=generate_step_id)
    task_id: str
    sequence_no: int = Field(ge=1)
    tool_name: str
    step_state: StepState
    inputs_json: JsonDict = Field(default_factory=dict)
    outputs_json: JsonDict | None = None
    error_code: str | None = None
    retry_count: int = Field(default=0, ge=0)
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    ended_at: datetime | None = None


class Observation(SpotTrainModel):
    observation_id: str = Field(default_factory=generate_observation_id)
    task_id: str
    place_id: str | None = None
    asset_id: str | None = None
    observation_kind: str
    source: str
    artifact_uri: str | None = None
    summary: str | None = None
    structured_data_json: JsonDict = Field(default_factory=dict)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    captured_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ConditionResult(SpotTrainModel):
    condition_result_id: str = Field(default_factory=generate_condition_result_id)
    task_id: str
    target_type: EntityType
    target_id: str
    condition_id: str
    result: ConditionVerdict
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    evidence_ids_json: list[str] = Field(default_factory=list)
    rationale: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class FamiliarityFactors(SpotTrainModel):
    place_id: str
    visit_count: int = Field(default=0, ge=0)
    successful_localizations: int = Field(default=0, ge=0)
    failed_localizations: int = Field(default=0, ge=0)
    last_successful_localization_at: datetime | None = None
    observation_freshness_s: int | None = Field(default=None, ge=0)
    alias_resolution_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    view_coverage_score: float | None = Field(default=None, ge=0.0, le=1.0)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class OperatorEvent(SpotTrainModel):
    operator_event_id: str = Field(default_factory=generate_operator_event_id)
    task_id: str | None = None
    event_type: OperatorEventType
    operator_id: str | None = None
    source: ModelSource | str
    details_json: JsonDict = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


__all__ = [
    "AliasType",
    "ApprovalProfile",
    "Asset",
    "AssetAlias",
    "CaptureSpec",
    "ConditionResult",
    "ConditionSpec",
    "ConditionVerdict",
    "EntityType",
    "FamiliarityBand",
    "FamiliarityFactors",
    "GraphRef",
    "InspectionProfile",
    "JsonDict",
    "JsonList",
    "LookupTargetType",
    "ModelSource",
    "Observation",
    "OperatorEvent",
    "OperatorEventType",
    "OutcomeCode",
    "Place",
    "PlaceAlias",
    "ResolutionMode",
    "StepState",
    "Task",
    "TaskOutcome",
    "TaskStatus",
    "TaskStep",
]
