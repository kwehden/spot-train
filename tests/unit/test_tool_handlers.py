from __future__ import annotations

from spot_train.memory.repository import WorldRepository
from spot_train.models import ResolutionMode, Task
from spot_train.supervisor.runner import StepExecutionResult, SupervisorRunner
from spot_train.tools.contracts import (
    ToolBlockedResponse,
    ToolErrorCategory,
    ToolErrorEnvelope,
    ToolSuccessResponse,
)
from spot_train.tools.handlers import ToolHandlerService


def make_repository() -> WorldRepository:
    repository = WorldRepository.connect(initialize=True)
    repository.seed_minimal_lab_world()
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
