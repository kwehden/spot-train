# Tasks

## Status

Draft for Gate 4 approval.

## Purpose

Break the approved design into an ordered, minimal implementation plan for this repository.

## Execution principles

- Build the smallest useful vertical slice first.
- Keep all robot side effects behind adapters and the supervisor.
- Treat stop control, ridealong visibility, and latency instrumentation as first-class MVP work.
- Prefer dry-run and fake-adapter validation before any live robot dependency.
- Keep Python work isolated to a project virtualenv.

## Phase 0: repository bootstrap

### T-001 Create repository skeleton

Deliverables:

- create `src/spot_train/`, `tests/`, `profiles/`, `data/`, and supporting package structure from the design
- add placeholder `__init__.py` files where needed
- add a local virtualenv-oriented developer setup note

Exit criteria:

- repository structure matches the approved design closely enough to begin implementation

### T-002 Establish project configuration

Deliverables:

- choose and add Python project metadata and dependency management files
- define formatting, linting, and test commands
- ensure commands assume project virtualenv usage

Exit criteria:

- a developer can install dependencies in a virtualenv and run the baseline checks locally

## Phase 1: persistence and contracts

### T-003 Implement core IDs and domain models

Deliverables:

- add shared ID generation helpers
- add typed models for `Place`, `Asset`, `Task`, `TaskStep`, `Observation`, `ConditionResult`, `InspectionProfile`, `ApprovalProfile`, and `OperatorEvent`
- add common enums and outcome codes

Exit criteria:

- domain models cover the approved schema and can be instantiated in tests

### T-004 Implement storage schema

Deliverables:

- create schema creation logic for the MVP SQLite database
- include tables for places, aliases, graph refs, assets, profiles, tasks, task steps, observations, condition results, familiarity factors, and operator events
- include indexes for likely hot-path lookups such as alias resolution and task history

Exit criteria:

- a fresh local database can be created deterministically in tests

### T-005 Implement repository layer

Deliverables:

- CRUD-style repository functions for core entities
- task-step append operations and observation persistence
- familiarity factor updates and derivation hooks
- operator event persistence

Exit criteria:

- tests can create, query, and update the world model and task history without direct SQL in business logic

### T-006 Seed minimal world and profile data

Deliverables:

- add one minimal lab seed dataset with a few places, aliases, and assets
- add one inspection profile such as `lab_readiness_v1`
- add one approval profile used by the MVP dry run

Exit criteria:

- dry-run tasks have enough seeded data to resolve a place and execute an inspection flow

## Phase 2: supervisor core

### T-007 Implement supervisor state model

Deliverables:

- implement task states and transitions from the design
- encode terminal outcomes and recovery states
- add explicit handling for `blocked`, `inconclusive`, `failed`, and `cancelled`

Exit criteria:

- task transitions are deterministic and testable without adapters

### T-008 Implement supervisor runner

Deliverables:

- implement step execution orchestration
- wire task lifecycle updates, step persistence, and evidence attachment
- ensure only the supervisor can trigger adapter side effects

Exit criteria:

- a fake task can traverse the full success path and persist each step

### T-009 Implement retry, timeout, and recovery policies

Deliverables:

- implement retry limits
- implement timeout handling hooks
- implement relocalization-first recovery for retryable navigation failures
- implement inconclusive handling for low-confidence evidence

Exit criteria:

- retryable and non-retryable failures take the expected transition paths

## Phase 3: tool contracts and handlers

### T-010 Implement tool request and response contracts

Deliverables:

- define typed I/O contracts for `resolve_target`, `get_place_context`, `navigate_to_place`, `inspect_place`, `capture_evidence`, `verify_condition`, `relocalize`, `get_operator_status`, and `summarize_task`
- define common response envelope and outcome code mapping

Exit criteria:

- tool contracts validate inputs and support structured outputs in tests

### T-011 Implement tool handlers

Deliverables:

- add thin handlers that validate input and delegate to the supervisor or repository layer
- enforce that handlers do not directly use raw Spot SDK calls
- keep handler logic lightweight and timing-aware

Exit criteria:

- handlers return consistent structured responses against fake adapters and seeded data

### T-012 Implement target resolution logic

Deliverables:

- exact alias matching
- best-effort matching above threshold
- blocked results with ranked candidates below threshold
- storage of resolution confidence and resolution mode on tasks

Exit criteria:

- best-effort target resolution behaves as specified in Gate 2 requirements

## Phase 4: adapters and perception boundary

### T-013 Implement fake Spot adapter

Deliverables:

- add a fake navigation adapter with success, failure, and relocalization-needed modes
- expose navigation outcomes without leaking robot-internal details to tools

Exit criteria:

- supervisor tests can simulate navigation success and recovery flows without hardware

### T-014 Implement fake perception adapter

Deliverables:

- add deterministic evidence capture outputs
- add deterministic condition verification outputs with confidence values
- support inconclusive outcomes cleanly

Exit criteria:

- inspection tests can simulate evidence-rich and inconclusive runs deterministically

### T-015 Define real adapter interfaces

Deliverables:

- define Spot adapter interface boundaries for navigation, relocalization, and stop-related integration points
- define perception adapter interface boundaries for image capture and condition analysis
- keep real implementations stubbed until after dry-run validation

Exit criteria:

- the codebase has stable integration boundaries even if only fake adapters are active

## Phase 5: operator safety and ridealong

### T-016 Implement terminal stop-control workflow

Deliverables:

- add a terminal-based stop-control entrypoint separated from the main orchestration path
- ensure stop requests are recorded as operator events
- ensure the stop path can signal the supervisor independently of the agent loop

Exit criteria:

- an active dry run can be interrupted through the terminal stop workflow and recorded in task history

### T-017 Implement operator event handling

Deliverables:

- add approval-granted, approval-denied, stop-requested, and cancel-requested handling
- persist operator-originated actions and route them into supervisor transitions

Exit criteria:

- operator-originated events change supervisor state predictably and remain auditable

### T-018 Implement Linux ridealong UI

Deliverables:

- add a minimal Linux-compatible UI for task state, approvals, evidence references, and stop-state visibility
- make the UI read-mostly except for explicit operator actions such as approval and stop
- source data from the same supervisor/task records used elsewhere

Exit criteria:

- a dry-run task can be observed live through the ridealong UI without changing task semantics

## Phase 6: latency and observability

### T-019 Add timing instrumentation

Deliverables:

- capture timings for tool invocation, supervisor transitions, adapter calls, and model-backed steps
- record timing fields in logs or traces without making them part of the critical path

Exit criteria:

- tests and dry runs can distinguish model-service latency from orchestration overhead

### T-020 Add logging and correlation

Deliverables:

- add structured logs for tasks, steps, observations, approvals, and stop events
- ensure correlation IDs connect tasks, steps, evidence, and operator events
- ensure ridealong status can be reconciled with logs

Exit criteria:

- a developer can reconstruct why a task progressed or stopped from persisted records and logs

### T-021 Keep noncritical updates off the control path

Deliverables:

- review the implementation for synchronous noncritical work in latency-sensitive flows
- bound or defer UI/logging/status-update work where practical
- document the intended control-path versus observer-path split

Exit criteria:

- the stack architecture clearly separates robot control flow from observer and reporting paths

## Phase 7: Strands integration

### T-022 Register bounded Strands tools

Deliverables:

- expose the approved tool surface through Strands
- ensure only the bounded tool set is registered
- add hook points for policy enforcement and observability

Exit criteria:

- a Strands agent can invoke the MVP tool surface against the dry-run stack

### T-023 Add task summary generation path

Deliverables:

- produce operator-facing summaries from task records, evidence, and condition results
- ensure summaries are backed by stored evidence references

Exit criteria:

- completed and inconclusive dry runs produce useful summaries with evidence links

## Phase 8: verification

### T-024 Add unit test suite

Minimum coverage:

- exact alias resolution
- best-effort alias resolution
- blocked low-confidence resolution
- familiarity derivation updates
- approval event transitions
- stop event handling
- retry exhaustion behavior
- transition timing capture

Exit criteria:

- unit tests cover the core contracts and supervisor policy logic

### T-025 Add integration dry-run suite

Minimum coverage:

- end-to-end `check the optics bench` dry run
- navigation failure followed by relocalization recovery
- inspection with inconclusive evidence
- ridealong UI reflects supervisor progress
- terminal stop-control interrupts an active dry run safely
- latency traces distinguish orchestration overhead from model-backed work

Exit criteria:

- dry-run integration tests exercise the main MVP path without live hardware

### T-026 Verify spec alignment

Deliverables:

- review implemented modules against requirements and design
- confirm that no raw Spot SDK calls are reachable from agent-facing handlers
- confirm that safety/UI/latency concerns are represented in code and tests

Exit criteria:

- implementation is ready for post-execution verification and review under Gate 5 workflow

## Suggested execution order

1. `T-001` to `T-006`
2. `T-007` to `T-009`
3. `T-010` to `T-012`
4. `T-013` to `T-015`
5. `T-016` to `T-018`
6. `T-019` to `T-021`
7. `T-022` to `T-023`
8. `T-024` to `T-026`

## Parallelization notes

Safe early parallel work after bootstrap:

- persistence/schema work can proceed in parallel with fake adapter design
- ridealong UI scaffolding can proceed in parallel with supervisor core once operator status contracts are stable
- logging and timing infrastructure can begin once task and step models stabilize

Avoid parallelizing these before interfaces settle:

- Strands tool registration before contracts are fixed
- real adapter work before fake adapter flows validate the boundaries
- UI semantics before supervisor state and operator events are fixed

## Open implementation questions

These do not block Gate 4, but should be answered before coding begins:

- what Python packaging and dependency tool should this repo standardize on
- what Linux UI stack is preferred for the ridealong view
- what exact stop-control integration approach is appropriate for the deployment environment while remaining aligned with Boston Dynamics safety practices
- what initial latency budgets should be used to judge orchestration overhead during dry runs
