"""SQLite schema creation helpers."""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence

SCHEMA_STATEMENTS: tuple[str, ...] = (
    "PRAGMA foreign_keys = ON;",
    """
    CREATE TABLE IF NOT EXISTS places (
        place_id TEXT PRIMARY KEY,
        canonical_name TEXT NOT NULL,
        zone TEXT,
        tags_json TEXT NOT NULL DEFAULT '[]',
        active INTEGER NOT NULL DEFAULT 1,
        explicit_familiarity_score REAL,
        explicit_familiarity_band TEXT,
        last_visited_at TEXT,
        last_observed_at TEXT,
        notes TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        CHECK (active IN (0, 1))
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS place_aliases (
        alias_id TEXT PRIMARY KEY,
        place_id TEXT NOT NULL,
        alias TEXT NOT NULL,
        alias_type TEXT NOT NULL,
        confidence_hint REAL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (place_id) REFERENCES places(place_id) ON DELETE CASCADE
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS graph_refs (
        graph_ref_id TEXT PRIMARY KEY,
        place_id TEXT NOT NULL,
        graph_id TEXT,
        waypoint_id TEXT,
        waypoint_snapshot_id TEXT,
        anchor_hint TEXT,
        route_policy TEXT,
        relocalization_hint_json TEXT NOT NULL DEFAULT '{}',
        active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        CHECK (active IN (0, 1)),
        FOREIGN KEY (place_id) REFERENCES places(place_id) ON DELETE CASCADE
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS assets (
        asset_id TEXT PRIMARY KEY,
        place_id TEXT NOT NULL,
        canonical_name TEXT NOT NULL,
        asset_type TEXT NOT NULL,
        tags_json TEXT NOT NULL DEFAULT '[]',
        status_hint TEXT,
        last_observed_at TEXT,
        notes TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (place_id) REFERENCES places(place_id) ON DELETE CASCADE
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS asset_aliases (
        alias_id TEXT PRIMARY KEY,
        asset_id TEXT NOT NULL,
        alias TEXT NOT NULL,
        alias_type TEXT NOT NULL,
        confidence_hint REAL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (asset_id) REFERENCES assets(asset_id) ON DELETE CASCADE
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS approval_profiles (
        approval_profile_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        requires_navigation_approval INTEGER NOT NULL DEFAULT 0,
        requires_inspection_approval INTEGER NOT NULL DEFAULT 0,
        requires_retry_approval INTEGER NOT NULL DEFAULT 0,
        notes TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        CHECK (requires_navigation_approval IN (0, 1)),
        CHECK (requires_inspection_approval IN (0, 1)),
        CHECK (requires_retry_approval IN (0, 1))
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS inspection_profiles (
        profile_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        description TEXT,
        required_evidence_json TEXT NOT NULL,
        conditions_json TEXT NOT NULL,
        capture_plan_json TEXT NOT NULL,
        approval_profile_id TEXT,
        timeout_s INTEGER,
        retry_limit INTEGER,
        active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        CHECK (active IN (0, 1)),
        FOREIGN KEY (approval_profile_id) REFERENCES approval_profiles(approval_profile_id)
            ON DELETE SET NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS tasks (
        task_id TEXT PRIMARY KEY,
        instruction TEXT NOT NULL,
        operator_session_id TEXT,
        resolved_target_type TEXT,
        resolved_target_id TEXT,
        resolution_mode TEXT,
        resolution_confidence REAL,
        inspection_profile_id TEXT,
        status TEXT NOT NULL,
        outcome_code TEXT,
        created_at TEXT NOT NULL,
        started_at TEXT,
        ended_at TEXT,
        result_summary TEXT,
        FOREIGN KEY (inspection_profile_id) REFERENCES inspection_profiles(profile_id)
            ON DELETE SET NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS task_steps (
        step_id TEXT PRIMARY KEY,
        task_id TEXT NOT NULL,
        sequence_no INTEGER NOT NULL,
        tool_name TEXT NOT NULL,
        step_state TEXT NOT NULL,
        inputs_json TEXT NOT NULL,
        outputs_json TEXT,
        error_code TEXT,
        retry_count INTEGER NOT NULL DEFAULT 0,
        started_at TEXT NOT NULL,
        ended_at TEXT,
        CHECK (retry_count >= 0),
        FOREIGN KEY (task_id) REFERENCES tasks(task_id) ON DELETE CASCADE
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS observations (
        observation_id TEXT PRIMARY KEY,
        task_id TEXT NOT NULL,
        place_id TEXT,
        asset_id TEXT,
        observation_kind TEXT NOT NULL,
        source TEXT NOT NULL,
        artifact_uri TEXT,
        summary TEXT,
        structured_data_json TEXT NOT NULL DEFAULT '{}',
        confidence REAL,
        captured_at TEXT NOT NULL,
        FOREIGN KEY (task_id) REFERENCES tasks(task_id) ON DELETE CASCADE,
        FOREIGN KEY (place_id) REFERENCES places(place_id) ON DELETE SET NULL,
        FOREIGN KEY (asset_id) REFERENCES assets(asset_id) ON DELETE SET NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS condition_results (
        condition_result_id TEXT PRIMARY KEY,
        task_id TEXT NOT NULL,
        target_type TEXT NOT NULL,
        target_id TEXT NOT NULL,
        condition_id TEXT NOT NULL,
        result TEXT NOT NULL,
        confidence REAL,
        evidence_ids_json TEXT NOT NULL DEFAULT '[]',
        rationale TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY (task_id) REFERENCES tasks(task_id) ON DELETE CASCADE
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS familiarity_factors (
        place_id TEXT PRIMARY KEY,
        visit_count INTEGER NOT NULL DEFAULT 0,
        successful_localizations INTEGER NOT NULL DEFAULT 0,
        failed_localizations INTEGER NOT NULL DEFAULT 0,
        last_successful_localization_at TEXT,
        observation_freshness_s INTEGER,
        alias_resolution_confidence REAL,
        view_coverage_score REAL,
        updated_at TEXT NOT NULL,
        CHECK (visit_count >= 0),
        CHECK (successful_localizations >= 0),
        CHECK (failed_localizations >= 0),
        FOREIGN KEY (place_id) REFERENCES places(place_id) ON DELETE CASCADE
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS operator_events (
        operator_event_id TEXT PRIMARY KEY,
        task_id TEXT,
        event_type TEXT NOT NULL,
        operator_id TEXT,
        source TEXT NOT NULL,
        details_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL,
        FOREIGN KEY (task_id) REFERENCES tasks(task_id) ON DELETE CASCADE
    );
    """,
)

INDEX_STATEMENTS: tuple[str, ...] = (
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_place_aliases_alias_norm "
    "ON place_aliases (lower(alias));",
    "CREATE INDEX IF NOT EXISTS idx_place_aliases_place_id ON place_aliases (place_id);",
    "CREATE INDEX IF NOT EXISTS idx_graph_refs_place_active ON graph_refs (place_id, active);",
    "CREATE INDEX IF NOT EXISTS idx_assets_place_id ON assets (place_id);",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_asset_aliases_alias_norm "
    "ON asset_aliases (lower(alias));",
    "CREATE INDEX IF NOT EXISTS idx_asset_aliases_asset_id ON asset_aliases (asset_id);",
    "CREATE INDEX IF NOT EXISTS idx_tasks_status_created ON tasks (status, created_at DESC);",
    "CREATE INDEX IF NOT EXISTS idx_tasks_target "
    "ON tasks (resolved_target_type, resolved_target_id);",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_task_steps_task_sequence "
    "ON task_steps (task_id, sequence_no);",
    "CREATE INDEX IF NOT EXISTS idx_task_steps_task_started "
    "ON task_steps (task_id, started_at DESC);",
    "CREATE INDEX IF NOT EXISTS idx_observations_task_captured "
    "ON observations (task_id, captured_at DESC);",
    "CREATE INDEX IF NOT EXISTS idx_observations_place_captured "
    "ON observations (place_id, captured_at DESC);",
    "CREATE INDEX IF NOT EXISTS idx_observations_asset_captured "
    "ON observations (asset_id, captured_at DESC);",
    "CREATE INDEX IF NOT EXISTS idx_condition_results_task_created "
    "ON condition_results (task_id, created_at DESC);",
    "CREATE INDEX IF NOT EXISTS idx_operator_events_task_created "
    "ON operator_events (task_id, created_at DESC);",
    "CREATE INDEX IF NOT EXISTS idx_operator_events_type_created "
    "ON operator_events (event_type, created_at DESC);",
)


def create_schema(connection: sqlite3.Connection) -> None:
    """Create the full MVP schema on an existing SQLite connection."""
    connection.execute("PRAGMA foreign_keys = ON;")
    with connection:
        for statement in SCHEMA_STATEMENTS:
            connection.execute(statement)
        for statement in INDEX_STATEMENTS:
            connection.execute(statement)


def create_schema_at_path(path: str) -> sqlite3.Connection:
    """Open a SQLite database, initialize schema, and return the connection."""
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    create_schema(connection)
    return connection


def schema_statements() -> Sequence[str]:
    """Return ordered DDL statements for tests or introspection."""
    return (*SCHEMA_STATEMENTS, *INDEX_STATEMENTS)
