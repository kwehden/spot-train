# Requirements

## Status

Draft for Gate 2 approval.

## Purpose

Define the functional and non-functional requirements for a concept-first MVP that enables a Strands agent to direct Boston Dynamics Spot in an indoor lab through a world-memory layer and a deterministic supervisor.

## Scope

This requirements set covers:

- memory-driven familiarity with an indoor lab
- a bounded tool interface exposed to the agent
- a supervisor that mediates between agent intent and Spot execution
- inspection-oriented and navigation-oriented MVP workflows

This requirements set does not require:

- end-to-end VLA control
- learned locomotion
- broad manipulation planning
- multi-robot coordination
- manipulation-specific MVP requirements

## System Context

The target system is a `Strands planner -> world model -> supervisor -> Spot skills` stack in which:

- Spot-native autonomy remains responsible for navigation and execution safety
- the world model stores spatial, semantic, and episodic knowledge
- the supervisor executes typed skills, handles failures, and updates memory

## Definitions

- `place`: a named environment location such as a bench, room, station, or corridor segment
- `asset`: a notable object or system associated with a place, such as a charger, printer, or instrument
- `spatial memory`: navigation-relevant identifiers and relationships, including GraphNav references
- `semantic memory`: human-facing names, aliases, tags, and relationships among places and assets
- `episodic memory`: time-stamped records of visits, observations, task executions, and outcomes
- `inspection profile`: a reusable procedure describing what evidence to collect and what conditions to assess at a target
- `skill`: a deterministic, typed operation callable by the supervisor and indirectly by the agent

## Functional Requirements

### Goal and task intake

- `REQ-001` The system shall accept a high-level operator instruction expressed in natural language.
- `REQ-002` The system shall convert each accepted instruction into a structured task record with a unique identifier.
- `REQ-003` For each task, the system shall persist the original instruction, task timestamp, and execution status.
- `REQ-004` When an instruction references a known place or asset alias, the system shall resolve that reference to an internal entity identifier.
- `REQ-005` If an instruction cannot be resolved with sufficient confidence for an exact match, the system shall attempt best-effort resolution to the most likely known target, return the selected target with a confidence value, and avoid robot motion only when no candidate meets the configured minimum confidence.

### World memory

- `REQ-006` The system shall maintain separate representations for spatial memory, semantic memory, and episodic memory.
- `REQ-007` The system shall store a stable internal identifier for every place known to the system.
- `REQ-008` The system shall allow each place to have one or more human-facing aliases.
- `REQ-009` The system shall associate each navigable place with one or more Spot navigation references when such references exist.
- `REQ-010` The system shall store a last-observed timestamp for each place and asset when observations exist.
- `REQ-011` The system shall store visit history for completed and attempted robot visits.
- `REQ-012` The system shall store observation records that can reference images, structured detections, summaries, and confidence values.
- `REQ-013` The system shall preserve the relationship between a place, its assets, and the observations collected there.
- `REQ-014` The system shall store an explicit familiarity assessment for each place and shall also support deriving familiarity at query time from stored history, freshness, and confidence signals.
- `REQ-015` When a task completes or fails, the system shall append an episodic record describing the outcome.

### Planning and tool interface

- `REQ-016` The system shall expose a bounded set of typed tools to the Strands agent instead of raw Spot SDK methods.
- `REQ-017` Each tool shall define explicit inputs, outputs, and failure modes.
- `REQ-018` The system shall ensure that agent-issued tool calls are validated before execution.
- `REQ-019` The system shall allow the agent to request place resolution, navigation, inspection, evidence capture, condition verification, re-localization, and task summary generation.
- `REQ-020` The system shall return structured tool results suitable for agent replanning.
- `REQ-021` If a tool request violates schema or policy, the system shall reject the request with a structured error.

### Supervisor behavior

- `REQ-022` The system shall include a deterministic supervisor between agent tool calls and Spot execution.
- `REQ-023` The supervisor shall manage task lifecycle states from intake through completion, failure, or cancellation.
- `REQ-024` When a tool call requires robot action, the supervisor shall verify preconditions before execution.
- `REQ-025` If required preconditions are not met, the supervisor shall stop that action and return a structured failure or blocked result.
- `REQ-026` The supervisor shall update task state after every executed step.
- `REQ-027` The supervisor shall write memory updates after every step that changes environment knowledge or task status.
- `REQ-028` If navigation fails, the supervisor shall support at least one recovery path such as re-localization, retry, or safe abort.
- `REQ-029` If perception results are low-confidence, the supervisor shall record the uncertainty and return an inconclusive result rather than fabricating success.
- `REQ-030` When an execution step produces evidence, the supervisor shall attach that evidence to the active task record.
- `REQ-031` The supervisor shall distinguish between at least these outcomes: `success`, `inconclusive`, `blocked`, `failed`, and `cancelled`.
- `REQ-032` The supervisor shall support operator-configurable retry limits and timeout limits.
- `REQ-033` Operator approval gates shall be profile-specific, and when enabled for a profile, the supervisor shall pause before configured high-impact actions and record the approval decision.

### Spot integration

- `REQ-034` The system shall treat Spot-native navigation and mission infrastructure as the execution substrate for movement tasks.
- `REQ-035` The system shall map navigational intents onto Spot-compatible waypoints, missions, routes, or equivalent abstractions.
- `REQ-036` The system shall permit execution components to run off-robot or on supported robot-adjacent compute.
- `REQ-037` The system shall avoid requiring direct low-level locomotion generation by the agent for MVP workflows.

### Inspection and evidence workflows

- `REQ-038` The system shall support an inspection-oriented task flow for known places.
- `REQ-039` An inspection profile shall specify the evidence to collect and the conditions to assess at a target.
- `REQ-040` When executing an inspection profile, the system shall collect the required evidence or return a structured reason why collection failed.
- `REQ-041` The system shall support condition-verification results of `true`, `false`, and `inconclusive`.
- `REQ-042` The system shall produce an operator-facing summary that references the task outcome and supporting evidence.

### Observability and auditability

- `REQ-043` The system shall emit logs or traces for task creation, tool invocation, supervisor decisions, execution outcomes, and memory updates.
- `REQ-044` The system shall make it possible to reconstruct why a robot action was taken from recorded task and tool history.
- `REQ-045` The system shall assign identifiers that allow observations, actions, and summaries to be correlated to a single task.

### Operator safety and ridealong experience

- `REQ-046` The system shall provide a separate terminal-based software E-Stop or stop-control workflow that is operationally independent from the main agent and supervisor process.
- `REQ-047` The MVP shall provide a Linux-compatible ridealong UI for monitoring task execution in real time.
- `REQ-048` The ridealong UI shall display at least active task status, resolved target, current supervisor state, recent tool outcomes, and recent evidence references.
- `REQ-049` The ridealong UI shall surface approval prompts, blocked states, and stop-state visibility to the operator.

## Non-Functional Requirements

- `NFR-001` The MVP shall prioritize explainability over autonomy breadth.
- `NFR-002` The MVP shall prefer deterministic, inspectable control flow over opaque agent-driven execution loops.
- `NFR-003` The system shall be modular enough to swap perception providers without changing the agent-facing tool contract.
- `NFR-004` The system shall be modular enough to add future manipulation or VLM/VLA integrations without redesigning the world-memory core.
- `NFR-005` The system shall store memory in a form that can be inspected and edited by developers during early development.
- `NFR-006` The system shall be implementable as a minimal greenfield repository with a small number of core modules.
- `NFR-007` The MVP shall support safe failure modes that do not silently continue after unresolved ambiguity or failed execution preconditions.
- `NFR-008` The system shall be testable at the supervisor and tool-contract layers without requiring a live robot for every test.
- `NFR-009` The system shall preserve enough evidence and metadata for post-run review by an operator or developer.
- `NFR-010` The MVP shall assume a known indoor lab and does not need to generalize to arbitrary environments.
- `NFR-011` Safety-relevant stop control shall remain available even if the main orchestration process is degraded or blocked.
- `NFR-012` The ridealong UI shall run on Linux without requiring proprietary tablet hardware.
- `NFR-013` The orchestration stack shall be designed so that its control-plane overhead is not a primary contributor to end-to-end task latency.
- `NFR-014` The system shall isolate LLM/VLM inference latency from supervisor bookkeeping, storage, and UI update paths wherever practical.
- `NFR-015` The system shall emit timing data for tool invocation, supervisor transitions, adapter calls, and model-backed perception/reasoning steps so latency regressions can be measured.

## Constraints

- `CON-001` The MVP shall assume Boston Dynamics Spot as the robot platform.
- `CON-002` The MVP shall assume Strands Agents as the high-level agent framework.
- `CON-003` The MVP shall not depend on a VLA or robot foundation model to complete core navigation-and-inspection workflows.
- `CON-004` The MVP shall be designed for a greenfield repository with no pre-existing application code.

## Acceptance Signals for the Design Phase

The design artifact should be considered aligned with these requirements only if it defines:

- a concrete schema for places, assets, observations, tasks, and familiarity-related fields
- a bounded tool surface with typed request and response structures
- a supervisor state machine with explicit success, retry, inconclusive, and failure paths
- a minimal implementation plan that can be executed incrementally in this repository

## Resolved Requirement Decisions

- ambiguity handling defaults to `best effort with confidence`
- operator approvals are profile-specific
- familiarity is stored both as an explicit assessment and derivable at query time
- the first MVP includes no manipulation-specific requirements
