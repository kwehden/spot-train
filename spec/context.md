# Context

## Status

Draft for Gate 1 approval.

## Problem Statement

This repository is intended to support an indoor-lab autonomy stack for Boston Dynamics Spot driven by a Strands agent. The target capability is not open-ended whole-body policy learning. The near-term problem is to translate natural-language instructions into reliable robot behavior using:

- developed persistent knowledge of the lab
- Spot-native navigation and autonomy primitives
- bounded perception tools
- deterministic supervision around agent actions

The system should make Spot appear "familiar" with the lab by remembering places, aliases, assets, observations, prior visits, and task outcomes, then using that memory to plan and execute repeatable work.

## Scope Framing

The first phase is a concept-first, greenfield design for:

- a suggested data schema for spatial, semantic, and episodic memory
- tool definitions for the Strands-facing orchestration layer
- a supervisor state machine between agent intent and Spot execution
- a minimal first implementation plan for this repository

This phase is explicitly about architecture and artifact definition, not full robot deployment.

## Repository State

Current repository state at the start of this spec effort:

- `AGENTS.md` exists and requires a System2, gated, spec-driven workflow
- no `spec/` artifacts existed before this draft
- no source tree, tests, docs, or prior implementation are present

Implication:

- there are no legacy constraints from existing code
- architecture drift is the main risk unless requirements and interfaces are pinned early

## Operational Context

### Environment

- indoor lab with recurring routes, named areas, benches, stations, doors, and dock locations
- partially structured, but subject to change: moved equipment, blocked paths, lighting shifts, people in the loop
- repeated tasks are likely inspection, patrol, status checking, evidence capture, and basic operator assistance

### Robot and platform assumptions

- robot platform is Boston Dynamics Spot, potentially with Arm and/or Spot CAM depending on deployment
- Spot GraphNav, Missions, Autowalk, and docking remain the source of truth for navigation and execution safety
- custom logic can run off-robot, on a compute payload, or on CORE I/O depending on latency and deployment needs
- the high-level agent layer is expected to be implemented with Strands Agents in Python

### User interaction model

- a human issues high-level instructions such as "check the optics bench" or "inspect the charging station"
- the system resolves human language to known places/assets, executes robot skills, gathers evidence, updates memory, and reports results

## Key Architectural Decision

The recommended direction is:

**Strands planner -> world model -> supervisor -> Spot skills**

and not:

**LLM/VLA -> direct low-level robot control**

### Why this is the right starting point

1. Spot already provides production autonomy primitives for mapping, localization, route traversal, missions, and callbacks. Replacing those with a VLA would introduce avoidable risk.
2. The target environment is a known indoor lab, where the main challenge is semantic grounding and memory freshness, not learning locomotion from pixels.
3. Most successful recent robot systems papers still combine planners, perception, and robot-native skills through explicit orchestration rather than relying on direct end-to-end control.
4. The requested capability, "memory-driven familiarity with the environment," is more naturally expressed as spatial, semantic, and episodic memory than as an action-only policy.

## Research Findings

### 1. Spot already has the right abstraction boundaries

Boston Dynamics' autonomy stack is built around GraphNav maps, missions, and callback services:

- the autonomy docs position GraphNav as the mapping, localization, and autonomous traversal system
- Mission Service exposes high-level autonomous behavior using behavior trees
- Remote mission nodes and area callbacks provide insertion points for custom logic at waypoints or regions
- Network Compute Bridge supports offboard/onboard perception or model inference behind a robot-native API

Design implication:

- use Spot services for motion, traversal, route execution, and safety-adjacent control
- insert semantic reasoning and perception at mission nodes, callback regions, and tool boundaries

### 2. The right problem is orchestration, not direct action generation

The SayCan and Inner Monologue lines of work are directly relevant. They show that language models are strongest when they:

- choose among explicit skills
- incorporate feasibility or affordance constraints
- receive closed-loop environment feedback for replanning

They do not require the model to generate raw robot actions. This matches the desired lab workflow much better than a VLA-first approach.

Design implication:

- the planner should reason over skills and world state
- the supervisor should feed execution results back into the agent as structured observations
- success/failure and scene summaries should be first-class inputs to replanning

### 3. Open-world robot systems still rely heavily on explicit memory and state machines

OK-Robot is especially relevant because it combines:

- open-vocabulary perception
- semantic memory over an environment
- navigation and manipulation primitives
- a simple state-machine style composition

The important lesson is not the exact stack, but that real-world performance depends heavily on how perception, memory, and skills are combined.

Design implication:

- treat world memory as a core subsystem, not an afterthought
- keep execution logic explicit and inspectable
- expect robust behavior to come from careful composition rather than a single "smart model"

### 4. Strands already supports the right control points for orchestration

Current Strands docs emphasize:

- tool-based agent execution
- hooks around invocation and tool lifecycles
- observability primitives for traces, metrics, and logs

Design implication:

- expose robot capabilities as a small, typed tool surface
- use hooks and/or steering-style middleware to enforce policy checks before tool execution
- instrument the system from day one so failures are traceable through plan, tool, and execution spans

### 5. VLA work remains useful, but as a future extension

Recent VLA systems such as RT-2, OpenVLA, and pi0/pi0.5 are valuable reference points for long-term generalization and manipulation research. They are not the best first answer for this repository's immediate goal. For a known indoor lab and Spot-native mobility stack, the urgent gap is not low-level action synthesis; it is semantic grounding, durable memory, and supervision.

Design implication:

- treat VLM/VLA integration as an optional perception or manipulation enhancement later
- do not make the MVP depend on fine-tuning a robot foundation model

## Proposed System Boundaries

### In scope for the concept and MVP design

- human-friendly place and asset names mapped onto Spot navigation artifacts
- memory of visits, observations, and task outcomes
- structured tool calls from a Strands agent
- deterministic supervisor flow for retries, fallbacks, and approvals
- integration points for perception services and future manipulation

### Out of scope for the MVP design

- full VLA-based locomotion or manipulation control
- learned end-to-end navigation
- broad multi-robot coordination
- cloud-scale fleet management
- deployment-hardening for every Spot payload topology

## Working Assumptions

- the lab can be represented as a stable set of named places plus a changing set of observations
- at least one GraphNav map exists or will be created early in implementation
- operator-defined aliases and inspection profiles will be more valuable than fully automatic ontology induction
- many tasks will be inspect/report workflows rather than manipulation
- failures should degrade to safe, explainable outcomes such as re-localize, ask for clarification, or stop and report

## Risks and Unknowns

### Product and task risks

- The exact task set is not yet fixed: patrol, readiness checks, image capture, status inspection, and manipulation may have different requirements.
- The level of autonomy expected during ambiguity is unclear: should the system ask questions early or make best-effort assumptions?

### Technical risks

- A semantic layer that is too free-form will become hard to query reliably.
- A skill layer that exposes raw Spot APIs instead of stable verbs will make the agent brittle.
- Perception confidence and localization confidence may drift independently; the supervisor must distinguish those failure modes.
- If future work adds manipulation, the current design must accommodate richer task and affordance models without breaking core interfaces.

### Deployment risks

- Compute placement is still open: laptop, offboard server, CORE I/O, or payload GPU.
- Real-world network conditions may affect any design that depends on offboard inference.
- Safety review will matter once autonomous callbacks can affect route execution.

## Initial Direction for the Next Artifact

The requirements artifact should formalize:

- the memory model as separate spatial, semantic, and episodic concerns
- the minimal tool contract the Strands agent is allowed to call
- supervisor guarantees for retries, timeouts, and safe failure
- observability and approval requirements for robot actions

## Source Notes

Primary sources used for this context draft:

- Boston Dynamics Autonomy overview: https://dev.bostondynamics.com/docs/concepts/autonomy/README.html
- Boston Dynamics Mission Service: https://dev.bostondynamics.com/docs/concepts/autonomy/missions_service.html
- Boston Dynamics GraphNav technical summary: https://dev.bostondynamics.com/docs/concepts/autonomy/graphnav_tech_summary.html
- Boston Dynamics GraphNav area callbacks: https://dev.bostondynamics.com/docs/concepts/autonomy/graphnav_area_callbacks.html
- Boston Dynamics Network Compute Bridge: https://dev.bostondynamics.com/docs/concepts/network_compute_bridge.html
- Boston Dynamics custom apps / CORE I/O docs: https://dev.bostondynamics.com/docs/payload/docker_containers.html
- Boston Dynamics Arm services: https://dev.bostondynamics.com/docs/concepts/arm/arm_services.html
- Strands tool docs: https://strandsagents.com/1.4.x/documentation/docs/user-guide/concepts/tools/python-tools/
- Strands hooks docs: https://strandsagents.com/1.0.x/documentation/docs/user-guide/concepts/agents/hooks/
- Strands observability docs: https://strandsagents.com/0.1.x/documentation/docs/user-guide/observability-evaluation/observability/
- SayCan project page: https://say-can.github.io/
- PaLM-SayCan overview: https://sites.research.google/palm-saycan
- Inner Monologue project page: https://innermonologue.github.io/
- OK-Robot paper/project: https://arxiv.org/abs/2401.12202 and https://ok-robot.github.io/
- RT-2 paper: https://arxiv.org/abs/2307.15818
- OpenVLA paper: https://arxiv.org/abs/2406.09246
- Physical Intelligence openpi repo: https://github.com/Physical-Intelligence/openpi
