from __future__ import annotations

from spot_train.adapters.spot import (
    FakeSpotAdapter,
    FakeSpotNavigationMode,
    FakeSpotRelocalizationMode,
    SpotActionStatus,
    SpotNavigationBinding,
    SpotNavigationIntent,
    SpotNavigationSurface,
    SpotRelocalizeIntent,
    SpotStopState,
)
from spot_train.models import OutcomeCode


def test_fake_spot_adapter_preserves_navigation_mapping_contract() -> None:
    adapter = FakeSpotAdapter()
    binding = SpotNavigationBinding(
        place_id="plc_optics_bench",
        surface=SpotNavigationSurface.MISSION,
        mission_id="mission_optics",
        route_id="route_lab_a",
        anchor_hint="north wall",
        relocalization_hint={"preferred_surface": "mission"},
    )
    adapter.register_navigation_binding(binding)

    intent = SpotNavigationIntent(
        place_id="plc_optics_bench",
        route_policy="inspection",
        approval_profile_id="apr_default_dry_run",
        timeout_s=45,
    )

    assert adapter.map_navigation_intent(intent) == binding

    result = adapter.navigate(intent)
    assert result.status == SpotActionStatus.SUCCEEDED
    assert result.outcome_code == OutcomeCode.NAVIGATION_SUCCEEDED
    assert result.target_place_id == "plc_optics_bench"
    assert result.route_policy == "inspection"
    assert result.navigation_surface == SpotNavigationSurface.MISSION
    assert result.stop_state == SpotStopState.CLEAR
    assert result.relocalization_required is False
    assert result.recommended_action == "continue"


def test_fake_spot_adapter_supports_deterministic_navigation_failure() -> None:
    adapter = FakeSpotAdapter(default_navigation_mode=FakeSpotNavigationMode.FAILURE)

    result = adapter.navigate(
        SpotNavigationIntent(place_id="plc_charging_station", route_policy="default")
    )

    assert result.status == SpotActionStatus.FAILED
    assert result.outcome_code == OutcomeCode.NAVIGATION_FAILED
    assert result.navigation_surface == SpotNavigationSurface.WAYPOINT
    assert result.confidence == 0.25
    assert result.recommended_action == "abort_or_retry"


def test_fake_spot_adapter_supports_relocalization_needed_mode() -> None:
    adapter = FakeSpotAdapter(
        default_navigation_mode=FakeSpotNavigationMode.RELOCALIZATION_NEEDED
    )

    result = adapter.navigate(
        SpotNavigationIntent(place_id="plc_optics_bench", route_policy="default")
    )

    assert result.status == SpotActionStatus.RELOCALIZATION_NEEDED
    assert result.outcome_code == OutcomeCode.RELOCALIZATION_REQUIRED
    assert result.relocalization_required is True
    assert result.confidence == 0.55
    assert result.recommended_action == "relocalize_then_retry"


def test_fake_spot_adapter_relocalize_is_deterministic_per_target() -> None:
    adapter = FakeSpotAdapter()
    success = adapter.relocalize(SpotRelocalizeIntent(place_id="plc_optics_bench"))

    adapter.set_relocalization_mode(
        "plc_optics_bench",
        FakeSpotRelocalizationMode.FAILURE,
    )
    failure = adapter.relocalize(SpotRelocalizeIntent(place_id="plc_optics_bench"))

    assert success.status == SpotActionStatus.SUCCEEDED
    assert success.outcome_code == OutcomeCode.RELOCALIZATION_SUCCEEDED
    assert success.place_id == "plc_optics_bench"
    assert success.recommended_action == "retry_navigation"
    assert failure.status == SpotActionStatus.FAILED
    assert failure.outcome_code == OutcomeCode.RELOCALIZATION_FAILED
    assert failure.recommended_action == "request_operator_assistance"


def test_fake_spot_adapter_stop_request_interrupts_navigation() -> None:
    adapter = FakeSpotAdapter()

    stop = adapter.request_stop(reason="terminal stop requested")
    result = adapter.navigate(SpotNavigationIntent(place_id="plc_optics_bench"))
    cleared = adapter.clear_stop()

    assert stop.stop_state == SpotStopState.STOP_REQUESTED
    assert stop.acknowledged is True
    assert adapter.stop_state == SpotStopState.CLEAR
    assert adapter.last_stop_reason is None
    assert result.status == SpotActionStatus.CANCELLED
    assert result.outcome_code == OutcomeCode.TASK_CANCELLED
    assert result.stop_state == SpotStopState.STOP_REQUESTED
    assert result.recommended_action == "await_operator_clear"
    assert cleared.stop_state == SpotStopState.CLEAR
