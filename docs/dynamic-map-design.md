# Dynamic Map Design

## Problem Statement

The current architecture treats GraphNav maps as static recordings uploaded
wholesale to the robot. This creates several failures:

1. Maps are lost on robot reboot — require manual re-upload
2. Locations can't be added, moved, or removed at runtime
3. The operator can't say "this is the new home" and have it stick
4. Relocalization fails when the robot is in an unmapped area
5. The world model (SQLite) and the navigation graph (GraphNav) are
   disconnected systems with a brittle join on waypoint_id

## Design Principle

The world model is the map authority. GraphNav is the execution substrate.

```
World DB (source of truth)
    │
    ├── Places: semantic locations with aliases
    ├── GraphRefs: waypoint bindings (mutable)
    ├── SpatialState: current robot pose, localization status
    │
    ▼
MapManager (sync layer)
    │
    ├── create_waypoint_here(name) → creates waypoint on robot + graph_ref in DB
    ├── update_location(place_id) → re-records waypoint at current position
    ├── remove_location(place_id) → deactivates graph_ref
    ├── sync_to_robot() → ensures robot graph matches world DB
    ├── sync_from_robot() → imports new waypoints from robot graph
    ├── relocalize_best_effort() → tries fiducials, then each known waypoint
    │
    ▼
GraphNav (execution substrate, eventually consistent)
```

## MapManager Interface

```python
class MapManager:
    """Manages the bidirectional sync between world DB and GraphNav."""

    def __init__(self, repository, graph_nav_client, recording_client, robot):
        ...

    def create_waypoint_here(self, name: str) -> GraphRef:
        """Record a new waypoint at the robot's current position.

        1. Calls recording_client.create_waypoint(name)
        2. Creates a Place in the world DB (if not exists)
        3. Creates a GraphRef binding the place to the new waypoint
        4. Registers the navigation binding on the adapter
        """

    def update_location(self, place_id: str) -> GraphRef:
        """Update an existing place to the robot's current position.

        1. Creates a new waypoint at current position
        2. Deactivates the old graph_ref
        3. Creates a new graph_ref with the new waypoint_id
        4. Updates the adapter binding
        """

    def remove_location(self, place_id: str) -> None:
        """Deactivate a place's navigation binding.

        Does not delete the place from the world DB — just removes
        the graph_ref so navigation won't target it.
        """

    def relocalize_best_effort(self) -> str | None:
        """Try to localize the robot using all available methods.

        Strategy (in order):
        1. Fiducials (FIDUCIAL_INIT_NEAREST) — instant if visible
        2. Each known waypoint as initial guess — try nearest first
        3. Return the waypoint_id if successful, None if all fail
        """

    def sync_to_robot(self) -> None:
        """Ensure the robot's graph matches the world DB.

        - Upload graph + snapshots if robot has no graph
        - Add new waypoints/edges that exist in DB but not on robot
        - Does NOT delete waypoints from the robot graph
        """

    def sync_from_robot(self) -> list[str]:
        """Import named waypoints from the robot graph into the world DB.

        Returns list of newly created place_ids.
        Only imports waypoints with annotations.name set.
        Skips waypoints that already have a graph_ref in the DB.
        """
```

## Agent Tools

New tools exposed to the agent:

```python
@tool
def mark_location(name: str) -> dict:
    """Mark the robot's current position as a named location.

    If the location already exists, updates it to the current position.
    If it's new, creates a new place in the world model.

    Args:
        name: Human-friendly name for this location.
    """

@tool
def forget_location(name: str) -> dict:
    """Remove a location's navigation binding.

    The place remains in the world model but can no longer be
    navigated to. Use this when a location has moved or is no longer
    relevant.

    Args:
        name: Name of the location to forget.
    """

@tool
def relocalize(place_id: str | None = None) -> dict:
    """Relocalize the robot on the map.

    Tries fiducials first, then known waypoints. If place_id is
    provided, prioritizes that location as the initial guess.
    """
```

## Operator Interaction Examples

```
operator: "this is the new break room"
agent:    → mark_location("break room")
          → creates waypoint at current position
          → creates Place + GraphRef in world DB
          → "Break room marked at current position."

operator: "the optics bench has moved, update it"
agent:    → resolve_target("optics bench")
          → mark_location("optics bench")  # updates existing
          → "Optics bench location updated to current position."

operator: "forget about the old storage room"
agent:    → forget_location("storage")
          → "Storage location removed from navigation."

operator: "where am I?"
agent:    → relocalize()
          → "Relocalized at waypoint near 'home'."
```

## Recording Integration

The MapManager wraps the GraphNav recording client for incremental
waypoint creation. It does NOT require starting/stopping a full
recording session — it uses `create_waypoint` directly when the
graph is already loaded.

For initial map creation (first time in a new environment), the
existing `record_map.py` script is still the right tool. The
MapManager handles incremental updates after that.

## Sync Strategy

### Robot boot (session start)
1. Check if robot has a graph loaded
2. If not, upload from `data/maps/lab_map/`
3. Sync graph_refs from world DB to adapter bindings
4. Attempt relocalization (fiducials → waypoints)

### Runtime (operator commands)
1. `mark_location` → create waypoint + graph_ref immediately
2. `update_location` → new waypoint + deactivate old ref
3. `forget_location` → deactivate graph_ref
4. All changes persist to world DB immediately
5. Robot graph is updated incrementally (no full re-upload)

### Session end
1. Download updated graph from robot
2. Save to `data/maps/lab_map/` (overwrites)
3. New waypoints are preserved for next session

## Migration from Current Architecture

1. `_upload_graph_if_needed` → `MapManager.sync_to_robot()`
2. `_sync_navigation_bindings` → `MapManager.sync_to_robot()` (combined)
3. `load_map.py` → `MapManager.sync_from_robot()`
4. `RealSpotAdapter.relocalize()` → `MapManager.relocalize_best_effort()`
5. Adapter keeps its binding registry but MapManager owns the updates

## Open Questions

1. Should the MapManager also handle edge creation between new waypoints
   and existing ones? The recording client can create edges, but choosing
   which waypoints to connect requires spatial reasoning.

2. Should `mark_location` require the robot to be standing and localized,
   or should it work even when not localized (creating an orphan waypoint)?

3. Should the graph be saved to disk on every change, or only on session
   end? Frequent saves protect against crashes but add I/O.
