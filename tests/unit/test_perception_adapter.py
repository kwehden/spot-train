from __future__ import annotations

import pytest

from spot_train.adapters.perception import (
    CapturedEvidence,
    CaptureEvidenceRequest,
    ConditionAnalysisResult,
    ConditionVerificationRequest,
    FakePerceptionAdapter,
    RealPerceptionAdapter,
)
from spot_train.models import ConditionVerdict, EntityType, OutcomeCode


def test_fake_perception_adapter_capture_is_repeatable() -> None:
    adapter = FakePerceptionAdapter()
    request = CaptureEvidenceRequest(
        task_id="tsk_001",
        place_id="plc_optics_bench",
        capture_kind="overview_image",
    )

    first = adapter.capture_evidence(request)
    second = adapter.capture_evidence(request)

    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert first.outcome_code == OutcomeCode.OBSERVATION_CAPTURED
    assert first.confidence == second.confidence
    assert first.observation_id == second.observation_id
    assert first.artifact_uri.startswith("fake://perception/obs_")


def test_fake_perception_adapter_capture_fixture_can_force_inconclusive() -> None:
    adapter = FakePerceptionAdapter()
    request = {
        "task_id": "tsk_002",
        "place_id": "plc_optics_bench",
        "capture_kind": "closeup_image",
    }
    adapter.register_capture_fixture(
        request,
        CapturedEvidence(
            observation_id="obs_fixture_closeup",
            task_id="tsk_002",
            place_id="plc_optics_bench",
            capture_kind="closeup_image",
            capture_profile="macro",
            artifact_uri="fake://perception/obs_fixture_closeup/closeup_image.json",
            summary="Close-up image was not sharp enough to confirm the target.",
            confidence=0.21,
            outcome_code=OutcomeCode.PERCEPTION_INCONCLUSIVE,
            structured_data_json={"reason": "blur"},
            inconclusive_reason="blur",
        ),
    )

    result = adapter.capture_evidence(request)

    assert result.outcome_code == OutcomeCode.PERCEPTION_INCONCLUSIVE
    assert result.summary.startswith("Close-up image")
    assert result.inconclusive_reason == "blur"
    assert result.confidence == 0.21


def test_fake_perception_adapter_verify_condition_is_repeatable() -> None:
    adapter = FakePerceptionAdapter()
    request = ConditionVerificationRequest(
        task_id="tsk_003",
        target_type=EntityType.PLACE,
        target_id="plc_optics_bench",
        condition_id="condition_clean_surface",
        evidence_ids=["obs_a", "obs_b"],
    )

    first = adapter.verify_condition(request)
    second = adapter.verify_condition(request)

    assert first.model_dump(mode="json") == second.model_dump(mode="json")
    assert first.result in {
        ConditionVerdict.TRUE,
        ConditionVerdict.FALSE,
        ConditionVerdict.INCONCLUSIVE,
    }
    assert 0.5 <= first.confidence <= 0.99
    assert first.evidence_ids == ["obs_a", "obs_b"]


def test_fake_perception_adapter_verify_condition_fixtures_cover_all_verdicts() -> None:
    adapter = FakePerceptionAdapter()

    true_request = {
        "task_id": "tsk_true",
        "target_type": "place",
        "target_id": "plc_optics_bench",
        "condition_id": "condition_ready",
        "evidence_ids": ["obs_true"],
    }
    false_request = {
        "task_id": "tsk_false",
        "target_type": "place",
        "target_id": "plc_optics_bench",
        "condition_id": "condition_blocked",
        "evidence_ids": ["obs_false"],
    }
    inconclusive_request = {
        "task_id": "tsk_inconclusive",
        "target_type": "place",
        "target_id": "plc_optics_bench",
        "condition_id": "condition_ambiguous",
        "evidence_ids": ["obs_unknown"],
    }

    adapter.register_condition_fixture(
        true_request,
        ConditionAnalysisResult(
            task_id="tsk_true",
            target_type=EntityType.PLACE,
            target_id="plc_optics_bench",
            condition_id="condition_ready",
            result=ConditionVerdict.TRUE,
            confidence=0.93,
            rationale="Fixture verified readiness.",
            evidence_ids=["obs_true"],
            outcome_code=OutcomeCode.INSPECTION_COMPLETED,
        ),
    )
    adapter.register_condition_fixture(
        false_request,
        {
            "task_id": "tsk_false",
            "target_type": "place",
            "target_id": "plc_optics_bench",
            "condition_id": "condition_blocked",
            "result": "false",
            "confidence": 0.61,
            "rationale": "Fixture rejected readiness.",
            "evidence_ids": ["obs_false"],
            "outcome_code": "inspection_completed",
        },
    )
    adapter.register_condition_fixture(
        inconclusive_request,
        ConditionAnalysisResult(
            task_id="tsk_inconclusive",
            target_type=EntityType.PLACE,
            target_id="plc_optics_bench",
            condition_id="condition_ambiguous",
            result=ConditionVerdict.INCONCLUSIVE,
            confidence=0.37,
            rationale="Fixture evidence was insufficient.",
            evidence_ids=["obs_unknown"],
            outcome_code=OutcomeCode.INSPECTION_INCONCLUSIVE,
        ),
    )

    true_result = adapter.verify_condition(true_request)
    false_result = adapter.verify_condition(false_request)
    inconclusive_result = adapter.verify_condition(inconclusive_request)

    assert true_result.result == ConditionVerdict.TRUE
    assert true_result.outcome_code == OutcomeCode.INSPECTION_COMPLETED
    assert false_result.result == ConditionVerdict.FALSE
    assert false_result.outcome_code == OutcomeCode.INSPECTION_COMPLETED
    assert inconclusive_result.result == ConditionVerdict.INCONCLUSIVE
    assert inconclusive_result.outcome_code == OutcomeCode.INSPECTION_INCONCLUSIVE


def test_real_perception_adapter_is_stubbed() -> None:
    adapter = RealPerceptionAdapter()

    with pytest.raises(NotImplementedError):
        adapter.capture_evidence(
            CaptureEvidenceRequest(
                place_id="plc_optics_bench",
                capture_kind="overview_image",
            )
        )

    with pytest.raises(NotImplementedError):
        adapter.verify_condition(
            ConditionVerificationRequest(
                target_type=EntityType.PLACE,
                target_id="plc_optics_bench",
                condition_id="condition_ready",
            )
        )
