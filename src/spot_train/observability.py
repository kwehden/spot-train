"""Timing instrumentation and structured logging with correlation."""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterator

# ---------------------------------------------------------------------------
# Correlation context (T-020)
# ---------------------------------------------------------------------------

current_task_id: ContextVar[str | None] = ContextVar("current_task_id", default=None)
current_step_id: ContextVar[str | None] = ContextVar("current_step_id", default=None)


@contextmanager
def correlation_context(
    task_id: str | None = None,
    step_id: str | None = None,
) -> Iterator[None]:
    """Set correlation vars for the duration of a block."""
    t_token = current_task_id.set(task_id)
    s_token = current_step_id.set(step_id)
    try:
        yield
    finally:
        current_task_id.reset(t_token)
        current_step_id.reset(s_token)


# ---------------------------------------------------------------------------
# Structured logging (T-020)
# ---------------------------------------------------------------------------


class _CorrelationFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat()
        tid = current_task_id.get(None) or "-"
        sid = current_step_id.get(None) or "-"
        msg = record.getMessage()
        return f"{ts} [{record.levelname}] {record.name} | task_id={tid} step_id={sid} | {msg}"


def configure_logging(level: int = logging.INFO, *, console: bool = True) -> None:
    """Attach the correlation formatter to the ``spot_train`` logger."""
    logger = logging.getLogger("spot_train")
    logger.setLevel(level)
    if not logger.handlers and console:
        handler = logging.StreamHandler()
        handler.setFormatter(_CorrelationFormatter())
        logger.addHandler(handler)
    elif not console:
        # Suppress console output — traces will go to the viewer
        logger.addHandler(logging.NullHandler())


def get_logger(name: str) -> logging.Logger:
    """Return a logger under the ``spot_train`` namespace."""
    return logging.getLogger(f"spot_train.{name}")


# ---------------------------------------------------------------------------
# Timing spans (T-019)
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class Span:
    name: str
    category: str  # 'tool', 'supervisor', 'adapter', 'model'
    task_id: str | None
    started_at: float  # time.perf_counter()
    ended_at: float | None = None
    duration_ms: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class SpanCollector:
    """Append-only span store for testing / dry-run inspection."""

    def __init__(self, maxlen: int | None = 10_000) -> None:
        self.spans: list[Span] = []
        self.maxlen = maxlen

    def record(self, span: Span) -> None:
        self.spans.append(span)
        if self.maxlen is not None and len(self.spans) > self.maxlen:
            self.spans = self.spans[-self.maxlen :]

    def spans_for_task(self, task_id: str) -> list[Span]:
        return [s for s in self.spans if s.task_id == task_id]

    def summary(self, task_id: str | None = None) -> dict[str, Any]:
        subset = self.spans_for_task(task_id) if task_id else self.spans
        agg: dict[str, dict[str, float | int]] = defaultdict(
            lambda: {"total_ms": 0.0, "count": 0},
        )
        for s in subset:
            bucket = agg[s.category]
            bucket["total_ms"] += s.duration_ms or 0.0
            bucket["count"] += 1
        return dict(agg)


_default_collector = SpanCollector()


class SpanTimer:
    """Context manager that captures wall-clock duration into a :class:`Span`."""

    def __init__(
        self,
        name: str,
        category: str,
        *,
        task_id: str | None = None,
        collector: SpanCollector | None = None,
        **metadata: Any,
    ) -> None:
        self._collector = collector or _default_collector
        self._span = Span(
            name=name,
            category=category,
            task_id=task_id,
            started_at=time.perf_counter(),
            metadata=metadata,
        )

    def __enter__(self) -> Span:
        return self._span

    def __exit__(self, *exc: object) -> None:
        self._span.ended_at = time.perf_counter()
        self._span.duration_ms = (self._span.ended_at - self._span.started_at) * 1000.0
        self._collector.record(self._span)


def timed(
    name: str,
    category: str,
    *,
    task_id: str | None = None,
    collector: SpanCollector | None = None,
    **metadata: Any,
) -> SpanTimer:
    """Convenience wrapper that defaults to the module-level collector."""
    return SpanTimer(name, category, task_id=task_id, collector=collector, **metadata)
