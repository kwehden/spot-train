from __future__ import annotations

from spot_train.adapters.perception import (
    CapturedEvidence,
    ConditionAnalysisResult,
    FakePerceptionAdapter,
)
from spot_train.adapters.spot import (
    FakeSpotAdapter,
    FakeSpotNavigationMode,
    FakeSpotRelocalizationMode,
)
from spot_train.memory.repository import WorldRepository
from spot_train.models import OutcomeCode, ResolutionMode, Task
from spot_train.profiles.loader import load_default_profiles
from spot_train.supervisor.policies import RetryPolicy
from spot_train.supervisor.runner import StepExecutionResult, SupervisorRunner
from spot_train.tools.contracts import (
    ToolBlockedResponse,
    ToolErrorCategory,
    ToolErrorEnvelope,
    ToolFailedResponse,
    ToolSuccessResponse,
)
from spot_train.tools.handlers import ToolHandlerService


def make_repository() -> WorldRepository:
    repository = WorldRepository.connect(initialize=True)
    repository.seed_minimal_lab_world()
    return repository


def make_repository_with_profiles() -> WorldRepository:
    repository = make_repository()
    approval_profile, inspection_profile = load_default_profiles()
    repository.create_approval_profile(approval_profile)
    repository.create_inspection_profile(inspection_profile)
    return repository


def test_resolve_target_exact_alias_match() -> None:
    repository = make_repository()
    service = ToolHandlerService(repository)

    response = service.resolve_target({"name": "bench alpha"})

    assert isinstance(response, ToolSuccessResponse)
    assert response.outcome_code.value == "resolved_exact"
    assert response.data["selected_target_name"] == "Optics Bench"
    assert response.data["resolution_mode"] == ResolutionMode.EXACT.value
    repository.close()


def test_resolve_target_best_effort_above_threshold() -> None:
    repository = make_repository()
    service = ToolHandlerService(repository)

    response = service.resolve_target(
        {
            "name": "bench alph",
            "target_type": "place",
            "min_confidence": 0.7,
        }
    )

    assert isinstance(response, ToolSuccessResponse)
    assert response.outcome_code.value == "resolved_best_effort"
    assert response.data["selected_target_name"] == "Optics Bench"
    assert response.confidence is not None
    assert response.confidence >= 0.7
    repository.close()


def test_resolve_target_blocks_low_confidence_with_ranked_candidates() -> None:
    repository = make_repository()
    service = ToolHandlerService(repository)

    response = service.resolve_target(
        {
            "name": "bench alph",
            "target_type": "place",
            "min_confidence": 0.99,
        }
    )

    assert isinstance(response, ToolBlockedResponse)
    assert response.outcome_code.value == "ambiguous_low_confidence"
    assert response.data["ranked_candidates"]
    assert response.details["ranked_candidates"][0]["target_name"] == "Optics Bench"
    repository.close()


def test_resolve_target_persists_task_resolution_fields() -> None:
    repository = make_repository()
    task = repository.create_task(Task(instruction="check optics bench"))
    service = ToolHandlerService(repository)

    response = service.resolve_target({"name": "optics bench"}, task_id=task.task_id)

    stored_task = repository.get_task(task.task_id)
    assert isinstance(response, ToolSuccessResponse)
    assert stored_task is not None
    assert stored_task.resolved_target_id == "plc_optics_bench"
    assert stored_task.resolution_mode == ResolutionMode.EXACT
    assert stored_task.resolution_confidence == 1.0
    repository.close()


def test_handler_returns_schema_validation_rejection_envelope() -> None:
    repository = make_repository()
    service = ToolHandlerService(repository)

    response = service.resolve_target({"name": "", "min_confidence": 1.5})

    assert isinstance(response, ToolErrorEnvelope)
    assert response.error.category == ToolErrorCategory.SCHEMA_VALIDATION
    assert "name" in response.error.field_errors
    repository.close()


def test_side_effect_handler_returns_policy_rejection_without_runner() -> None:
    repository = make_repository()
    task = repository.create_task(Task(instruction="go to optics bench"))
    service = ToolHandlerService(repository)

    response = service.navigate_to_place(
        {"place_id": "plc_optics_bench"},
        task_id=task.task_id,
    )

    assert isinstance(response, ToolErrorEnvelope)
    assert response.error.category == ToolErrorCategory.POLICY_ENFORCEMENT
    assert response.error.code == "runner_required"
    repository.close()


def test_side_effect_handler_delegates_through_runner_with_fake_operation() -> None:
    repository = make_repository()
    task = repository.create_task(Task(instruction="go to optics bench"))
    runner = SupervisorRunner(repository)
    service = ToolHandlerService(repository, runner=runner)

    response = service.navigate_to_place(
        {"place_id": "plc_optics_bench"},
        task_id=task.task_id,
        operation=lambda _context: StepExecutionResult.success(),
    )

    assert isinstance(response, ToolSuccessResponse)
    stored_task = repository.get_task(task.task_id)
    stored_steps = repository.list_task_steps(task.task_id)
    assert stored_task is not None
    assert stored_task.status.value == "completed"
    assert [step.tool_name for step in stored_steps] == ["navigate_to_place"]
    repository.close()


def test_navigation_handler_uses_fake_spot_adapter_by_default() -> None:
    repository = make_repository()
    task = repository.create_task(Task(instruction="go to optics bench"))
    runner = SupervisorRunner(repository)
    service = ToolHandlerService(
        repository,
        runner=runner,
        spot_adapter=FakeSpotAdapter(),
    )

    response = service.navigate_to_place({"place_id": "plc_optics_bench"}, task_id=task.task_id)

    stored_task = repository.get_task(task.task_id)
    stored_steps = repository.list_task_steps(task.task_id)

    assert isinstance(response, ToolSuccessResponse)
    assert response.data["target_place_id"] == "plc_optics_bench"
    assert response.data["outcome_code"] == "navigation_succeeded"
    assert stored_task is not None
    assert stored_task.status.value == "completed"
    assert stored_steps[0].tool_name == "navigate_to_place"
    assert stored_steps[0].outputs_json["navigation_surface"] == "waypoint"
    repository.close()


def test_navigation_handler_relocalizes_then_retries_with_fake_spot_adapter() -> None:
    repository = make_repository()
    task = repository.create_task(Task(instruction="go to optics bench"))
    runner = SupervisorRunner(repository, retry_policy=RetryPolicy(default_limit=1))
    spot_adapter = FakeSpotAdapter(
        default_navigation_mode=FakeSpotNavigationMode.RELOCALIZATION_NEEDED
    )
    spot_adapter.set_relocalization_mode(
        "plc_optics_bench",
        FakeSpotRelocalizationMode.SUCCESS,
    )
    service = ToolHandlerService(repository, runner=runner, spot_adapter=spot_adapter)

    response = service.navigate_to_place({"place_id": "plc_optics_bench"}, task_id=task.task_id)

    stored_task = repository.get_task(task.task_id)
    stored_steps = repository.list_task_steps(task.task_id)

    assert isinstance(response, ToolFailedResponse)
    assert response.outcome_code.value == "relocalization_required"
    assert stored_task is not None
    assert stored_task.status.value == "failed"
    assert [step.tool_name for step in stored_steps] == [
        "navigate_to_place",
        "relocalize",
        "navigate_to_place",
    ]
    assert stored_steps[1].outputs_json["outcome_code"] == "relocalization_succeeded"
    repository.close()


def test_capture_evidence_uses_fake_perception_adapter_and_persists_observation() -> None:
    repository = make_repository()
    task = repository.create_task(Task(instruction="capture optics bench evidence"))
    runner = SupervisorRunner(repository)
    perception = FakePerceptionAdapter()
    perception.register_capture_fixture(
        {
            "task_id": task.task_id,
            "place_id": "plc_optics_bench",
            "capture_kind": "overview_image",
            "capture_profile": None,
        },
        CapturedEvidence(
            observation_id="obs_capture_001",
            task_id=task.task_id,
            place_id="plc_optics_bench",
            capture_kind="overview_image",
            capture_profile=None,
            artifact_uri="fake://perception/obs_capture_001/overview_image.json",
            summary="Captured a clean overview image.",
            confidence=0.91,
            outcome_code=OutcomeCode.OBSERVATION_CAPTURED,
            structured_data_json={"quality": "clean"},
        ),
    )
    service = ToolHandlerService(repository, runner=runner, perception_adapter=perception)

    response = service.capture_evidence(
        {"place_id": "plc_optics_bench", "capture_kind": "overview_image"},
        task_id=task.task_id,
    )

    observations = repository.list_observations(task.task_id)

    assert isinstance(response, ToolSuccessResponse)
    assert response.data["observation_id"] == "obs_capture_001"
    assert response.data["outcome_code"] == "observation_captured"
    assert len(observations) == 1
    assert observations[0].artifact_uri == "fake://perception/obs_capture_001/overview_image.json"
    repository.close()


def test_inspect_place_uses_fake_perception_adapter_and_persists_results() -> None:
    repository = make_repository_with_profiles()
    approval_profile, inspection_profile = load_default_profiles()
    task = repository.create_task(
        Task(
            instruction="inspect optics bench",
            inspection_profile_id=inspection_profile.profile_id,
        )
    )
    runner = SupervisorRunner(repository)
    perception = FakePerceptionAdapter()
    perception.register_capture_fixture(
        {
            "task_id": task.task_id,
            "place_id": "plc_optics_bench",
            "capture_kind": "overview_image",
            "capture_profile": None,
        },
        CapturedEvidence(
            observation_id="obs_inspect_001",
            task_id=task.task_id,
            place_id="plc_optics_bench",
            capture_kind="overview_image",
            capture_profile=None,
            artifact_uri="fake://perception/obs_inspect_001/overview_image.json",
            summary="Inspection overview captured.",
            confidence=0.96,
            outcome_code=OutcomeCode.OBSERVATION_CAPTURED,
            structured_data_json={"quality": "sharp"},
        ),
    )
    perception.register_condition_fixture(
        {
            "task_id": task.task_id,
            "target_type": "place",
            "target_id": "plc_optics_bench",
            "condition_id": "area_clear",
            "evidence_ids": ["obs_inspect_001"],
        },
        ConditionAnalysisResult(
            task_id=task.task_id,
            target_type="place",
            target_id="plc_optics_bench",
            condition_id="area_clear",
            result="true",
            confidence=0.94,
            rationale="The bench area is clear in the captured evidence.",
            evidence_ids=["obs_inspect_001"],
            outcome_code=OutcomeCode.INSPECTION_COMPLETED,
            structured_data_json={"signal": "clear"},
        ),
    )
    service = ToolHandlerService(repository, runner=runner, perception_adapter=perception)

    response = service.inspect_place(
        {
            "place_id": "plc_optics_bench",
            "inspection_profile_id": inspection_profile.profile_id,
        },
        task_id=task.task_id,
    )

    observations = repository.list_observations(task.task_id)
    condition_results = repository.list_condition_results(task.task_id)
    verify_response = service.verify_condition(
        {
            "target_type": "place",
            "target_id": "plc_optics_bench",
            "condition_id": "area_clear",
            "evidence_ids": ["obs_inspect_001"],
        },
        task_id=task.task_id,
    )

    assert isinstance(response, ToolSuccessResponse)
    assert response.data["observation_ids"] == ["obs_inspect_001"]
    assert response.data["condition_results"][0]["result"] == "true"
    assert len(observations) == 1
    assert len(condition_results) == 1
    assert condition_results[0].result.value == "true"
    assert isinstance(verify_response, ToolSuccessResponse)
    assert verify_response.data["result"] == "true"
    assert approval_profile.requires_navigation_approval is True
    repository.close()
