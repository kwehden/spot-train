# Design

## Status

Approved for Gate 3 on 2026-04-07.

## Purpose

Define the concrete design for the MVP described in [context.md](/home/kwehden/projects/spot-train/spec/context.md) and [requirements.md](/home/kwehden/projects/spot-train/spec/requirements.md), covering:

- the data schema
- the agent-facing tool definitions
- the supervisor state machine
- the minimal first implementation plan for this repository

## Design Summary

The system is designed as:

`Strands agent -> typed tool layer -> deterministic supervisor -> Spot/perception adapters -> world memory`

with these core rules:

- the agent reasons over named entities and typed tools, not raw Spot SDK calls
- the supervisor is the only component allowed to trigger robot side effects
- world memory is split into spatial, semantic, and episodic concerns
- ambiguity defaults to best-effort resolution with confidence, but no motion occurs below a configurable confidence threshold
- approvals are profile-specific, not global
- operator stop control remains available through a separate terminal workflow
- operators can monitor execution through a Linux-compatible ridealong UI
- the orchestration path is expected to add minimal control-plane latency relative to model inference and robot execution

## Architecture

### Components

1. `Agent layer`
   A Strands agent that receives operator instructions and selects from a bounded tool surface.

2. `Tool layer`
   Thin typed tool wrappers that validate input, invoke the supervisor, and return structured results.

3. `Supervisor`
   A deterministic task orchestrator that owns task state, retries, approvals, recovery, and memory updates.

4. `World memory`
   A persistent store for place knowledge, aliases, observations, task history, and familiarity.

5. `Spot adapter`
   A boundary module that maps supervisor actions onto Spot-native navigation and autonomy APIs.

6. `Perception adapter`
   A boundary module for image capture, evidence extraction, and condition verification.

7. `Operator control plane`
   A separate operator-facing control path for stop control, approval handling, and health visibility.

8. `Ridealong UI`
   A Linux-compatible operator UI that shows live task state, evidence, approvals, and stop-state visibility.

### Runtime boundaries

- The agent can only call tools.
- Tools cannot directly command Spot; they route through the supervisor.
- The supervisor can call adapters and write memory.
- Adapters cannot mutate task policy; they only execute requests and return results.
- Stop control must remain operationally available through a path that does not depend on the main agent event loop.
- The ridealong UI is read-mostly for MVP, except for approvals and explicit operator stop actions.
- Tool handlers, supervisor transitions, and memory writes should stay lightweight and should not synchronously wait on noncritical work.
- Latency-sensitive execution paths should separate robot control flow from slower model inference and rich logging/UI updates.

## Storage Design

### Recommended MVP storage strategy

Use a hybrid local-first storage model:

- `SQLite` for structured entities and queryable history
- `JSON` columns or blobs for variable structured outputs such as detections and tool inputs
- filesystem artifact storage for images and large evidence payloads

Recommended locations:

- `data/world.sqlite`
- `data/artifacts/<task_id>/...`
- `profiles/inspection/*.yaml`
- `profiles/approval/*.yaml`

Rationale:

- SQLite is simple, inspectable, and testable in a greenfield repo
- it supports transactional updates across tasks, steps, and observations
- it avoids introducing an external service before the interfaces stabilize

### Why not a graph database in the MVP

SQLite in this design is the operational system of record, not the source of truth for robot navigation graphs. Spot GraphNav remains the mobility graph authority, while SQLite stores semantic bindings, task history, observations, approvals, and familiarity factors.

A semantic graph database such as Kuzu may be added later if multi-hop relationship traversal becomes a primary planning need. That is intentionally deferred until the MVP proves that graph-native queries are a bottleneck or a core planning primitive.

### Operator safety housekeeping

The MVP should include a separate terminal-based stop-control workflow as an operational safeguard. This is not a replacement for Boston Dynamics safety practices or hardware controls; it is an additional independent operator path so the main orchestration process is not the only way to stop or interrupt execution.

The MVP should also include a Linux-compatible ridealong UI for situational awareness, approval handling, and rapid diagnosis during runs.

### Latency design stance

The stack should treat LLM and VLM latency as configurable model-service cost, not as a reason to tolerate additional orchestration delay. Supervisor bookkeeping, memory persistence, and UI updates should remain thin enough that they do not become a dominant contributor to operator-visible latency.

For MVP, that means:

- keep tool handlers and supervisor transitions small and deterministic
- avoid blocking robot execution on nonessential UI or logging work
- measure timing at each boundary so model latency and orchestration latency can be distinguished

## Data Schema

### Design principles

- Use stable IDs for every first-class entity.
- Store canonical names separately from aliases.
- Keep navigation references out of the agent-facing interface.
- Store both explicit familiarity and the inputs required to derive familiarity.
- Normalize tasks, steps, and observations so execution can be audited later.

### Entity overview

#### `places`

Purpose:
A named environment location that the robot can reason about and, when configured, navigate to.

Suggested fields:

- `place_id` `TEXT PRIMARY KEY`
- `canonical_name` `TEXT NOT NULL`
- `zone` `TEXT`
- `tags_json` `TEXT NOT NULL DEFAULT '[]'`
- `active` `INTEGER NOT NULL DEFAULT 1`
- `explicit_familiarity_score` `REAL`
- `explicit_familiarity_band` `TEXT`
- `last_visited_at` `TEXT`
- `last_observed_at` `TEXT`
- `notes` `TEXT`
- `created_at` `TEXT NOT NULL`
- `updated_at` `TEXT NOT NULL`

#### `place_aliases`

Purpose:
Map human-facing names to known places without polluting the canonical place record.

Suggested fields:

- `alias_id` `TEXT PRIMARY KEY`
- `place_id` `TEXT NOT NULL`
- `alias` `TEXT NOT NULL`
- `alias_type` `TEXT NOT NULL`
- `confidence_hint` `REAL`
- `created_at` `TEXT NOT NULL`

Notes:

- `alias_type` can distinguish operator-defined, imported, or learned aliases
- enforce uniqueness on normalized alias text where practical

#### `graph_refs`

Purpose:
Store Spot navigation references and execution metadata that should not be exposed directly to the agent.

Suggested fields:

- `graph_ref_id` `TEXT PRIMARY KEY`
- `place_id` `TEXT NOT NULL`
- `graph_id` `TEXT`
- `waypoint_id` `TEXT`
- `waypoint_snapshot_id` `TEXT`
- `anchor_hint` `TEXT`
- `route_policy` `TEXT`
- `relocalization_hint_json` `TEXT NOT NULL DEFAULT '{}'`
- `active` `INTEGER NOT NULL DEFAULT 1`
- `created_at` `TEXT NOT NULL`
- `updated_at` `TEXT NOT NULL`

#### `assets`

Purpose:
Represent notable equipment or targets associated with a place.

Suggested fields:

- `asset_id` `TEXT PRIMARY KEY`
- `place_id` `TEXT NOT NULL`
- `canonical_name` `TEXT NOT NULL`
- `asset_type` `TEXT NOT NULL`
- `tags_json` `TEXT NOT NULL DEFAULT '[]'`
- `status_hint` `TEXT`
- `last_observed_at` `TEXT`
- `notes` `TEXT`
- `created_at` `TEXT NOT NULL`
- `updated_at` `TEXT NOT NULL`

#### `asset_aliases`

Suggested fields:

- `alias_id` `TEXT PRIMARY KEY`
- `asset_id` `TEXT NOT NULL`
- `alias` `TEXT NOT NULL`
- `alias_type` `TEXT NOT NULL`
- `confidence_hint` `REAL`
- `created_at` `TEXT NOT NULL`

#### `inspection_profiles`

Purpose:
Define repeatable inspection procedures without hardcoding them into the agent.

Suggested fields:

- `profile_id` `TEXT PRIMARY KEY`
- `name` `TEXT NOT NULL`
- `description` `TEXT`
- `required_evidence_json` `TEXT NOT NULL`
- `conditions_json` `TEXT NOT NULL`
- `capture_plan_json` `TEXT NOT NULL`
- `approval_profile_id` `TEXT`
- `timeout_s` `INTEGER`
- `retry_limit` `INTEGER`
- `active` `INTEGER NOT NULL DEFAULT 1`
- `created_at` `TEXT NOT NULL`
- `updated_at` `TEXT NOT NULL`

#### `approval_profiles`

Purpose:
Capture when operator approval is required for a class of actions.

Suggested fields:

- `approval_profile_id` `TEXT PRIMARY KEY`
- `name` `TEXT NOT NULL`
- `requires_navigation_approval` `INTEGER NOT NULL DEFAULT 0`
- `requires_inspection_approval` `INTEGER NOT NULL DEFAULT 0`
- `requires_retry_approval` `INTEGER NOT NULL DEFAULT 0`
- `notes` `TEXT`
- `created_at` `TEXT NOT NULL`
- `updated_at` `TEXT NOT NULL`

#### `tasks`

Purpose:
Track each operator request from intake through completion.

Suggested fields:

- `task_id` `TEXT PRIMARY KEY`
- `instruction` `TEXT NOT NULL`
- `operator_session_id` `TEXT`
- `resolved_target_type` `TEXT`
- `resolved_target_id` `TEXT`
- `resolution_mode` `TEXT`
- `resolution_confidence` `REAL`
- `inspection_profile_id` `TEXT`
- `status` `TEXT NOT NULL`
- `outcome_code` `TEXT`
- `created_at` `TEXT NOT NULL`
- `started_at` `TEXT`
- `ended_at` `TEXT`
- `result_summary` `TEXT`

#### `operator_events`

Purpose:
Store explicit operator approvals, stop actions, and acknowledgements as part of the audit trail.

Suggested fields:

- `operator_event_id` `TEXT PRIMARY KEY`
- `task_id` `TEXT`
- `event_type` `TEXT NOT NULL`
- `operator_id` `TEXT`
- `source` `TEXT NOT NULL`
- `details_json` `TEXT NOT NULL DEFAULT '{}'`
- `created_at` `TEXT NOT NULL`

#### `task_steps`

Purpose:
Track every supervisor step, tool invocation, retry, and intermediate outcome.

Suggested fields:

- `step_id` `TEXT PRIMARY KEY`
- `task_id` `TEXT NOT NULL`
- `sequence_no` `INTEGER NOT NULL`
- `tool_name` `TEXT NOT NULL`
- `step_state` `TEXT NOT NULL`
- `inputs_json` `TEXT NOT NULL`
- `outputs_json` `TEXT`
- `error_code` `TEXT`
- `retry_count` `INTEGER NOT NULL DEFAULT 0`
- `started_at` `TEXT NOT NULL`
- `ended_at` `TEXT`

#### `observations`

Purpose:
Represent captured evidence and derived perception output.

Suggested fields:

- `observation_id` `TEXT PRIMARY KEY`
- `task_id` `TEXT NOT NULL`
- `place_id` `TEXT`
- `asset_id` `TEXT`
- `observation_kind` `TEXT NOT NULL`
- `source` `TEXT NOT NULL`
- `artifact_uri` `TEXT`
- `summary` `TEXT`
- `structured_data_json` `TEXT NOT NULL DEFAULT '{}'`
- `confidence` `REAL`
- `captured_at` `TEXT NOT NULL`

#### `condition_results`

Purpose:
Store condition-check outputs independently of raw observations.

Suggested fields:

- `condition_result_id` `TEXT PRIMARY KEY`
- `task_id` `TEXT NOT NULL`
- `target_type` `TEXT NOT NULL`
- `target_id` `TEXT NOT NULL`
- `condition_id` `TEXT NOT NULL`
- `result` `TEXT NOT NULL`
- `confidence` `REAL`
- `evidence_ids_json` `TEXT NOT NULL DEFAULT '[]'`
- `rationale` `TEXT`
- `created_at` `TEXT NOT NULL`

#### `familiarity_factors`

Purpose:
Persist the inputs that support derived familiarity.

Suggested fields:

- `place_id` `TEXT PRIMARY KEY`
- `visit_count` `INTEGER NOT NULL DEFAULT 0`
- `successful_localizations` `INTEGER NOT NULL DEFAULT 0`
- `failed_localizations` `INTEGER NOT NULL DEFAULT 0`
- `last_successful_localization_at` `TEXT`
- `observation_freshness_s` `INTEGER`
- `alias_resolution_confidence` `REAL`
- `view_coverage_score` `REAL`
- `updated_at` `TEXT NOT NULL`

### Example familiarity derivation

Suggested derived score inputs:

- visit recency
- localization success rate
- observation freshness
- alias resolution confidence
- view coverage

Suggested output forms:

- numeric score `0.0 - 1.0`
- band such as `low`, `medium`, `high`

Use explicit familiarity as a cached snapshot for fast retrieval, then recompute derived familiarity when the relevant factors change.

## Tool Definitions

### Tool design rules

- tools are typed and side-effect scoped
- every tool returns a common response envelope
- the supervisor owns retries and policy decisions
- tools surface named entities, not robot-internal IDs

### Common response envelope

Successful result shape:

```json
{
  "status": "success",
  "outcome_code": "resolved_exact",
  "confidence": 0.94,
  "data": {},
  "evidence_ids": [],
  "next_recommended_actions": []
}
```

Non-success result shape:

```json
{
  "status": "blocked",
  "outcome_code": "ambiguous_low_confidence",
  "confidence": 0.42,
  "retryable": false,
  "message": "No candidate met minimum confidence.",
  "details": {},
  "evidence_ids": []
}
```

### `resolve_target`

Purpose:
Resolve a human reference to the most likely known place or asset.

Inputs:

- `name: str`
- `target_type: Literal["place", "asset", "auto"] = "auto"`
- `min_confidence: float = 0.70`

Behavior:

- match against canonical names and aliases
- return the best candidate if confidence is above threshold
- return ranked candidates without motion if confidence is below threshold

Response data:

- `selected_target_type`
- `selected_target_id`
- `selected_target_name`
- `resolution_mode`: `exact` or `best_effort`
- `ranked_candidates`

Typical outcome codes:

- `resolved_exact`
- `resolved_best_effort`
- `ambiguous_low_confidence`
- `unknown_target`

### `get_place_context`

Purpose:
Provide compact world-memory context for an already-resolved place.

Inputs:

- `place_id: str`

Response data:

- `canonical_name`
- `aliases`
- `zone`
- `last_visited_at`
- `last_observed_at`
- `explicit_familiarity`
- `derived_familiarity`
- `known_assets`
- `known_risks`

### `navigate_to_place`

Purpose:
Request movement to a known place through Spot-native navigation.

Inputs:

- `place_id: str`
- `route_policy: str = "default"`
- `approval_profile_id: str | null = null`
- `timeout_s: int | null = null`

Behavior:

- fetch internal graph references for the place
- check approval policy if present
- invoke Spot adapter navigation
- record step, outcome, and updated visit status

Typical outcome codes:

- `navigation_started`
- `navigation_succeeded`
- `approval_required`
- `approval_denied`
- `navigation_failed`
- `relocalization_required`

### `inspect_place`

Purpose:
Execute an inspection profile against a resolved place.

Inputs:

- `place_id: str`
- `inspection_profile_id: str`

Behavior:

- load capture plan and conditions from the profile
- trigger evidence capture through the supervisor
- store observations and condition results

Response data:

- `observation_ids`
- `condition_results`
- `inspection_summary`

Typical outcome codes:

- `inspection_completed`
- `inspection_inconclusive`
- `evidence_capture_failed`

### `capture_evidence`

Purpose:
Capture a specific evidence artifact without running a full inspection profile.

Inputs:

- `place_id: str`
- `capture_kind: str`
- `capture_profile: str | null = null`

Response data:

- `observation_id`
- `artifact_uri`
- `summary`
- `confidence`

Typical outcome codes:

- `observation_captured`
- `perception_inconclusive`
- `capture_failed`

### `verify_condition`

Purpose:
Evaluate a named condition using one or more observations.

Inputs:

- `target_type: Literal["place", "asset"]`
- `target_id: str`
- `condition_id: str`
- `evidence_ids: list[str] | null = null`

Response data:

- `result`: `true`, `false`, or `inconclusive`
- `confidence`
- `rationale`
- `evidence_ids`

### `relocalize`

Purpose:
Recover from localization failures using known hints for the current or target place.

Inputs:

- `place_id: str | null = null`
- `strategy: str = "nearest_hint"`

Typical outcome codes:

- `relocalization_succeeded`
- `relocalization_failed`

### `get_operator_status`

Purpose:
Return a compact status payload for the ridealong UI and terminal operator workflows.

Inputs:

- `task_id: str | null = null`

Response data:

- `active_task`
- `supervisor_state`
- `latest_step`
- `approval_pending`
- `stop_state`
- `recent_evidence_ids`

### `summarize_task`

Purpose:
Produce an operator-facing summary of task outcome and evidence.

Inputs:

- `task_id: str`

Response data:

- `status`
- `resolved_target`
- `result_summary`
- `evidence_ids`
- `condition_results`

## Supervisor State Machine

### Design goals

The supervisor must:

- own all side effects
- make recovery explicit
- update memory after every meaningful step
- separate `blocked`, `inconclusive`, and `failed`

### Task states

Suggested task states:

- `created`
- `resolving_target`
- `ready`
- `awaiting_approval`
- `executing`
- `recovering`
- `summarizing`
- `completed`
- `inconclusive`
- `blocked`
- `failed`
- `cancelled`

### State transitions

```text
created
  -> resolving_target

resolving_target
  -> ready                       if target resolved above threshold
  -> blocked                     if no candidate meets minimum confidence

ready
  -> awaiting_approval           if active profile requires approval
  -> executing                   otherwise

awaiting_approval
  -> executing                   if approved
  -> blocked                     if denied or expired

executing
  -> executing                   for next step in task plan
  -> recovering                  if retryable navigation/localization failure occurs
  -> summarizing                 if execution path is complete
  -> inconclusive                if evidence is insufficient but task is safely complete
  -> failed                      if non-retryable execution error occurs

recovering
  -> executing                   if recovery succeeds
  -> blocked                     if recovery requires human intervention
  -> failed                      if retry budget is exhausted

summarizing
  -> completed                   if summary generation succeeds
  -> inconclusive                if task executed but evidence remains insufficient

any non-terminal state
  -> cancelled                   on operator cancel
```

### Step-level execution policy

For each supervisor step:

1. validate tool request and task context
2. load relevant memory and profile data
3. check approval requirements
4. call the appropriate adapter
5. persist step result and any evidence
6. update task state
7. recompute derived familiarity when relevant inputs changed

### Recovery policy

Supported MVP recovery paths:

- navigation failure -> relocalize -> retry navigation once or up to profile limit
- capture failure -> retry capture once if retryable
- low-confidence evidence -> mark `inconclusive` rather than guessing
- approval denied -> mark `blocked`

### Terminal outcomes

- `completed`: task succeeded and summary is available
- `inconclusive`: task ran safely but evidence is insufficient for a definitive answer
- `blocked`: external intervention or clarification is required
- `failed`: unrecoverable execution error
- `cancelled`: operator terminated the task

### Operator control behaviors

For MVP, the supervisor should recognize these operator-originated events:

- `approval_granted`
- `approval_denied`
- `stop_requested`
- `task_cancel_requested`

A separate terminal stop-control path should be able to inject `stop_requested` without relying on the Strands agent process being healthy.

## Minimal First Implementation Plan

### Implementation goals

Build the smallest useful system that can:

- take a natural-language instruction about a known place
- resolve it with best-effort confidence
- navigate through a fake or real Spot adapter boundary
- capture evidence through a fake perception boundary
- store memory and produce an auditable task summary

### Recommended repository layout

```text
spec/
  context.md
  requirements.md
  design.md
  tasks.md
src/spot_train/
  config.py
  ids.py
  models.py
  ui/
    ridealong.py
  safety/
    terminal_estop.py
  memory/
    schema.py
    repository.py
    familiarity.py
  tools/
    contracts.py
    handlers.py
  supervisor/
    state_machine.py
    runner.py
    policies.py
  adapters/
    spot.py
    perception.py
    approval.py
  profiles/
    loader.py
tests/
  unit/
  integration/
profiles/
  inspection/
  approval/
data/
  artifacts/
```

### Recommended technology choices

- Python 3.x
- Pydantic for contracts and validation
- SQLite via `sqlite3` or SQLAlchemy Core for persistence
- Strands Agents Python SDK for tool registration and hooks
- YAML for inspection and approval profiles
- nonblocking or bounded-latency status propagation to the ridealong UI

### Phase 1: persistence and contracts

Deliverables:

- schema creation for core tables
- Pydantic models for entities and tool I/O
- repository layer for places, aliases, tasks, steps, and observations

Success criteria:

- can seed a small lab world model locally
- can create and query a task record end-to-end

### Phase 2: supervisor skeleton

Deliverables:

- task state machine
- step runner
- retry and timeout policy handling
- structured outcome codes
- transition timing instrumentation

Success criteria:

- a fake task can move through `created -> resolving_target -> executing -> summarizing -> completed`
- blocked and failed paths are test-covered

### Phase 3: tool layer

Deliverables:

- tool handlers for `resolve_target`, `get_place_context`, `navigate_to_place`, `inspect_place`, `capture_evidence`, `relocalize`, and `summarize_task`
- common response envelope
- lightweight handler path with explicit timing capture
- validation and error mapping

Success criteria:

- tools can be invoked against the fake adapters and return structured outputs

### Phase 4: adapters and profiles

Deliverables:

- fake Spot adapter for local development
- fake perception adapter for deterministic tests
- profile loader for inspection and approval profiles
- one seed inspection profile such as `lab_readiness_v1`

Success criteria:

- a known-place inspection run produces stored observations and a summary without live hardware

### Phase 5: operator controls and ridealong UI

Deliverables:

- terminal-based stop-control workflow separated from the main orchestration entrypoint
- Linux-compatible ridealong UI for task state, approvals, evidence, and stop-state visibility
- operator event persistence for approvals and stop actions

Success criteria:

- an operator can observe task state live on Linux during a dry run
- stop and approval actions are recorded in the audit trail

### Phase 6: Strands integration and observability

Deliverables:

- Strands agent registration for the bounded tool surface
- hook-based logging around tool invocation and supervisor outcomes
- task/evidence correlation IDs in logs
- ridealong UI status feed integration
- latency breakdown reporting for model calls versus orchestration overhead

Success criteria:

- a single operator instruction can be exercised end-to-end in a local dry run
- logs explain why each action was taken
- the ridealong UI reflects the same task and supervisor state seen in logs

## Initial test plan

Prioritize tests at the supervisor and contract layers.

### Unit tests

- alias resolution exact match
- operator stop event handling
- approval event state transitions
- alias resolution best-effort match above threshold
- alias resolution blocked below threshold
- familiarity derivation from factor changes
- approval profile gating
- retry exhaustion behavior
- supervisor timing capture on successful and failed transitions

### Integration tests

- end-to-end dry run for `check the optics bench`
- ridealong UI reflects supervisor progress during dry run
- terminal stop-control path interrupts an active dry run safely
- navigation failure followed by relocalization recovery
- inspection resulting in `inconclusive`
- summary generation with linked evidence IDs
- timing traces distinguish model-service latency from orchestration overhead

## Deferred items

These are intentionally not part of the MVP design:

- manipulation-specific flows
- end-to-end VLA control
- fleet management
- production deployment topology optimization
- advanced semantic map learning from free-form exploration
- an optional semantic graph layer such as Kuzu before graph-native traversal is proven necessary

## Risks and design watchpoints

- alias sprawl will degrade resolution quality unless normalization rules are enforced early
- too many JSON blobs will make memory hard to query; keep hot-path fields relational
- cached familiarity can drift unless recomputation is triggered deterministically
- if the tool surface grows beyond the current bounded set, orchestration complexity will leak back into the agent

## Source alignment

This design remains aligned with the source set in [context.md](/home/kwehden/projects/spot-train/spec/context.md):

- Spot-native autonomy remains the execution substrate
- Network Compute Bridge and external compute remain valid future integration points for perception services
- Strands hooks and typed tools provide the correct control points for policy enforcement and observability
- planning-over-skills patterns from SayCan and related systems remain the reference model for the MVP architecture
- Spot safety and stop-control remain separate operator concerns and should not be collapsed into the agent loop
