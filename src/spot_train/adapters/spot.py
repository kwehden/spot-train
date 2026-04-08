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
    default_relocalization_mode: FakeSpotRelocalizationMode = FakeSpotRelocalizationMode.SUCCESS
    default_navigation_surface: SpotNavigationSurface = SpotNavigationSurface.WAYPOINT
    navigation_bindings: dict[str, SpotNavigationBinding] = field(default_factory=dict)
    navigation_modes_by_place_id: dict[str, FakeSpotNavigationMode] = field(default_factory=dict)
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
    """SDK-backed Spot adapter using the estop_control.py connection pattern.

    Expects the e-stop keepalive to be running in a separate process.
    This adapter does NOT own the e-stop endpoint — it manages a body
    lease for motion commands, sends stop commands to halt the robot,
    and uses GraphNav for navigation and localization recovery.
    """

    def __init__(self, robot: Any, *, lease_client: Any = None) -> None:
        from bosdyn.api.graph_nav import graph_nav_pb2
        from bosdyn.client.graph_nav import GraphNavClient
        from bosdyn.client.robot_command import RobotCommandBuilder, RobotCommandClient

        self._robot = robot
        self._graph_nav: Any = robot.ensure_client(GraphNavClient.default_service_name)
        self._command_client: Any = robot.ensure_client(RobotCommandClient.default_service_name)
        self._lease_client = lease_client
        self._lease_keepalive: Any | None = None
        self._feedback_status = graph_nav_pb2.NavigationFeedbackResponse.Status
        self._set_loc_request = graph_nav_pb2.SetLocalizationRequest
        self._stop_command_builder = RobotCommandBuilder.stop_command
        self._stop_state = SpotStopState.CLEAR
        self._last_stop_reason: str | None = None
        self._bindings: dict[str, SpotNavigationBinding] = {}

    # -- factory ----------------------------------------------------------

    @classmethod
    def connect(cls, config: Any | None = None) -> "RealSpotAdapter":
        """Create an adapter using the estop_control.py connection pattern."""
        import bosdyn.client
        import bosdyn.client.util
        from bosdyn.client.lease import LeaseClient

        if config is None:
            from spot_train.config import SpotConnectionConfig

            config = SpotConnectionConfig.from_env()

        import os

        os.environ.setdefault("BOSDYN_CLIENT_USERNAME", config.username)
        os.environ.setdefault("BOSDYN_CLIENT_PASSWORD", config.password)

        sdk = bosdyn.client.create_standard_sdk("spot_train")
        robot = sdk.create_robot(config.hostname)
        bosdyn.client.util.authenticate(robot)
        robot.sync_with_directory()
        robot.time_sync.wait_for_sync()

        lease_client = robot.ensure_client(LeaseClient.default_service_name)
        return cls(robot, lease_client=lease_client)

    # -- lease management -------------------------------------------------

    def acquire_lease(self) -> None:
        """Acquire the body lease and start keepalive.

        Must be called before any motion command. The keepalive thread
        automatically renews the lease until ``release_lease()`` is called.
        """
        from bosdyn.client.lease import LeaseKeepAlive

        if self._lease_keepalive is not None:
            return  # already held
        self._lease_client.take()
        self._lease_keepalive = LeaseKeepAlive(
            self._lease_client, must_acquire=True, return_at_exit=True
        )

    def release_lease(self) -> None:
        """Release the body lease and stop keepalive."""
        if self._lease_keepalive is not None:
            self._lease_keepalive.shutdown()
            self._lease_keepalive = None

    @property
    def has_lease(self) -> bool:
        return self._lease_keepalive is not None

    # -- binding registry -------------------------------------------------

    def register_navigation_binding(self, binding: SpotNavigationBinding) -> None:
        self._bindings[binding.place_id] = binding

    def map_navigation_intent(self, intent: SpotNavigationIntent) -> SpotNavigationBinding:
        binding = self._bindings.get(intent.place_id)
        if binding is not None:
            return binding
        return SpotNavigationBinding(
            place_id=intent.place_id,
            surface=SpotNavigationSurface.WAYPOINT,
        )

    # -- robot stop (sends command to halt motion) ------------------------

    def _send_stop_to_robot(self) -> None:
        """Send a stop command to the robot to halt all motion."""
        try:
            cmd = self._stop_command_builder()
            self._command_client.robot_command(cmd)
        except Exception:
            pass  # best-effort; hardware e-stop is the safety backstop

    # -- navigation -------------------------------------------------------

    def navigate(self, intent: SpotNavigationIntent) -> SpotNavigationOutcome:
        import time

        if self._stop_state == SpotStopState.STOP_REQUESTED:
            return SpotNavigationOutcome(
                status=SpotActionStatus.CANCELLED,
                outcome_code=OutcomeCode.TASK_CANCELLED,
                message="Navigation aborted — stop control is active.",
                target_place_id=intent.place_id,
                route_policy=intent.route_policy,
                stop_state=self._stop_state,
                recommended_action="await_operator_clear",
            )

        binding = self.map_navigation_intent(intent)
        waypoint_id = binding.waypoint_id
        if not waypoint_id:
            return SpotNavigationOutcome(
                status=SpotActionStatus.FAILED,
                outcome_code=OutcomeCode.NAVIGATION_FAILED,
                message=f"No waypoint_id bound for {intent.place_id}.",
                target_place_id=intent.place_id,
                route_policy=intent.route_policy,
                recommended_action="register_navigation_binding",
            )

        if not self.has_lease:
            return SpotNavigationOutcome(
                status=SpotActionStatus.FAILED,
                outcome_code=OutcomeCode.NAVIGATION_FAILED,
                message="No body lease held. Call acquire_lease() first.",
                target_place_id=intent.place_id,
                route_policy=intent.route_policy,
                recommended_action="acquire_lease",
            )

        timeout_s = intent.timeout_s or 30
        try:
            cmd_id = self._graph_nav.navigate_to(
                waypoint_id,
                cmd_duration=timeout_s,
            )
        except Exception as exc:
            return SpotNavigationOutcome(
                status=SpotActionStatus.FAILED,
                outcome_code=OutcomeCode.NAVIGATION_FAILED,
                message=f"navigate_to raised: {exc}",
                target_place_id=intent.place_id,
                route_policy=intent.route_policy,
                recommended_action="abort_or_retry",
            )

        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if self._stop_state == SpotStopState.STOP_REQUESTED:
                self._send_stop_to_robot()
                return SpotNavigationOutcome(
                    status=SpotActionStatus.CANCELLED,
                    outcome_code=OutcomeCode.TASK_CANCELLED,
                    message="Navigation interrupted — stop command sent to robot.",
                    target_place_id=intent.place_id,
                    route_policy=intent.route_policy,
                    stop_state=self._stop_state,
                    recommended_action="await_operator_clear",
                )

            feedback = self._graph_nav.navigation_feedback(cmd_id)
            status = feedback.status

            if status == self._feedback_status.Value("STATUS_REACHED_GOAL"):
                return SpotNavigationOutcome(
                    status=SpotActionStatus.SUCCEEDED,
                    outcome_code=OutcomeCode.NAVIGATION_SUCCEEDED,
                    message=f"Reached {intent.place_id}.",
                    target_place_id=intent.place_id,
                    route_policy=intent.route_policy,
                    navigation_surface=binding.surface,
                    confidence=1.0,
                    recommended_action="continue",
                )

            if status in (
                self._feedback_status.Value("STATUS_NO_LOCALIZATION"),
                self._feedback_status.Value("STATUS_LOST"),
                self._feedback_status.Value("STATUS_NOT_LOCALIZED_TO_ROUTE"),
            ):
                self._send_stop_to_robot()
                return SpotNavigationOutcome(
                    status=SpotActionStatus.RELOCALIZATION_NEEDED,
                    outcome_code=OutcomeCode.RELOCALIZATION_REQUIRED,
                    message="Robot lost localization — stop command sent.",
                    target_place_id=intent.place_id,
                    route_policy=intent.route_policy,
                    navigation_surface=binding.surface,
                    relocalization_required=True,
                    confidence=0.3,
                    recommended_action="relocalize_then_retry",
                )

            if status in (
                self._feedback_status.Value("STATUS_NO_ROUTE"),
                self._feedback_status.Value("STATUS_STUCK"),
                self._feedback_status.Value("STATUS_ROBOT_IMPAIRED"),
                self._feedback_status.Value("STATUS_CONSTRAINT_FAULT"),
                self._feedback_status.Value("STATUS_LEASE_ERROR"),
                self._feedback_status.Value("STATUS_AREA_CALLBACK_ERROR"),
            ):
                self._send_stop_to_robot()
                return SpotNavigationOutcome(
                    status=SpotActionStatus.FAILED,
                    outcome_code=OutcomeCode.NAVIGATION_FAILED,
                    message=f"Navigation failed (status {status}) — stop command sent.",
                    target_place_id=intent.place_id,
                    route_policy=intent.route_policy,
                    navigation_surface=binding.surface,
                    confidence=0.0,
                    recommended_action="abort_or_retry",
                )

            if status == self._feedback_status.Value("STATUS_COMMAND_OVERRIDDEN"):
                return SpotNavigationOutcome(
                    status=SpotActionStatus.CANCELLED,
                    outcome_code=OutcomeCode.TASK_CANCELLED,
                    message="Navigation command was overridden.",
                    target_place_id=intent.place_id,
                    route_policy=intent.route_policy,
                    recommended_action="abort_or_retry",
                )

            # STATUS_FOLLOWING_ROUTE or STATUS_UNKNOWN — keep polling
            time.sleep(0.5)

        # Timeout — stop the robot before returning
        self._send_stop_to_robot()
        return SpotNavigationOutcome(
            status=SpotActionStatus.FAILED,
            outcome_code=OutcomeCode.NAVIGATION_FAILED,
            message=f"Navigation timed out after {timeout_s}s — stop command sent.",
            target_place_id=intent.place_id,
            route_policy=intent.route_policy,
            recommended_action="abort_or_retry",
        )

    # -- relocalization ---------------------------------------------------

    def relocalize(self, intent: SpotRelocalizeIntent) -> SpotRelocalizationOutcome:
        """Attempt localization recovery using visual features.

        If a place_id is provided and has a waypoint binding, uses that
        waypoint as the initial guess. Falls back to FIDUCIAL_INIT_NO_FIDUCIAL
        so localization works on maps recorded without fiducials.
        """
        if self._stop_state == SpotStopState.STOP_REQUESTED:
            return SpotRelocalizationOutcome(
                status=SpotActionStatus.CANCELLED,
                outcome_code=OutcomeCode.TASK_CANCELLED,
                message="Relocalization aborted — stop control is active.",
                strategy=intent.strategy,
                place_id=intent.place_id,
                stop_state=self._stop_state,
                recommended_action="await_operator_clear",
            )

        try:
            from bosdyn.api.graph_nav import nav_pb2
            from bosdyn.client.frame_helpers import get_odom_tform_body
            from bosdyn.client.robot_state import RobotStateClient

            # Build initial guess from waypoint binding if available
            initial_guess = nav_pb2.Localization()
            if intent.place_id:
                binding = self._bindings.get(intent.place_id)
                if binding and binding.waypoint_id:
                    initial_guess.waypoint_id = binding.waypoint_id
                    # Identity transform: assume robot is roughly at the waypoint
                    initial_guess.waypoint_tform_body.rotation.w = 1.0

            # Get current odom pose for the ko_tform_body hint
            state_client = self._robot.ensure_client(RobotStateClient.default_service_name)
            robot_state = state_client.get_robot_state()
            odom_tform_body = get_odom_tform_body(
                robot_state.kinematic_state.transforms_snapshot
            ).to_proto()

            self._graph_nav.set_localization(
                initial_guess_localization=initial_guess,
                ko_tform_body=odom_tform_body,
                max_distance=20.0,
                max_yaw=3.14159,
                fiducial_init=self._set_loc_request.FIDUCIAL_INIT_NO_FIDUCIAL,
            )
            state = self._graph_nav.get_localization_state()
            if state.localization.waypoint_id:
                return SpotRelocalizationOutcome(
                    status=SpotActionStatus.SUCCEEDED,
                    outcome_code=OutcomeCode.RELOCALIZATION_SUCCEEDED,
                    message=f"Relocalized at waypoint {state.localization.waypoint_id}.",
                    strategy=intent.strategy,
                    place_id=intent.place_id,
                    confidence=0.9,
                    recommended_action="retry_navigation",
                )
            return SpotRelocalizationOutcome(
                status=SpotActionStatus.FAILED,
                outcome_code=OutcomeCode.RELOCALIZATION_FAILED,
                message="set_localization succeeded but no waypoint returned.",
                strategy=intent.strategy,
                place_id=intent.place_id,
                confidence=0.0,
                recommended_action="request_operator_assistance",
            )
        except Exception as exc:
            return SpotRelocalizationOutcome(
                status=SpotActionStatus.FAILED,
                outcome_code=OutcomeCode.RELOCALIZATION_FAILED,
                message=f"Relocalization error: {exc}",
                strategy=intent.strategy,
                place_id=intent.place_id,
                confidence=0.0,
                recommended_action="request_operator_assistance",
            )

    # -- stop control (sends stop command to robot) -----------------------

    def request_stop(self, *, reason: str | None = None) -> SpotStopOutcome:
        """Set the software stop flag and send a stop command to halt motion."""
        self._stop_state = SpotStopState.STOP_REQUESTED
        self._last_stop_reason = reason
        self._send_stop_to_robot()
        return SpotStopOutcome(
            stop_state=self._stop_state,
            acknowledged=True,
            message="Stop request acknowledged — stop command sent to robot.",
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

    @property
    def stop_state(self) -> SpotStopState:
        return self._stop_state


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
