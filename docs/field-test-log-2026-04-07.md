# Field Test Log — 2026-04-07

## Session Summary

First live field test of the spot-train stack against Sunshine (Boston Dynamics Spot).
Robot connected, map recorded (79 waypoints, 11 named locations), navigation and
perception tested end-to-end through the Strands agent REPL with Bedrock Claude Sonnet 4.

## What Worked

- **Connection + lease**: `RealSpotAdapter.connect()` and `acquire_lease()` reliable
- **Target resolution**: "optics bench", "office 1", "home", "front door" all resolve correctly
- **Place context**: VLM-backed place descriptions with aliases, assets, zone info
- **Navigation**: Robot successfully navigated between waypoints (home → storage → home)
- **Perception capture**: All 5 cameras + depth captured, Nova Lite VLM generated
  accurate scene descriptions, point clouds saved as PLY files
- **Power tools**: `power on` / `sit down` / `power off` work through agent via natural language
- **Battery in prompt**: `sunshine(29%)>` updates after each command
- **Supervisor audit trail**: All tool calls create supervisor steps with persisted outcomes
- **Stop control**: Software stop tested and working

## Issues Identified

### 1. Relocalization fails without proper body transform (FIXED)

**Symptom**: "Invalid initial guess waypoint_tform_body" error on every relocalize attempt.

**Root cause**: `set_localization` was called without `waypoint_tform_body` (identity rotation)
and without `ko_tform_body` (current odom pose). The SDK needs both to match visual features.

**Fix applied**: Added identity `waypoint_tform_body.rotation.w = 1.0`, pass `ko_tform_body`
from `RobotStateClient`, and use generous `max_distance=20.0` / `max_yaw=π` tolerance.
Not yet tested live — will verify tomorrow.

### 2. Agent lacks planning/reasoning before acting

**Symptom**: "capture evidence at the front door" → agent captures at current location
instead of navigating first. Agent is too literal — resolves name and immediately calls
the most obvious tool.

**Needed**: System prompt update with a planning protocol:
- Assess: where is the robot now vs where does it need to be?
- Navigate first if not at the target location
- Then capture/inspect
- Check robot state (powered on? standing?) before motion commands

### 3. Supervisor trace leaks into REPL stdout

**Symptom**: Lines like `[INFO] spot_train.supervisor.runner | task_id=- step_id=- | task tsk_xxx -> executing`
appear inline with agent responses, cluttering the operator view.

**Fix planned**: Route these to the viewer's command trace pane (right side of bottom bar)
instead of stderr/stdout. Part of the viewer UI implementation.

### 4. Navigation lost localization mid-route

**Symptom**: Robot started navigating to front door, moved through storage, then got
blocked with relocalization error partway through the route.

**Likely cause**: The earlier session where I grabbed the lease from outside the REPL
may have corrupted the localization state. The robot ended up at an unexpected position
and couldn't re-localize with the old visual features.

**Mitigation**: Never grab the lease outside the active REPL session. The relocalize
fix (issue #1) should also help recovery when this happens.

### 5. Task context not carried across multi-step agent plans

**Symptom**: Each tool call within a single agent response creates a new task or reuses
the same task, but the supervisor marks the task as terminal (completed/blocked) after
each side-effect tool. Subsequent tool calls in the same agent turn get `task_id_required`
or start a fresh task.

**Needed**: The REPL creates one task per instruction, but the supervisor's `run_task`
marks it terminal after the first step completes. Multi-step plans (resolve → navigate →
capture) need the task to stay open across multiple handler calls.

### 6. SQLite check_same_thread (FIXED)

**Symptom**: "database objects created in a thread can only be used in that same thread"
when Strands calls tools from its async executor thread.

**Fix applied**: `sqlite3.connect(path, check_same_thread=False)` in `WorldRepository.connect()`.

### 7. Idempotent seed for persistent DB (FIXED)

**Symptom**: `UNIQUE constraint failed: places.place_id` on second run with `data/world.sqlite`.

**Fix applied**: `if not repo.list_places(): repo.seed_minimal_lab_world()` in `create_robot_session()`.

## UI Design Sample — Command Trace (right pane)

This is what currently leaks into the REPL and should go to the viewer's bottom-right pane:

```
[03:00:10] Tool #1: power_on_robot
[03:00:10] task tsk_0c3f4293 -> executing
[03:00:16] task tsk_0c3f4293 -> summarizing
[03:00:16] task tsk_0c3f4293 -> completed

[03:00:45] Tool #3: resolve_target("front door") -> success
[03:00:45] Tool #4: capture_evidence(plc_front_door, photo)
[03:00:45] task tsk_85cb8ccb -> executing
[03:00:50] task tsk_85cb8ccb -> summarizing
[03:00:50] task tsk_85cb8ccb -> completed

[03:03:10] Tool #6: navigate_to_place(plc_front_door)
[03:03:10] task tsk_f7c0295e -> executing
[03:03:41] task tsk_f7c0295e -> blocked (relocalization error)
[03:03:43] Tool #7: relocalize(plc_home) -> inconclusive
[03:03:45] Tool #8: relocalize(plc_front_door) -> inconclusive

[03:04:49] Tool #10: resolve_target("home") -> success
[03:04:49] Tool #11: navigate_to_place(plc_home)
[03:04:49] task tsk_8c1ef8ae -> executing
[03:05:19] task tsk_8c1ef8ae -> blocked (relocalization error)
```

## UI Design Sample — VLM Descriptions (left pane)

```
[03:00:50] Front-left: empty workshop/storage area, tiled floors, white walls,
           high ceilings. Tables and chairs stacked against walls.
           Depth: nearest 350mm, farthest 13m, mean 2.8m.
           Point cloud: 22,798 points (7.4% coverage).

[03:00:50] Front-right: corridor extending ~4m, fluorescent lighting,
           door frame visible at ~3m. Clear path forward.
           Depth: nearest 890mm, farthest 8.2m.

[03:00:50] Left: wall ~0.8m, electrical panel, fire extinguisher.
           Depth: nearest 420mm, coverage 12%.

[03:00:50] Right: open area, desks with monitors ~2m, person walking ~3.5m.
           Depth: nearest 1.1m, farthest 6.4m.

[03:00:50] Back: doorway ~1.2m, hallway extending beyond.
           Depth: nearest 680mm.
```

## Tomorrow's Priorities

1. Verify relocalize fix works live
2. Update system prompt with planning protocol
3. Implement the viewer UI (spec/viewer-design.md)
4. Address task context issue (#5) for multi-step agent plans
5. Push PR #8 fixes and merge
