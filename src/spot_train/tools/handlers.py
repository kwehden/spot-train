"""Thin tool handlers that route through the supervisor or repository."""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

from pydantic import ValidationError

from spot_train.adapters.perception import (
    CaptureEvidenceRequest as AdapterCaptureEvidenceRequest,
)
from spot_train.adapters.perception import (
    ConditionVerificationRequest as AdapterConditionVerificationRequest,
)
from spot_train.adapters.perception import (
    PerceptionAdapter,
)
from spot_train.adapters.spot import (
    SpotActionStatus,
    SpotAdapter,
    SpotNavigationIntent,
    SpotRelocalizeIntent,
)
from spot_train.memory.repository import WorldRepository
from spot_train.models import (
    ConditionResult,
    ConditionVerdict,
    EntityType,
    Observation,
    OutcomeCode,
    ResolutionMode,
    StepState,
    TaskStatus,
)
from spot_train.observability import timed
from spot_train.supervisor.runner import (
    ExecutionContext,
    PreconditionCheck,
    StepExecutionResult,
    StepOperation,
    SupervisorRunner,
    SupervisorStep,
)
from spot_train.tools.contracts import (
    CaptureEvidenceRequest,
    GetOperatorStatusRequest,
    GetPlaceContextRequest,
    InspectPlaceData,
    InspectPlaceRequest,
    NavigateToPlaceData,
    NavigateToPlaceRequest,
    OperatorStatusData,
    RankedTargetCandidate,
    RelocalizeData,
    RelocalizeRequest,
    RequestEnvelope,
    ResolveTargetData,
    ResolveTargetRequest,
    ResponseLike,
    SummarizeTaskRequest,
    TaskSummaryData,
    ToolErrorEnvelope,
    VerifyConditionData,
    VerifyConditionRequest,
    blocked_response,
    failed_response,
    inconclusive_response,
    policy_rejection_error,
    request_model_for_tool,
    schema_validation_error,
    success_response,
)

HandlerResult = ResponseLike | ToolErrorEnvelope


@dataclass(frozen=True, slots=True)
class ResolutionCandidate:
    target_type: EntityType
    target_id: str
    target_name: str
    confidence: float
    exact: bool = False


class ToolHandlerService:
    """Agent-facing tool layer that validates requests and delegates work."""

    def __init__(
        self,
        repository: WorldRepository,
        *,
        runner: SupervisorRunner | None = None,
        spot_adapter: SpotAdapter | None = None,
        perception_adapter: PerceptionAdapter | None = None,
    ) -> None:
        self.repository = repository
        self.runner = runner
        self.spot_adapter = spot_adapter
        self.perception_adapter = perception_adapter

    def handle(self, tool_name: str, request: dict[str, Any] | Any, **kwargs: Any) -> HandlerResult:
        request_model = request_model_for_tool(tool_name)
        validated = self._validate_request(tool_name, request_model, request)
        if isinstance(validated, ToolErrorEnvelope):
            return validated
        handler = getattr(self, tool_name)
        with timed(tool_name, "tool"):
            return handler(validated, **kwargs)

    def resolve_target(
        self,
        request: ResolveTargetRequest | dict[str, Any],
        *,
        task_id: str | None = None,
    ) -> HandlerResult:
        validated = self._ensure_request("resolve_target", request)
        if isinstance(validated, ToolErrorEnvelope):
            return validated

        candidates = self._rank_candidates(validated.name, validated.target_type)
        if not candidates:
            self._persist_resolution(
                task_id=task_id,
                resolution_mode=None,
                resolution_confidence=0.0,
            )
            return blocked_response(
                outcome_code=OutcomeCode.UNKNOWN_TARGET,
                message="No known target matched the requested name.",
                confidence=0.0,
            )

        exact_candidates = [candidate for candidate in candidates if candidate.exact]
        selected = exact_candidates[0] if exact_candidates else candidates[0]
        ranked_candidates = [self._ranked_candidate(candidate) for candidate in candidates[:5]]

        if exact_candidates:
            self._persist_resolution(
                task_id=task_id,
                selected=selected,
                resolution_mode=ResolutionMode.EXACT,
                resolution_confidence=selected.confidence,
            )
            return success_response(
                outcome_code=OutcomeCode.RESOLVED_EXACT,
                confidence=selected.confidence,
                data=ResolveTargetData(
                    selected_target_type=selected.target_type,
                    selected_target_id=selected.target_id,
                    selected_target_name=selected.target_name,
                    resolution_mode=ResolutionMode.EXACT,
                    ranked_candidates=ranked_candidates,
                ),
            )

        if selected.confidence >= validated.min_confidence:
            self._persist_resolution(
                task_id=task_id,
                selected=selected,
                resolution_mode=ResolutionMode.BEST_EFFORT,
                resolution_confidence=selected.confidence,
            )
            return success_response(
                outcome_code=OutcomeCode.RESOLVED_BEST_EFFORT,
                confidence=selected.confidence,
                data=ResolveTargetData(
                    selected_target_type=selected.target_type,
                    selected_target_id=selected.target_id,
                    selected_target_name=selected.target_name,
                    resolution_mode=ResolutionMode.BEST_EFFORT,
                    ranked_candidates=ranked_candidates,
                ),
            )

        self._persist_resolution(
            task_id=task_id,
            resolution_mode=ResolutionMode.BEST_EFFORT,
            resolution_confidence=selected.confidence,
        )
        ranked_candidate_payload = [
            candidate.model_dump(mode="json") for candidate in ranked_candidates
        ]
        return blocked_response(
            outcome_code=OutcomeCode.AMBIGUOUS_LOW_CONFIDENCE,
            message="No candidate met minimum confidence.",
            confidence=selected.confidence,
            data={"ranked_candidates": ranked_candidate_payload},
            details={"ranked_candidates": ranked_candidate_payload},
        )

    def get_place_context(
        self,
        request: GetPlaceContextRequest | dict[str, Any],
    ) -> HandlerResult:
        validated = self._ensure_request("get_place_context", request)
        if isinstance(validated, ToolErrorEnvelope):
            return validated

        place = self.repository.get_place(validated.place_id)
        if place is None:
            return blocked_response(
                outcome_code=OutcomeCode.UNKNOWN_TARGET,
                message="Requested place is not known to the world model.",
            )

        aliases = [alias.alias for alias in self.repository.list_place_aliases(place.place_id)]
        assets = self.repository.list_assets(place_id=place.place_id)
        derived = self.repository.get_derived_familiarity(place.place_id)
        return success_response(
            outcome_code=OutcomeCode.RESOLVED_EXACT,
            data={
                "canonical_name": place.canonical_name,
                "aliases": aliases,
                "zone": place.zone,
                "last_visited_at": (
                    place.last_visited_at.isoformat() if place.last_visited_at else None
                ),
                "last_observed_at": (
                    place.last_observed_at.isoformat() if place.last_observed_at else None
                ),
                "explicit_familiarity": {
                    "score": place.explicit_familiarity_score,
                    "band": place.explicit_familiarity_band.value
                    if place.explicit_familiarity_band
                    else None,
                },
                "derived_familiarity": (
                    {
                        "score": derived.score,
                        "band": derived.band,
                        "components": {
                            "visit_recency": derived.components.visit_recency,
                            "localization_success_rate": (
                                derived.components.localization_success_rate
                            ),
                            "observation_freshness": derived.components.observation_freshness,
                            "alias_resolution_confidence": (
                                derived.components.alias_resolution_confidence
                            ),
                            "view_coverage": derived.components.view_coverage,
                        },
                    }
                    if derived
                    else None
                ),
                "known_assets": [
                    {
                        "asset_id": asset.asset_id,
                        "canonical_name": asset.canonical_name,
                        "asset_type": asset.asset_type,
                    }
                    for asset in assets
                ],
                "known_risks": [],
            },
        )

    def navigate_to_place(
        self,
        request: NavigateToPlaceRequest | dict[str, Any],
        *,
        task_id: str | None = None,
        operation: StepOperation | None = None,
        precondition: PreconditionCheck | None = None,
        recovery_operation: StepOperation | None = None,
    ) -> HandlerResult:
        validated = self._ensure_request("navigate_to_place", request)
        if isinstance(validated, ToolErrorEnvelope):
            return validated
        resolved_operation = operation
        resolved_recovery_operation = recovery_operation
        success_payload: NavigateToPlaceData | None = NavigateToPlaceData(
            place_id=validated.place_id,
            route_policy=validated.route_policy,
            approval_profile_id=validated.approval_profile_id,
            visit_status="requested",
        )
        if resolved_operation is None and self.spot_adapter is not None:
            resolved_operation = self._build_navigation_operation(validated)
            success_payload = None
        if resolved_recovery_operation is None and self.spot_adapter is not None:
            resolved_recovery_operation = self._build_relocalization_operation(
                RelocalizeRequest(place_id=validated.place_id)
            )
        return self._run_side_effect_tool(
            tool_name="navigate_to_place",
            request=validated,
            task_id=task_id,
            operation=resolved_operation,
            precondition=precondition,
            recovery_operation=resolved_recovery_operation,
            success_data=success_payload,
        )

    def inspect_place(
        self,
        request: InspectPlaceRequest | dict[str, Any],
        *,
        task_id: str | None = None,
        operation: StepOperation | None = None,
        precondition: PreconditionCheck | None = None,
    ) -> HandlerResult:
        validated = self._ensure_request("inspect_place", request)
        if isinstance(validated, ToolErrorEnvelope):
            return validated
        resolved_operation = operation
        success_payload: InspectPlaceData | None = InspectPlaceData()
        if resolved_operation is None and self.perception_adapter is not None:
            resolved_operation = self._build_inspection_operation(validated)
            success_payload = None
        return self._run_side_effect_tool(
            tool_name="inspect_place",
            request=validated,
            task_id=task_id,
            operation=resolved_operation,
            precondition=precondition,
            success_data=success_payload,
        )

    def capture_evidence(
        self,
        request: CaptureEvidenceRequest | dict[str, Any],
        *,
        task_id: str | None = None,
        operation: StepOperation | None = None,
        precondition: PreconditionCheck | None = None,
    ) -> HandlerResult:
        validated = self._ensure_request("capture_evidence", request)
        if isinstance(validated, ToolErrorEnvelope):
            return validated
        resolved_operation = operation
        if resolved_operation is None and self.perception_adapter is not None:
            resolved_operation = self._build_capture_evidence_operation(validated)
        return self._run_side_effect_tool(
            tool_name="capture_evidence",
            request=validated,
            task_id=task_id,
            operation=resolved_operation,
            precondition=precondition,
            success_data=None,
        )

    def verify_condition(
        self,
        request: VerifyConditionRequest | dict[str, Any],
        *,
        task_id: str | None = None,
    ) -> HandlerResult:
        validated = self._ensure_request("verify_condition", request)
        if isinstance(validated, ToolErrorEnvelope):
            return validated
        if task_id is None:
            return policy_rejection_error(
                code="task_id_required",
                message="Condition verification currently requires a task_id context.",
            )

        for result in self.repository.list_condition_results(task_id):
            if (
                result.target_type == validated.target_type
                and result.target_id == validated.target_id
                and result.condition_id == validated.condition_id
            ):
                if validated.evidence_ids and not set(validated.evidence_ids).issubset(
                    set(result.evidence_ids_json)
                ):
                    continue
                return success_response(
                    outcome_code=OutcomeCode.INSPECTION_COMPLETED,
                    confidence=result.confidence,
                    evidence_ids=result.evidence_ids_json,
                    data=VerifyConditionData(
                        result=result.result,
                        confidence=result.confidence,
                        rationale=result.rationale,
                        evidence_ids=result.evidence_ids_json,
                    ),
                )

        return blocked_response(
            outcome_code=OutcomeCode.UNKNOWN_TARGET,
            message="No matching condition result is available for the requested target.",
        )

    def relocalize(
        self,
        request: RelocalizeRequest | dict[str, Any],
        *,
        task_id: str | None = None,
        operation: StepOperation | None = None,
        precondition: PreconditionCheck | None = None,
    ) -> HandlerResult:
        validated = self._ensure_request("relocalize", request)
        if isinstance(validated, ToolErrorEnvelope):
            return validated
        resolved_operation = operation
        success_payload: RelocalizeData | None = RelocalizeData(
            strategy=validated.strategy,
            place_id=validated.place_id,
        )
        if resolved_operation is None and self.spot_adapter is not None:
            resolved_operation = self._build_relocalization_operation(validated)
            success_payload = None
        return self._run_side_effect_tool(
            tool_name="relocalize",
            request=validated,
            task_id=task_id,
            operation=resolved_operation,
            precondition=precondition,
            success_data=success_payload,
        )

    def _build_navigation_operation(
        self,
        request: NavigateToPlaceRequest,
    ) -> StepOperation:
        def operation(context: Any) -> StepExecutionResult:
            adapter = self._require_spot_adapter()
            if adapter is None:
                return StepExecutionResult.failed(
                    outcome_code=OutcomeCode.TASK_FAILED,
                    message="Spot adapter is not configured.",
                    error_code="spot_adapter_required",
                    retryable=False,
                )

            outcome = adapter.navigate(
                SpotNavigationIntent(
                    place_id=request.place_id,
                    route_policy=request.route_policy,
                    approval_profile_id=request.approval_profile_id,
                    timeout_s=request.timeout_s,
                )
            )
            outputs = self._navigation_outputs(outcome)

            if outcome.status == SpotActionStatus.SUCCEEDED:
                return StepExecutionResult.success(
                    outcome_code=outcome.outcome_code,
                    outputs=outputs,
                    confidence=outcome.confidence,
                )
            if outcome.status == SpotActionStatus.RELOCALIZATION_NEEDED:
                return StepExecutionResult(
                    step_state=StepState.FAILED,
                    outcome_code=outcome.outcome_code,
                    message=outcome.message,
                    error_code="relocalization_required",
                    retryable=True,
                    confidence=outcome.confidence,
                    outputs=outputs,
                    details={
                        "recommended_action": outcome.recommended_action,
                        "relocalization_required": outcome.relocalization_required,
                        "stop_state": outcome.stop_state.value,
                    },
                )
            if outcome.status == SpotActionStatus.CANCELLED:
                return StepExecutionResult(
                    step_state=StepState.CANCELLED,
                    outcome_code=outcome.outcome_code,
                    message=outcome.message,
                    error_code="stop_requested",
                    confidence=outcome.confidence,
                    outputs=outputs,
                    details={
                        "recommended_action": outcome.recommended_action,
                        "stop_state": outcome.stop_state.value,
                    },
                )
            return StepExecutionResult(
                step_state=StepState.FAILED,
                outcome_code=outcome.outcome_code,
                message=outcome.message,
                error_code="navigation_failed",
                retryable=True,
                confidence=outcome.confidence,
                outputs=outputs,
                details={
                    "recommended_action": outcome.recommended_action,
                    "stop_state": outcome.stop_state.value,
                },
            )

        return operation

    def _build_relocalization_operation(
        self,
        request: RelocalizeRequest,
    ) -> StepOperation:
        def operation(context: Any) -> StepExecutionResult:
            adapter = self._require_spot_adapter()
            if adapter is None:
                return StepExecutionResult.failed(
                    outcome_code=OutcomeCode.TASK_FAILED,
                    message="Spot adapter is not configured.",
                    error_code="spot_adapter_required",
                    retryable=False,
                )

            outcome = adapter.relocalize(
                SpotRelocalizeIntent(
                    place_id=request.place_id,
                    strategy=request.strategy,
                )
            )
            outputs = self._relocalization_outputs(outcome)

            if outcome.status == SpotActionStatus.SUCCEEDED:
                return StepExecutionResult.success(
                    outcome_code=outcome.outcome_code,
                    outputs=outputs,
                    confidence=outcome.confidence,
                )
            if outcome.status == SpotActionStatus.CANCELLED:
                return StepExecutionResult(
                    step_state=StepState.CANCELLED,
                    outcome_code=outcome.outcome_code,
                    message=outcome.message,
                    error_code="stop_requested",
                    confidence=outcome.confidence,
                    outputs=outputs,
                    details={
                        "recommended_action": outcome.recommended_action,
                        "stop_state": outcome.stop_state.value,
                    },
                )
            return StepExecutionResult(
                step_state=StepState.FAILED,
                outcome_code=outcome.outcome_code,
                message=outcome.message,
                error_code="relocalization_failed",
                retryable=False,
                confidence=outcome.confidence,
                outputs=outputs,
                details={
                    "recommended_action": outcome.recommended_action,
                    "stop_state": outcome.stop_state.value,
                },
            )

        return operation

    def _build_capture_evidence_operation(
        self,
        request: CaptureEvidenceRequest,
    ) -> StepOperation:
        def operation(context: Any) -> StepExecutionResult:
            adapter = self._require_perception_adapter()
            if adapter is None:
                return StepExecutionResult.failed(
                    outcome_code=OutcomeCode.TASK_FAILED,
                    message="Perception adapter is not configured.",
                    error_code="perception_adapter_required",
                    retryable=False,
                )

            adapter_request = AdapterCaptureEvidenceRequest(
                task_id=context.task.task_id,
                place_id=request.place_id,
                capture_kind=request.capture_kind,
                capture_profile=request.capture_profile,
            )
            capture = adapter.capture_evidence(adapter_request)
            observation = self._store_capture_observation(context.task.task_id, capture)
            outputs = self._capture_outputs(observation, capture)

            if capture.outcome_code == OutcomeCode.OBSERVATION_CAPTURED:
                return StepExecutionResult.success(
                    outcome_code=capture.outcome_code,
                    outputs=outputs,
                    confidence=capture.confidence,
                )
            if capture.outcome_code == OutcomeCode.PERCEPTION_INCONCLUSIVE:
                return StepExecutionResult.inconclusive(
                    outcome_code=capture.outcome_code,
                    message=capture.summary,
                    confidence=capture.confidence,
                    outputs=outputs,
                )
            return StepExecutionResult(
                step_state=StepState.FAILED,
                outcome_code=capture.outcome_code,
                message=capture.summary,
                error_code="capture_failed",
                retryable=True,
                confidence=capture.confidence,
                outputs=outputs,
                details={
                    "capture_kind": capture.capture_kind,
                    "inconclusive_reason": capture.inconclusive_reason,
                },
            )

        return operation

    def _build_inspection_operation(
        self,
        request: InspectPlaceRequest,
    ) -> StepOperation:
        def operation(context: Any) -> StepExecutionResult:
            adapter = self._require_perception_adapter()
            if adapter is None:
                return StepExecutionResult.failed(
                    outcome_code=OutcomeCode.TASK_FAILED,
                    message="Perception adapter is not configured.",
                    error_code="perception_adapter_required",
                    retryable=False,
                )

            profile = self.repository.get_inspection_profile(request.inspection_profile_id)
            if profile is None:
                return StepExecutionResult.failed(
                    outcome_code=OutcomeCode.TASK_FAILED,
                    message="Inspection profile is not known to the repository.",
                    error_code="inspection_profile_missing",
                    retryable=False,
                )

            observation_ids: list[str] = []
            condition_results: list[dict[str, Any]] = []
            confidence_values: list[float] = []
            inconclusive = False

            for capture_spec in profile.capture_plan_json:
                capture = adapter.capture_evidence(
                    AdapterCaptureEvidenceRequest(
                        task_id=context.task.task_id,
                        place_id=request.place_id,
                        capture_kind=capture_spec.capture_kind,
                        capture_profile=capture_spec.capture_profile,
                    )
                )
                observation = self._store_capture_observation(context.task.task_id, capture)
                observation_ids.append(observation.observation_id)
                if capture.confidence is not None:
                    confidence_values.append(capture.confidence)
                if capture.outcome_code == OutcomeCode.PERCEPTION_INCONCLUSIVE:
                    inconclusive = True

            evidence_ids = list(observation_ids)
            for condition_spec in profile.conditions_json:
                verification = adapter.verify_condition(
                    AdapterConditionVerificationRequest(
                        task_id=context.task.task_id,
                        target_type=condition_spec.target_type,
                        target_id=condition_spec.target_id or request.place_id,
                        condition_id=condition_spec.condition_id,
                        evidence_ids=evidence_ids,
                    )
                )
                self._store_condition_result(context.task.task_id, verification)
                condition_results.append(self._condition_result_payload(verification))
                if verification.confidence is not None:
                    confidence_values.append(verification.confidence)
                if verification.result == ConditionVerdict.INCONCLUSIVE:
                    inconclusive = True

            if not observation_ids:
                return StepExecutionResult.failed(
                    outcome_code=OutcomeCode.EVIDENCE_CAPTURE_FAILED,
                    message="Inspection profile did not produce any evidence.",
                    error_code="inspection_no_evidence",
                    retryable=False,
                )

            inspection_summary = (
                f"Collected {len(observation_ids)} observation(s) and "
                f"{len(condition_results)} condition result(s) for {request.place_id}."
            )
            outputs = {
                "place_id": request.place_id,
                "inspection_profile_id": request.inspection_profile_id,
                "observation_ids": observation_ids,
                "condition_results": condition_results,
                "inspection_summary": inspection_summary,
            }
            confidence = min(confidence_values) if confidence_values else None
            if inconclusive or (confidence is not None and confidence < 0.7):
                return StepExecutionResult.inconclusive(
                    outcome_code=OutcomeCode.INSPECTION_INCONCLUSIVE,
                    message=inspection_summary,
                    confidence=confidence,
                    outputs=outputs,
                )
            return StepExecutionResult.success(
                outcome_code=OutcomeCode.INSPECTION_COMPLETED,
                confidence=confidence,
                outputs=outputs,
            )

        return operation

    def get_operator_status(
        self,
        request: GetOperatorStatusRequest | dict[str, Any],
    ) -> HandlerResult:
        validated = self._ensure_request("get_operator_status", request)
        if isinstance(validated, ToolErrorEnvelope):
            return validated
        if validated.task_id is None:
            stop = self.spot_adapter.stop_state.value if self.spot_adapter else "unknown"
            return success_response(
                outcome_code=OutcomeCode.TASK_COMPLETED,
                data=OperatorStatusData(
                    active_task=None,
                    supervisor_state=None,
                    latest_step=None,
                    approval_pending=False,
                    stop_state=stop,
                    recent_evidence_ids=[],
                ),
            )

        task = self.repository.get_task(validated.task_id)
        if task is None:
            return blocked_response(
                outcome_code=OutcomeCode.UNKNOWN_TARGET,
                message="Requested task is not known.",
            )

        steps = self.repository.list_task_steps(validated.task_id)
        observations = self.repository.list_observations(validated.task_id)
        latest_step = steps[-1] if steps else None
        pending_approval = task.status == TaskStatus.AWAITING_APPROVAL
        stop = self.spot_adapter.stop_state.value if self.spot_adapter else "unknown"
        return success_response(
            outcome_code=task.outcome_code or OutcomeCode.TASK_COMPLETED,
            data=OperatorStatusData(
                active_task={
                    "task_id": task.task_id,
                    "instruction": task.instruction,
                    "status": task.status.value,
                },
                supervisor_state=task.status,
                latest_step=(
                    {
                        "step_id": latest_step.step_id,
                        "tool_name": latest_step.tool_name,
                        "step_state": latest_step.step_state.value,
                    }
                    if latest_step
                    else None
                ),
                approval_pending=pending_approval,
                stop_state=stop,
                recent_evidence_ids=[obs.observation_id for obs in observations[-5:]],
            ),
        )

    def summarize_task(
        self,
        request: SummarizeTaskRequest | dict[str, Any],
    ) -> HandlerResult:
        validated = self._ensure_request("summarize_task", request)
        if isinstance(validated, ToolErrorEnvelope):
            return validated

        task = self.repository.get_task(validated.task_id)
        if task is None:
            return blocked_response(
                outcome_code=OutcomeCode.UNKNOWN_TARGET,
                message="Requested task is not known.",
            )

        observations = self.repository.list_observations(task.task_id)
        condition_results = self.repository.list_condition_results(task.task_id)
        resolved_target = None
        if task.resolved_target_type and task.resolved_target_id:
            resolved_target = {
                "target_type": task.resolved_target_type.value,
                "target_id": task.resolved_target_id,
            }
        summary_text = task.result_summary or self._generate_summary_text(
            task, observations, condition_results
        )
        return success_response(
            outcome_code=task.outcome_code or OutcomeCode.TASK_COMPLETED,
            data=TaskSummaryData(
                status=task.status,
                resolved_target=resolved_target,
                result_summary=summary_text,
                evidence_ids=[observation.observation_id for observation in observations],
                condition_results=[
                    {
                        "condition_id": result.condition_id,
                        "result": result.result.value,
                        "confidence": result.confidence,
                    }
                    for result in condition_results
                ],
            ),
        )

    def _generate_summary_text(
        self,
        task: Any,
        observations: list[Any],
        condition_results: list[Any],
    ) -> str:
        lines = [f"Task: {task.instruction}", f"Status: {task.status.value}"]
        if task.resolved_target_type and task.resolved_target_id:
            lines.append(f"Target: {task.resolved_target_type.value}:{task.resolved_target_id}")
        lines.append(f"Evidence collected: {len(observations)}")
        for cr in condition_results:
            lines.append(
                f"  Condition '{cr.condition_id}': {cr.result.value} (confidence: {cr.confidence})"
            )
        return "\n".join(lines)

    # -- Robot control handlers (routed through supervisor) ----------------

    def power_on(
        self,
        request: Any,
        *,
        task_id: str | None = None,
    ) -> HandlerResult:
        validated = self._ensure_request("power_on", request)
        if isinstance(validated, ToolErrorEnvelope):
            return validated

        def _op(ctx: ExecutionContext) -> StepExecutionResult:
            adapter = self.spot_adapter
            if adapter is None or not hasattr(adapter, "_robot"):
                return StepExecutionResult.failed(
                    message="No robot connected (dry-run mode).",
                    error_code="no_robot",
                )
            try:
                import time

                from bosdyn.client.robot_command import (
                    RobotCommandBuilder,
                    RobotCommandClient,
                )

                adapter._robot.power_on(timeout_sec=20)
                cmd = adapter._robot.ensure_client(RobotCommandClient.default_service_name)
                cmd.robot_command(RobotCommandBuilder.synchro_stand_command(), timeout=10)
                time.sleep(1)
                return StepExecutionResult.success(
                    outputs={"message": "Robot powered on and standing."}
                )
            except Exception as exc:
                return StepExecutionResult.failed(
                    message=f"Power on failed: {exc}", error_code="power_on_error"
                )

        return self._run_side_effect_tool(
            tool_name="power_on",
            request=validated,
            task_id=task_id,
            operation=_op,
            precondition=None,
            success_data={"message": "Robot powered on and standing."},
        )

    def sit(
        self,
        request: Any,
        *,
        task_id: str | None = None,
    ) -> HandlerResult:
        validated = self._ensure_request("sit", request)
        if isinstance(validated, ToolErrorEnvelope):
            return validated

        def _op(ctx: ExecutionContext) -> StepExecutionResult:
            adapter = self.spot_adapter
            if adapter is None or not hasattr(adapter, "_robot"):
                return StepExecutionResult.failed(
                    message="No robot connected (dry-run mode).",
                    error_code="no_robot",
                )
            try:
                from bosdyn.client.robot_command import (
                    RobotCommandBuilder,
                    RobotCommandClient,
                )

                cmd = adapter._robot.ensure_client(RobotCommandClient.default_service_name)
                cmd.robot_command(RobotCommandBuilder.synchro_sit_command(), timeout=10)
                return StepExecutionResult.success(outputs={"message": "Robot is sitting."})
            except Exception as exc:
                return StepExecutionResult.failed(
                    message=f"Sit failed: {exc}", error_code="sit_error"
                )

        return self._run_side_effect_tool(
            tool_name="sit",
            request=validated,
            task_id=task_id,
            operation=_op,
            precondition=None,
            success_data={"message": "Robot is sitting. Motors still on."},
        )

    def power_off(
        self,
        request: Any,
        *,
        task_id: str | None = None,
    ) -> HandlerResult:
        validated = self._ensure_request("power_off", request)
        if isinstance(validated, ToolErrorEnvelope):
            return validated

        def _op(ctx: ExecutionContext) -> StepExecutionResult:
            adapter = self.spot_adapter
            if adapter is None or not hasattr(adapter, "_robot"):
                return StepExecutionResult.failed(
                    message="No robot connected (dry-run mode).",
                    error_code="no_robot",
                )
            try:
                import time

                from bosdyn.client.robot_command import (
                    RobotCommandBuilder,
                    RobotCommandClient,
                )

                cmd = adapter._robot.ensure_client(RobotCommandClient.default_service_name)
                cmd.robot_command(RobotCommandBuilder.synchro_sit_command(), timeout=10)
                time.sleep(2)
                adapter._robot.power_off(cut_immediately=False, timeout_sec=20)
                return StepExecutionResult.success(
                    outputs={"message": "Robot sat down and powered off."}
                )
            except Exception as exc:
                return StepExecutionResult.failed(
                    message=f"Power off failed: {exc}",
                    error_code="power_off_error",
                )

        return self._run_side_effect_tool(
            tool_name="power_off",
            request=validated,
            task_id=task_id,
            operation=_op,
            precondition=None,
            success_data={"message": "Robot sat down and powered off."},
        )

    def request_stop(
        self,
        request: Any,
        *,
        task_id: str | None = None,
    ) -> HandlerResult:
        validated = self._ensure_request("request_stop", request)
        if isinstance(validated, ToolErrorEnvelope):
            return validated

        def _op(ctx: ExecutionContext) -> StepExecutionResult:
            adapter = self.spot_adapter
            if adapter is None:
                return StepExecutionResult.failed(
                    message="No adapter available.", error_code="no_adapter"
                )
            outcome = adapter.request_stop(reason=validated.reason)
            return StepExecutionResult.success(
                outputs={
                    "stop_state": outcome.stop_state.value,
                    "message": outcome.message,
                }
            )

        return self._run_side_effect_tool(
            tool_name="request_stop",
            request=validated,
            task_id=task_id,
            operation=_op,
            precondition=None,
            success_data=None,
        )

    def clear_stop(
        self,
        request: Any,
        *,
        task_id: str | None = None,
    ) -> HandlerResult:
        validated = self._ensure_request("clear_stop", request)
        if isinstance(validated, ToolErrorEnvelope):
            return validated

        def _op(ctx: ExecutionContext) -> StepExecutionResult:
            adapter = self.spot_adapter
            if adapter is None:
                return StepExecutionResult.failed(
                    message="No adapter available.", error_code="no_adapter"
                )
            outcome = adapter.clear_stop()
            return StepExecutionResult.success(
                outputs={
                    "stop_state": outcome.stop_state.value,
                    "message": outcome.message,
                }
            )

        return self._run_side_effect_tool(
            tool_name="clear_stop",
            request=validated,
            task_id=task_id,
            operation=_op,
            precondition=None,
            success_data=None,
        )

    def _validate_request(
        self,
        tool_name: str,
        request_model: type[Any],
        request: dict[str, Any] | Any,
    ) -> Any | ToolErrorEnvelope:
        try:
            if isinstance(request, request_model):
                return request
            validated = request_model.model_validate(request)
            RequestEnvelope(tool_name=tool_name, request=validated)
            return validated
        except ValidationError as exc:
            field_errors: dict[str, list[str]] = {}
            for error in exc.errors():
                location = ".".join(str(part) for part in error["loc"])
                field_errors.setdefault(location, []).append(error["msg"])
            return schema_validation_error(
                field_errors=field_errors,
                details={"tool_name": tool_name},
            )

    def _ensure_request(
        self,
        tool_name: str,
        request: dict[str, Any] | Any,
    ) -> Any | ToolErrorEnvelope:
        return self._validate_request(tool_name, request_model_for_tool(tool_name), request)

    def _rank_candidates(
        self,
        name: str,
        target_type: EntityType | str,
    ) -> list[ResolutionCandidate]:
        normalized_name = _normalize(name)
        candidates: list[ResolutionCandidate] = []

        include_places = target_type in {EntityType.PLACE, "place", "auto"}
        include_assets = target_type in {EntityType.ASSET, "asset", "auto"}

        if include_places:
            for place in self.repository.list_places(active_only=True):
                candidates.append(
                    self._score_place_candidate(
                        place.place_id,
                        place.canonical_name,
                        normalized_name,
                    )
                )
                for alias in self.repository.list_place_aliases(place.place_id):
                    candidates.append(
                        self._score_place_candidate(
                            place.place_id,
                            place.canonical_name,
                            normalized_name,
                            alias.alias,
                        )
                    )

        if include_assets:
            for asset in self.repository.list_assets():
                candidates.append(
                    self._score_asset_candidate(
                        asset.asset_id,
                        asset.canonical_name,
                        normalized_name,
                    )
                )
                for alias in self.repository.list_asset_aliases(asset.asset_id):
                    candidates.append(
                        self._score_asset_candidate(
                            asset.asset_id,
                            asset.canonical_name,
                            normalized_name,
                            alias.alias,
                        )
                    )

        deduped: dict[tuple[EntityType, str], ResolutionCandidate] = {}
        for candidate in candidates:
            key = (candidate.target_type, candidate.target_id)
            previous = deduped.get(key)
            if previous is None or candidate.confidence > previous.confidence:
                deduped[key] = candidate

        return sorted(
            deduped.values(),
            key=lambda candidate: (candidate.confidence, candidate.exact, candidate.target_name),
            reverse=True,
        )

    def _score_place_candidate(
        self,
        place_id: str,
        canonical_name: str,
        normalized_name: str,
        alias: str | None = None,
    ) -> ResolutionCandidate:
        label = alias or canonical_name
        normalized_label = _normalize(label)
        exact = normalized_label == normalized_name or _normalize(canonical_name) == normalized_name
        return ResolutionCandidate(
            target_type=EntityType.PLACE,
            target_id=place_id,
            target_name=canonical_name,
            confidence=1.0 if exact else _similarity(normalized_name, normalized_label),
            exact=exact,
        )

    def _score_asset_candidate(
        self,
        asset_id: str,
        canonical_name: str,
        normalized_name: str,
        alias: str | None = None,
    ) -> ResolutionCandidate:
        label = alias or canonical_name
        normalized_label = _normalize(label)
        exact = normalized_label == normalized_name or _normalize(canonical_name) == normalized_name
        return ResolutionCandidate(
            target_type=EntityType.ASSET,
            target_id=asset_id,
            target_name=canonical_name,
            confidence=1.0 if exact else _similarity(normalized_name, normalized_label),
            exact=exact,
        )

    def _persist_resolution(
        self,
        *,
        task_id: str | None,
        selected: ResolutionCandidate | None = None,
        resolution_mode: ResolutionMode | None,
        resolution_confidence: float | None,
    ) -> None:
        if task_id is None:
            return
        task = self.repository.get_task(task_id)
        if task is None:
            return
        self.repository.update_task_status(
            task_id,
            status=task.status,
            resolved_target_type=selected.target_type if selected else None,
            resolved_target_id=selected.target_id if selected else None,
            resolution_mode=resolution_mode,
            resolution_confidence=resolution_confidence,
        )

    def _ranked_candidate(self, candidate: ResolutionCandidate) -> RankedTargetCandidate:
        return RankedTargetCandidate(
            target_type=candidate.target_type,
            target_id=candidate.target_id,
            target_name=candidate.target_name,
            confidence=candidate.confidence,
        )

    def _require_spot_adapter(self) -> SpotAdapter | None:
        return self.spot_adapter

    def _require_perception_adapter(self) -> PerceptionAdapter | None:
        return self.perception_adapter

    def _store_capture_observation(
        self,
        task_id: str,
        capture: Any,
    ) -> Observation:
        observation = Observation(
            observation_id=capture.observation_id,
            task_id=task_id,
            place_id=capture.place_id,
            observation_kind=capture.capture_kind,
            source="perception_adapter",
            artifact_uri=capture.artifact_uri,
            summary=capture.summary,
            structured_data_json=capture.structured_data_json,
            confidence=capture.confidence,
        )
        return self.repository.create_observation(observation)

    def _store_condition_result(
        self,
        task_id: str,
        verification: Any,
    ) -> ConditionResult:
        result = ConditionResult(
            task_id=task_id,
            target_type=verification.target_type,
            target_id=verification.target_id,
            condition_id=verification.condition_id,
            result=verification.result,
            confidence=verification.confidence,
            evidence_ids_json=list(verification.evidence_ids),
            rationale=verification.rationale,
        )
        return self.repository.create_condition_result(result)

    def _capture_outputs(self, observation: Observation, capture: Any) -> dict[str, Any]:
        return {
            "observation_id": observation.observation_id,
            "artifact_uri": observation.artifact_uri,
            "summary": observation.summary,
            "confidence": observation.confidence,
            "place_id": observation.place_id,
            "capture_kind": observation.observation_kind,
            "capture_profile": capture.capture_profile,
            "outcome_code": capture.outcome_code.value,
            "structured_data_json": observation.structured_data_json,
        }

    def _condition_result_payload(self, verification: Any) -> dict[str, Any]:
        return {
            "target_type": verification.target_type.value,
            "target_id": verification.target_id,
            "condition_id": verification.condition_id,
            "result": verification.result.value,
            "confidence": verification.confidence,
            "rationale": verification.rationale,
            "evidence_ids": list(verification.evidence_ids),
            "outcome_code": verification.outcome_code.value,
            "structured_data_json": verification.structured_data_json,
        }

    def _navigation_outputs(self, outcome: Any) -> dict[str, Any]:
        return {
            "target_place_id": outcome.target_place_id,
            "route_policy": outcome.route_policy,
            "navigation_surface": (
                outcome.navigation_surface.value if outcome.navigation_surface else None
            ),
            "confidence": outcome.confidence,
            "message": outcome.message,
            "recommended_action": outcome.recommended_action,
            "stop_state": outcome.stop_state.value,
            "relocalization_required": outcome.relocalization_required,
            "outcome_code": outcome.outcome_code.value,
        }

    def _relocalization_outputs(self, outcome: Any) -> dict[str, Any]:
        return {
            "strategy": outcome.strategy,
            "place_id": outcome.place_id,
            "confidence": outcome.confidence,
            "message": outcome.message,
            "recommended_action": outcome.recommended_action,
            "stop_state": outcome.stop_state.value,
            "outcome_code": outcome.outcome_code.value,
        }

    def _run_side_effect_tool(
        self,
        *,
        tool_name: str,
        request: Any,
        task_id: str | None,
        operation: StepOperation | None,
        precondition: PreconditionCheck | None,
        recovery_operation: StepOperation | None = None,
        success_data: Any,
    ) -> HandlerResult:
        if self.runner is None:
            return policy_rejection_error(
                code="runner_required",
                message=f"{tool_name} requires a configured supervisor runner.",
                details={"tool_name": tool_name},
            )
        if task_id is None:
            return policy_rejection_error(
                code="task_id_required",
                message=f"{tool_name} requires a task_id for supervisor execution.",
                details={"tool_name": tool_name},
            )
        if operation is None:
            return policy_rejection_error(
                code="operation_required",
                message=f"{tool_name} requires an operation callback for supervisor execution.",
                details={"tool_name": tool_name},
            )

        task_run = self.runner.run_task(
            task_id,
            [
                SupervisorStep(
                    tool_name=tool_name,
                    operation=operation,
                    precondition=precondition,
                    timeout_s=getattr(request, "timeout_s", None),
                    recovery_operation=recovery_operation,
                )
            ],
        )
        latest_step = task_run.steps[-1] if task_run.steps else None
        payload = latest_step.outputs_json if latest_step and latest_step.outputs_json else None
        if success_data is not None:
            payload = success_data
        message = payload.get("message") if isinstance(payload, dict) else None

        if task_run.final_status == TaskStatus.COMPLETED:
            return success_response(
                outcome_code=latest_step.error_code
                and OutcomeCode.TASK_COMPLETED
                or (task_run.task.outcome_code or OutcomeCode.TASK_COMPLETED),
                data=payload,
            )
        if task_run.final_status == TaskStatus.BLOCKED:
            return blocked_response(
                outcome_code=task_run.task.outcome_code or OutcomeCode.TASK_BLOCKED,
                message=task_run.task.result_summary or message or f"{tool_name} was blocked.",
                data=payload,
            )
        if task_run.final_status == TaskStatus.INCONCLUSIVE:
            return inconclusive_response(
                outcome_code=task_run.task.outcome_code or OutcomeCode.TASK_INCONCLUSIVE,
                message=task_run.task.result_summary or message or f"{tool_name} was inconclusive.",
                data=payload,
            )
        return failed_response(
            outcome_code=task_run.task.outcome_code or OutcomeCode.TASK_FAILED,
            message=task_run.task.result_summary or message or f"{tool_name} failed.",
            data=payload,
            retryable=False,
        )


def _normalize(value: str) -> str:
    return " ".join(value.lower().split())


def _similarity(left: str, right: str) -> float:
    return SequenceMatcher(None, left, right).ratio()


__all__ = ["HandlerResult", "ResolutionCandidate", "ToolHandlerService"]
