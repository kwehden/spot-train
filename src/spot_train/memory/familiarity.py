"""Familiarity scoring and derivation helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

_LOW_THRESHOLD = 0.34
_MEDIUM_THRESHOLD = 0.67
_MAX_VISIT_COUNT = 5
_RECENCY_FULL_SCORE_WINDOW_S = 7 * 24 * 60 * 60
_FRESHNESS_FULL_SCORE_WINDOW_S = 7 * 24 * 60 * 60


@dataclass(frozen=True, slots=True)
class FamiliarityComponents:
    """Normalized component scores contributing to a derived familiarity score."""

    visit_recency: float
    localization_success_rate: float
    observation_freshness: float
    alias_resolution_confidence: float
    view_coverage: float


@dataclass(frozen=True, slots=True)
class FamiliarityAssessment:
    """Derived familiarity output suitable for caching or operator display."""

    score: float
    band: str
    components: FamiliarityComponents


def derive_familiarity(
    *,
    visit_count: int = 0,
    successful_localizations: int = 0,
    failed_localizations: int = 0,
    last_successful_localization_at: str | datetime | None = None,
    observation_freshness_s: int | None = None,
    alias_resolution_confidence: float | None = None,
    view_coverage_score: float | None = None,
    now: datetime | None = None,
) -> FamiliarityAssessment:
    """Compute a weighted familiarity score and qualitative band."""
    current_time = now or datetime.now(UTC)

    recency_score = _visit_recency_score(last_successful_localization_at, current_time)
    localization_score = _localization_success_rate(successful_localizations, failed_localizations)
    freshness_score = _freshness_score(observation_freshness_s)
    alias_score = _clamp(alias_resolution_confidence or 0.0)
    coverage_score = _clamp(view_coverage_score or 0.0)
    visits_score = min(max(visit_count, 0), _MAX_VISIT_COUNT) / _MAX_VISIT_COUNT

    score = (
        (0.20 * recency_score)
        + (0.25 * localization_score)
        + (0.20 * freshness_score)
        + (0.20 * alias_score)
        + (0.15 * ((coverage_score + visits_score) / 2.0))
    )
    score = _clamp(score)

    components = FamiliarityComponents(
        visit_recency=recency_score,
        localization_success_rate=localization_score,
        observation_freshness=freshness_score,
        alias_resolution_confidence=alias_score,
        view_coverage=coverage_score,
    )
    return FamiliarityAssessment(score=score, band=familiarity_band(score), components=components)


def derive_familiarity_from_row(
    row: dict[str, Any] | Any,
    *,
    now: datetime | None = None,
) -> FamiliarityAssessment:
    """Compute familiarity from a sqlite row, dict, or row-like object."""
    values = dict(row)
    return derive_familiarity(
        visit_count=int(values.get("visit_count") or 0),
        successful_localizations=int(values.get("successful_localizations") or 0),
        failed_localizations=int(values.get("failed_localizations") or 0),
        last_successful_localization_at=values.get("last_successful_localization_at"),
        observation_freshness_s=values.get("observation_freshness_s"),
        alias_resolution_confidence=values.get("alias_resolution_confidence"),
        view_coverage_score=values.get("view_coverage_score"),
        now=now,
    )


def familiarity_band(score: float) -> str:
    """Map a normalized familiarity score to a low/medium/high band."""
    normalized = _clamp(score)
    if normalized < _LOW_THRESHOLD:
        return "low"
    if normalized < _MEDIUM_THRESHOLD:
        return "medium"
    return "high"


def _visit_recency_score(
    last_successful_localization_at: str | datetime | None,
    now: datetime,
) -> float:
    timestamp = _coerce_datetime(last_successful_localization_at)
    if timestamp is None:
        return 0.0
    age_seconds = max((now - timestamp).total_seconds(), 0.0)
    return max(0.0, 1.0 - (age_seconds / _RECENCY_FULL_SCORE_WINDOW_S))


def _localization_success_rate(successes: int, failures: int) -> float:
    total = max(successes, 0) + max(failures, 0)
    if total == 0:
        return 0.0
    return successes / total


def _freshness_score(observation_freshness_s: int | None) -> float:
    if observation_freshness_s is None:
        return 0.0
    age_seconds = max(observation_freshness_s, 0)
    return max(0.0, 1.0 - (age_seconds / _FRESHNESS_FULL_SCORE_WINDOW_S))


def _coerce_datetime(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))
