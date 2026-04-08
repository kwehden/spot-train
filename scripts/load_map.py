#!/usr/bin/env python3
"""Load a recorded GraphNav map into the world repository.

Reads data/maps/lab_map/graph, creates Place + PlaceAlias + GraphRef
records for every named waypoint, and syncs navigation bindings.

Usage:
    python scripts/load_map.py
"""

from __future__ import annotations

import os

from bosdyn.api.graph_nav import map_pb2

from spot_train.memory.repository import WorldRepository
from spot_train.memory.schema import create_schema
from spot_train.models import AliasType, GraphRef, Place, PlaceAlias

MAP_DIR = os.path.join("data", "maps", "lab_map")
DB_PATH = os.environ.get("SPOT_TRAIN_DB_PATH", "data/world.sqlite")

# Skip auto-generated waypoint names like "waypoint_42" and "lab_map_0"
SKIP_PREFIXES = ("waypoint_", "lab_map_")


def main():
    graph_path = os.path.join(MAP_DIR, "graph")
    if not os.path.exists(graph_path):
        print(f"❌ No graph found at {graph_path}. Record a map first.")
        return

    graph = map_pb2.Graph()
    with open(graph_path, "rb") as f:
        graph.ParseFromString(f.read())

    named_waypoints = []
    for wp in graph.waypoints:
        name = wp.annotations.name
        if name and not any(name.startswith(p) for p in SKIP_PREFIXES):
            named_waypoints.append((wp.id, name))

    if not named_waypoints:
        print("❌ No named waypoints found in the graph.")
        return

    print(f"Found {len(named_waypoints)} named waypoints:")
    for wp_id, name in named_waypoints:
        print(f"  {name} -> {wp_id[:24]}...")

    repo = WorldRepository.connect(DB_PATH, initialize=False)
    create_schema(repo.connection)

    created = 0
    updated = 0
    for wp_id, name in named_waypoints:
        # Normalize name for alias matching
        alias_text = name.lower().strip()
        place_id = f"plc_{alias_text.replace(' ', '_')}"

        # Check if place already exists
        existing = repo.get_place(place_id)
        if existing is None:
            repo.create_place(Place(place_id=place_id, canonical_name=name))
            repo.create_place_alias(
                PlaceAlias(
                    place_id=place_id,
                    alias=alias_text,
                    alias_type=AliasType.OPERATOR_DEFINED,
                )
            )
            created += 1
        else:
            updated += 1

        # Upsert graph ref — check if this waypoint is already registered
        existing_refs = repo.list_graph_refs(place_id)
        already_has = any(r.waypoint_id == wp_id for r in existing_refs)
        if not already_has:
            repo.create_graph_ref(
                GraphRef(
                    place_id=place_id,
                    waypoint_id=wp_id,
                    anchor_hint=name,
                )
            )

    print(f"\n✅ {created} places created, {updated} existing, all graph refs synced.")
    print(f"   Database: {DB_PATH}")

    # Show final state
    print("\nPlaces with navigation bindings:")
    for place in repo.list_places():
        refs = repo.list_graph_refs(place.place_id)
        wp_ids = [r.waypoint_id[:20] + "..." for r in refs if r.waypoint_id]
        if wp_ids:
            print(f"  {place.canonical_name} [{place.place_id}] -> {', '.join(wp_ids)}")
        else:
            print(f"  {place.canonical_name} [{place.place_id}] (no waypoint)")


if __name__ == "__main__":
    main()
