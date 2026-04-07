"""Spot adapter boundaries and deterministic fake implementation."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol

from spot_train.models import OutcomeCode

JsonDict = dict[str, Any]


class SpotNavigationSurface(str, Enum):
    """Spot-compatible navigation abstractions."""

    WAYPOINT = "waypoint"
    MISSION = "mission"
    ROUTE = "route"


class SpotActionStatus(str, Enum):
    """High-level adapter execution states."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    RELOCALIZATION_NEEDED = "relocalization_needed"
    CANCELLED = "cancelled"


class SpotStopState(str, Enum):
    """Operator stop-control state exposed by the adapter boundary."""

    CLEAR = "clear"
    STOP_REQUESTED = "stop_requested"


class FakeSpotNavigationMode(str, Enum):
    """Deterministic fake-navigation outcomes."""

    SUCCESS = "success"
    FAILURE = "failure"
    RELOCALIZATION_NEEDED = "relocalization_needed"


class FakeSpotRelocalizationMode(str, Enum):
    """Deterministic fake-relocalization outcomes."""

    SUCCESS = "success"
    FAILURE = "failure"


@dataclass(frozen=True, slots=True)
class SpotNavigationIntent:
    """High-level navigation request accepted by the adapter."""

    place_id: str
    route_policy: str = "default"
    approval_profile_id: str | None = None
    timeout_s: int | None = None


@dataclass(frozen=True, slots=True)
class SpotNavigationBinding:
    """Spot-compatible mapping for a place navigation intent."""

    place_id: str
    surface: SpotNavigationSurface = SpotNavigationSurface.WAYPOINT
    waypoint_id: str | None = None
    mission_id: str | None = None
    route_id: str | None = None
    anchor_hint: str | None = None
    relocalization_hint: JsonDict = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SpotRelocalizeIntent:
    """Request for localization recovery."""

    place_id: str | None = None
    strategy: str = "nearest_hint"


@dataclass(frozen=True, slots=True)
class SpotNavigationOutcome:
    """High-level navigation outcome that hides robot-internal details."""

    status: SpotActionStatus
    outcome_code: OutcomeCode
    message: str
    target_place_id: str
    route_policy: str
    stop_state: SpotStopState = SpotStopState.CLEAR
    confidence: float | None = None
    relocalization_required: bool = False
    recommended_action: str | None = None
    navigation_surface: SpotNavigationSurface | None = None


@dataclass(frozen=True, slots=True)
class SpotRelocalizationOutcome:
    """High-level relocalization outcome."""

    status: SpotActionStatus
    outcome_code: OutcomeCode
    message: str
    strategy: str
    place_id: str | None = None
    stop_state: SpotStopState = SpotStopState.CLEAR
    confidence: float | None = None
    recommended_action: str | None = None


@dataclass(frozen=True, slots=True)
class SpotStopOutcome:
    """Outcome of an out-of-band stop-control request."""

    stop_state: SpotStopState
    acknowledged: bool
    message: str
    reason: str | None = None


class SpotNavigationMapper(Protocol):
    """Contract for mapping a high-level intent to a Spot-native target."""

    def map_navigation_intent(self, intent: SpotNavigationIntent) -> SpotNavigationBinding:
        """Return a Spot-compatible target mapping for an intent."""


class SpotAdapter(SpotNavigationMapper, Protocol):
    """Stable adapter boundary for movement and stop-control integration."""

    def navigate(self, intent: SpotNavigationIntent) -> SpotNavigationOutcome:
        """Execute a navigation intent and return a high-level outcome."""

    def relocalize(self, intent: SpotRelocalizeIntent) -> SpotRelocalizationOutcome:
        """Execute a localization recovery flow and return a high-level outcome."""

    def request_stop(self, *, reason: str | None = None) -> SpotStopOutcome:
        """Request a stop through the adapter boundary."""

    def clear_stop(self) -> SpotStopOutcome:
        """Clear the stop state once the operator releases control."""

    @property
    def stop_state(self) -> SpotStopState:
        """Current stop-control state exposed for orchestration and UI."""


@dataclass(slots=True)
class FakeSpotAdapter:
    """Deterministic adapter used for local development and tests."""

    default_navigation_mode: FakeSpotNavigationMode = FakeSpotNavigationMode.SUCCESS
    default_relocalization_mode: FakeSpotRelocalizationMode = (
        FakeSpotRelocalizationMode.SUCCESS
    )
    default_navigation_surface: SpotNavigationSurface = SpotNavigationSurface.WAYPOINT
    navigation_bindings: dict[str, SpotNavigationBinding] = field(default_factory=dict)
    navigation_modes_by_place_id: dict[str, FakeSpotNavigationMode] = field(
        default_factory=dict
    )
    relocalization_modes_by_place_id: dict[str, FakeSpotRelocalizationMode] = field(
        default_factory=dict
    )
    _stop_state: SpotStopState = SpotStopState.CLEAR
    _last_stop_reason: str | None = None

    def register_navigation_binding(self, binding: SpotNavigationBinding) -> None:
        """Register a deterministic binding for a place."""

        self.navigation_bindings[binding.place_id] = binding

    def set_navigation_mode(
        self,
        place_id: str,
        mode: FakeSpotNavigationMode,
    ) -> None:
        """Override the navigation mode for a particular target."""

        self.navigation_modes_by_place_id[place_id] = mode

    def set_relocalization_mode(
        self,
        place_id: str,
        mode: FakeSpotRelocalizationMode,
    ) -> None:
        """Override the relocalization mode for a particular target."""

        self.relocalization_modes_by_place_id[place_id] = mode

    @property
    def stop_state(self) -> SpotStopState:
        return self._stop_state

    @property
    def last_stop_reason(self) -> str | None:
        return self._last_stop_reason

    def map_navigation_intent(self, intent: SpotNavigationIntent) -> SpotNavigationBinding:
        binding = self.navigation_bindings.get(intent.place_id)
        if binding is not None:
            return binding
        return SpotNavigationBinding(
            place_id=intent.place_id,
            surface=self.default_navigation_surface,
            waypoint_id=(
                f"{intent.place_id}:waypoint"
                if self.default_navigation_surface == SpotNavigationSurface.WAYPOINT
                else None
            ),
            mission_id=(
                f"{intent.place_id}:mission"
                if self.default_navigation_surface == SpotNavigationSurface.MISSION
                else None
            ),
            route_id=(
                f"{intent.place_id}:route"
                if self.default_navigation_surface == SpotNavigationSurface.ROUTE
                else None
            ),
            relocalization_hint={"strategy": "nearest_hint"},
        )

    def navigate(self, intent: SpotNavigationIntent) -> SpotNavigationOutcome:
        binding = self.map_navigation_intent(intent)
        if self.stop_state == SpotStopState.STOP_REQUESTED:
            return SpotNavigationOutcome(
                status=SpotActionStatus.CANCELLED,
                outcome_code=OutcomeCode.TASK_CANCELLED,
                message="Navigation aborted because stop control is active.",
                target_place_id=intent.place_id,
                route_policy=intent.route_policy,
                stop_state=self.stop_state,
                recommended_action="await_operator_clear",
                navigation_surface=binding.surface,
            )

        mode = self.navigation_modes_for(intent.place_id)
        if mode == FakeSpotNavigationMode.SUCCESS:
            return SpotNavigationOutcome(
                status=SpotActionStatus.SUCCEEDED,
                outcome_code=OutcomeCode.NAVIGATION_SUCCEEDED,
                message=f"Navigation to {intent.place_id} completed successfully.",
                target_place_id=intent.place_id,
                route_policy=intent.route_policy,
                navigation_surface=binding.surface,
                confidence=1.0,
                recommended_action="continue",
            )
        if mode == FakeSpotNavigationMode.RELOCALIZATION_NEEDED:
            return SpotNavigationOutcome(
                status=SpotActionStatus.RELOCALIZATION_NEEDED,
                outcome_code=OutcomeCode.RELOCALIZATION_REQUIRED,
                message="Localization needs to be refreshed before retrying navigation.",
                target_place_id=intent.place_id,
                route_policy=intent.route_policy,
                navigation_surface=binding.surface,
                confidence=0.55,
                relocalization_required=True,
                recommended_action="relocalize_then_retry",
            )
        return SpotNavigationOutcome(
            status=SpotActionStatus.FAILED,
            outcome_code=OutcomeCode.NAVIGATION_FAILED,
            message="Navigation could not be completed.",
            target_place_id=intent.place_id,
            route_policy=intent.route_policy,
            navigation_surface=binding.surface,
            confidence=0.25,
            recommended_action="abort_or_retry",
        )

    def relocalize(self, intent: SpotRelocalizeIntent) -> SpotRelocalizationOutcome:
        if self.stop_state == SpotStopState.STOP_REQUESTED:
            return SpotRelocalizationOutcome(
                status=SpotActionStatus.CANCELLED,
                outcome_code=OutcomeCode.TASK_CANCELLED,
                message="Relocalization aborted because stop control is active.",
                strategy=intent.strategy,
                place_id=intent.place_id,
                stop_state=self.stop_state,
                recommended_action="await_operator_clear",
            )

        mode = self.relocalization_modes_for(intent.place_id)
        if mode == FakeSpotRelocalizationMode.SUCCESS:
            return SpotRelocalizationOutcome(
                status=SpotActionStatus.SUCCEEDED,
                outcome_code=OutcomeCode.RELOCALIZATION_SUCCEEDED,
                message="Relocalization completed successfully.",
                strategy=intent.strategy,
                place_id=intent.place_id,
                confidence=0.93,
                recommended_action="retry_navigation",
            )
        return SpotRelocalizationOutcome(
            status=SpotActionStatus.FAILED,
            outcome_code=OutcomeCode.RELOCALIZATION_FAILED,
            message="Relocalization failed.",
            strategy=intent.strategy,
            place_id=intent.place_id,
            confidence=0.2,
            recommended_action="request_operator_assistance",
        )

    def request_stop(self, *, reason: str | None = None) -> SpotStopOutcome:
        self._stop_state = SpotStopState.STOP_REQUESTED
        self._last_stop_reason = reason
        return SpotStopOutcome(
            stop_state=self._stop_state,
            acknowledged=True,
            message="Stop request acknowledged.",
            reason=reason,
        )

    def clear_stop(self) -> SpotStopOutcome:
        self._stop_state = SpotStopState.CLEAR
        self._last_stop_reason = None
        return SpotStopOutcome(
            stop_state=self._stop_state,
            acknowledged=True,
            message="Stop state cleared.",
        )

    def navigation_modes_for(self, place_id: str) -> FakeSpotNavigationMode:
        return self.navigation_modes_by_place_id.get(place_id, self.default_navigation_mode)

    def relocalization_modes_for(self, place_id: str | None) -> FakeSpotRelocalizationMode:
        if place_id is None:
            return self.default_relocalization_mode
        return self.relocalization_modes_by_place_id.get(
            place_id,
            self.default_relocalization_mode,
        )


class RealSpotAdapter:
    """Future SDK-backed Spot adapter boundary.

    This class is intentionally stubbed until the dry-run validation phase.
    """

    def map_navigation_intent(self, intent: SpotNavigationIntent) -> SpotNavigationBinding:
        raise NotImplementedError("Real Spot adapter is not implemented yet.")

    def navigate(self, intent: SpotNavigationIntent) -> SpotNavigationOutcome:
        raise NotImplementedError("Real Spot adapter is not implemented yet.")

    def relocalize(self, intent: SpotRelocalizeIntent) -> SpotRelocalizationOutcome:
        raise NotImplementedError("Real Spot adapter is not implemented yet.")

    def request_stop(self, *, reason: str | None = None) -> SpotStopOutcome:
        raise NotImplementedError("Real Spot adapter is not implemented yet.")

    def clear_stop(self) -> SpotStopOutcome:
        raise NotImplementedError("Real Spot adapter is not implemented yet.")

    @property
    def stop_state(self) -> SpotStopState:
        raise NotImplementedError("Real Spot adapter is not implemented yet.")


__all__ = [
    "FakeSpotAdapter",
    "FakeSpotNavigationMode",
    "FakeSpotRelocalizationMode",
    "RealSpotAdapter",
    "SpotActionStatus",
    "SpotAdapter",
    "SpotNavigationBinding",
    "SpotNavigationIntent",
    "SpotNavigationMapper",
    "SpotNavigationOutcome",
    "SpotNavigationSurface",
    "SpotRelocalizationOutcome",
    "SpotRelocalizeIntent",
    "SpotStopOutcome",
    "SpotStopState",
]
