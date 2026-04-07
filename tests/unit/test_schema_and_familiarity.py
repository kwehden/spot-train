from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

from spot_train.memory.familiarity import (
    derive_familiarity,
    derive_familiarity_from_row,
    familiarity_band,
)
from spot_train.memory.schema import create_schema, schema_statements
from spot_train.profiles.loader import load_default_profiles


def test_schema_creation_is_deterministic() -> None:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row

    create_schema(connection)
    create_schema(connection)

    tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    indexes = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index' AND name NOT LIKE 'sqlite_%'"
        )
    }

    assert "places" in tables
    assert "task_steps" in tables
    assert "operator_events" in tables
    assert "idx_place_aliases_alias_norm" in indexes
    assert "idx_task_steps_task_sequence" in indexes
    assert len(schema_statements()) >= 20


def test_familiarity_derivation_behaves_as_expected() -> None:
    now = datetime.now(UTC)

    high = derive_familiarity(
        visit_count=5,
        successful_localizations=5,
        failed_localizations=0,
        last_successful_localization_at=now - timedelta(hours=4),
        observation_freshness_s=120,
        alias_resolution_confidence=0.98,
        view_coverage_score=0.9,
        now=now,
    )
    low = derive_familiarity(
        visit_count=0,
        successful_localizations=0,
        failed_localizations=3,
        observation_freshness_s=30 * 24 * 60 * 60,
        alias_resolution_confidence=0.2,
        view_coverage_score=0.1,
        now=now,
    )
    from_row = derive_familiarity_from_row(
        {
            "visit_count": 2,
            "successful_localizations": 2,
            "failed_localizations": 1,
            "last_successful_localization_at": (now - timedelta(days=1)).isoformat(),
            "observation_freshness_s": 3600,
            "alias_resolution_confidence": 0.85,
            "view_coverage_score": 0.7,
        },
        now=now,
    )

    assert high.score > low.score
    assert high.band == "high"
    assert low.band == "low"
    assert from_row.band in {"medium", "high"}
    assert familiarity_band(0.1) == "low"
    assert familiarity_band(0.5) == "medium"
    assert familiarity_band(0.9) == "high"


def test_profile_loader_reads_default_seed_profiles() -> None:
    approval, inspection = load_default_profiles()

    assert approval.approval_profile_id == "apr_default_dry_run"
    assert approval.requires_navigation_approval is True
    assert inspection.profile_id == "ipr_lab_readiness_v1"
    assert inspection.approval_profile_id == approval.approval_profile_id
    assert inspection.capture_plan_json[0].capture_kind == "overview_image"
