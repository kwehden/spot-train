from __future__ import annotations

from spot_train.memory.repository import WorldRepository
from spot_train.memory.schema import create_schema
from spot_train.models import (
    ConditionResult,
    ConditionVerdict,
    EntityType,
    FamiliarityFactors,
    ModelSource,
    Observation,
    OperatorEvent,
    OperatorEventType,
    OutcomeCode,
    ResolutionMode,
    StepState,
    Task,
    TaskStatus,
    TaskStep,
)
from spot_train.profiles.loader import load_default_profiles


def make_repository() -> WorldRepository:
    repository = WorldRepository.connect(initialize=False)
    create_schema(repository.connection)
    return repository


def test_repository_round_trip_for_world_and_task_history() -> None:
    repository = make_repository()

    seeded = repository.seed_minimal_lab_world()
    places = seeded["places"]
    assets = seeded["assets"]
    approval_profile, inspection_profile = load_default_profiles()
    repository.create_approval_profile(approval_profile)
    repository.create_inspection_profile(inspection_profile)

    task = repository.create_task(
        Task(
            instruction="check the optics bench",
            inspection_profile_id=inspection_profile.profile_id,
        )
    )
    updated_task = repository.update_task_status(
        task.task_id,
        status=TaskStatus.READY,
        outcome_code=OutcomeCode.RESOLVED_EXACT,
        resolved_target_type=EntityType.PLACE,
        resolved_target_id=places[0].place_id,
        resolution_mode=ResolutionMode.EXACT,
        resolution_confidence=0.99,
    )

    first_step = repository.append_task_step(
        TaskStep(
            task_id=task.task_id,
            sequence_no=1,
            tool_name="resolve_target",
            step_state=StepState.SUCCEEDED,
            inputs_json={"name": "optics bench"},
            outputs_json={"place_id": places[0].place_id},
        )
    )
    second_step = repository.append_task_step(
        TaskStep(
            task_id=task.task_id,
            sequence_no=1,
            tool_name="inspect_place",
            step_state=StepState.RUNNING,
            inputs_json={"place_id": places[0].place_id},
        )
    )

    observation = repository.create_observation(
        Observation(
            task_id=task.task_id,
            place_id=places[0].place_id,
            asset_id=assets[1].asset_id,
            observation_kind="overview_image",
            source="fake_perception",
            artifact_uri="data/artifacts/task/overview.jpg",
            summary="Bench area appears clear.",
            structured_data_json={"detections": []},
            confidence=0.92,
        )
    )
    condition_result = repository.create_condition_result(
        ConditionResult(
            task_id=task.task_id,
            target_type=EntityType.PLACE,
            target_id=places[0].place_id,
            condition_id="area_clear",
            result=ConditionVerdict.TRUE,
            confidence=0.88,
            evidence_ids_json=[observation.observation_id],
            rationale="No obstructions detected in the captured overview image.",
        )
    )
    familiarity = repository.upsert_familiarity_factors(
        FamiliarityFactors(
            place_id=places[0].place_id,
            visit_count=3,
            successful_localizations=3,
            failed_localizations=0,
            observation_freshness_s=300,
            alias_resolution_confidence=0.95,
            view_coverage_score=0.8,
        )
    )
    event = repository.create_operator_event(
        OperatorEvent(
            task_id=task.task_id,
            event_type=OperatorEventType.APPROVAL_GRANTED,
            source=ModelSource.TERMINAL,
            details_json={"approval_profile_id": approval_profile.approval_profile_id},
        )
    )

    assert repository.get_place(places[0].place_id).canonical_name == "Optics Bench"
    assert repository.get_place_by_alias("bench alpha").place_id == places[0].place_id
    assert len(repository.list_place_aliases(places[0].place_id)) == 2
    assert repository.get_asset_by_alias("spot dock").asset_id == assets[0].asset_id
    assert len(repository.list_assets(place_id=places[0].place_id)) == 1
    assert repository.get_task(task.task_id).status == TaskStatus.READY
    assert updated_task.resolution_confidence == 0.99
    assert [step.sequence_no for step in repository.list_task_steps(task.task_id)] == [1, 2]
    assert first_step.sequence_no == 1
    assert second_step.sequence_no == 2
    assert (
        repository.list_observations(task.task_id)[0].observation_id == observation.observation_id
    )
    assert (
        repository.list_condition_results(task.task_id)[0].condition_result_id
        == condition_result.condition_result_id
    )
    assert (
        repository.get_familiarity_factors(places[0].place_id).visit_count
        == familiarity.visit_count
    )
    assert repository.get_derived_familiarity(places[0].place_id).band in {"medium", "high"}
    assert (
        repository.list_operator_events(task_id=task.task_id)[0].operator_event_id
        == event.operator_event_id
    )
    assert (
        repository.get_inspection_profile(inspection_profile.profile_id).name == "lab_readiness_v1"
    )
    assert (
        repository.get_approval_profile(approval_profile.approval_profile_id).name
        == "default_dry_run"
    )

    repository.close()
