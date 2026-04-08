# Spatial Awareness Design

## Three-Tier Perception Architecture

```
Tier 1: SPATIAL AWARENESS (continuous, ~1-2 Hz, no VLM)
  - Front-left + front-right cameras + depth
  - Depth quadrant analysis (obstacle distances by direction)
  - Robot pose from odom
  - Injected into every agent prompt automatically
  - Feeds move_robot precondition checks (refuse to move into walls)
  - Latency: <50ms to read cached state

Tier 2: SCENE DESCRIPTION (periodic, ~10s, lightweight VLM)
  - Front-left + front-right camera images → Nova Lite
  - 2-sentence description: obstacles + notable objects
  - Cached in LocalScene.scene_description
  - Injected into agent prompt alongside Tier 1 data
  - Latency: ~1s VLM call, async/cached

Tier 3: EVIDENCE CAPTURE (on-demand, full stack)
  - All 5 cameras + all 5 depth + point clouds + full VLM
  - Persisted to world DB as Observation
  - Used by: capture_evidence, verify_condition
  - Latency: ~5s
```

## SpatialAwarenessActor

Background thread that polls sensors at ~1-2 Hz and maintains an
in-memory `LocalScene` snapshot. No SQLite, no disk I/O — pure
ephemeral state updated at sensor rate.

```
┌─────────────────────────────────────────────────────────┐
│  SpatialAwarenessActor (background thread)              │
│                                                         │
│  Polls at ~1-2 Hz:                                      │
│  ├─ frontleft_fisheye_image + frontright_fisheye_image  │
│  ├─ frontleft_depth_in_visual_frame                     │
│  ├─ frontright_depth_in_visual_frame                    │
│  └─ RobotStateClient (odom pose, heading)               │
│                                                         │
│  Maintains LocalScene:                                  │
│  ├─ obstacles by quadrant (front/left/right/back)       │
│  ├─ nearest obstacle distance + bearing                 │
│  ├─ clearest path bearing + distance                    │
│  ├─ robot pose (x, y, yaw, cardinal heading)            │
│  └─ scene_description (VLM, updated every ~10s)         │
│                                                         │
│  Feeds:                                                 │
│  ├─ Agent prompt injection (every turn)                 │
│  ├─ move_robot precondition (collision avoidance)       │
│  └─ Viewer UI (camera panels + depth overlay)           │
└─────────────────────────────────────────────────────────┘
```

## Data Model

```python
@dataclass
class QuadrantDepth:
    """Obstacle summary for one direction quadrant."""
    min_mm: int       # nearest obstacle
    mean_mm: int      # average depth
    max_mm: int       # farthest reading
    coverage: float   # fraction of pixels with valid depth

@dataclass
class LocalScene:
    """Lightweight spatial snapshot — updated at ~1-2 Hz."""
    timestamp: float

    # Depth by quadrant (derived from front-left + front-right depth)
    front: QuadrantDepth      # 0° ± 45°
    left: QuadrantDepth       # 90° ± 45°
    right: QuadrantDepth      # 270° ± 45°
    back: QuadrantDepth       # 180° ± 45° (from rear depth if available)

    # Nearest obstacle in any direction
    nearest_obstacle_m: float
    nearest_obstacle_bearing: float

    # Open path analysis
    clearest_path_bearing: float
    clearest_path_distance: float

    # Robot pose (odom frame)
    x: float
    y: float
    yaw: float
    heading_cardinal: str     # N, NE, E, SE, S, SW, W, NW

    # Lightweight VLM description (front cameras only, ~10s refresh)
    scene_description: str
    description_age_s: float

    # Raw front camera images (for viewer, not persisted)
    front_left_b64: str | None
    front_right_b64: str | None
```

## Agent Prompt Injection

The `LocalScene` is formatted as a compact text block and prepended
to every agent prompt automatically by the REPL:

```
[Scene: front clear 3.2m | left wall 0.8m | right open 5m+ | back clear 2.1m
 Pose: (1.2, -0.4) heading 15° NNE | nearest obstacle 0.8m at 90° left
 View: Workshop area, desk with monitor ~1.5m ahead-right, clear path forward]

operator: "move toward the desk"
```

The agent sees this context before every instruction and can reason
about relative positions without calling any tools.

## move_robot Precondition Check

The `move_robot` handler checks the `LocalScene` before executing:

- If moving forward and `front.min_mm < 300`: refuse, return blocked
- If moving backward and `back.min_mm < 300`: refuse, return blocked
- If moving left and `left.min_mm < 300`: refuse, return blocked
- If moving right and `right.min_mm < 300`: refuse, return blocked

This prevents the agent from driving into walls even if it
misinterprets a relative instruction.

## VLM Description Strategy

- Uses front-left + front-right cameras only (2 images)
- Nova Lite with a minimal prompt: "2 sentences: obstacles and objects"
- Runs every ~10s OR when scene_hash changes significantly
- Async: VLM call runs in the actor thread, doesn't block the REPL
- Cached in `LocalScene.scene_description` with age tracking
- Stale descriptions (>30s) are marked as such in the prompt injection

## Integration Points

### Session startup
```python
actor = SpatialAwarenessActor(image_client, state_client, bedrock_client)
actor.start()
```

### REPL prompt injection
```python
def default(self, statement):
    scene = self.session["spatial_actor"].get_scene()
    prompt = f"[{scene.format_compact()}]\n\n{text}"
    self.agent(prompt)
```

### Viewer UI
The actor's front camera images and depth data feed directly into
the viewer's camera panels, replacing the need for a separate
video polling thread.

### move_robot precondition
```python
def _op(ctx):
    scene = spatial_actor.get_scene()
    if validated.v_x > 0 and scene.front.min_mm < 300:
        return StepExecutionResult.blocked(message="Obstacle 0.3m ahead")
    # ... execute movement
```

## What This Replaces

- The agent no longer needs to call `get_scene()` as a tool — context
  is always available
- `move_robot` gets built-in collision avoidance
- The viewer gets its video feed from the actor instead of a separate thread
- Relative instructions ("move toward X", "back up from the wall")
  work because the agent always knows what's around it
