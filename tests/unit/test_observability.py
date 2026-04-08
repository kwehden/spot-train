"""Phase 8 verification tests for observability (T-019, T-020)."""

from __future__ import annotations

from spot_train.memory.repository import WorldRepository
from spot_train.memory.schema import create_schema
from spot_train.observability import (
    Span,
    SpanCollector,
    SpanTimer,
    _default_collector,
    correlation_context,
    current_step_id,
    current_task_id,
    timed,
)
from spot_train.tools.handlers import ToolHandlerService


def test_span_timer_captures_duration() -> None:
    collector = SpanCollector()
    with SpanTimer("op", "tool", collector=collector) as span:
        _ = sum(range(100))

    assert span.ended_at is not None
    assert span.duration_ms is not None
    assert span.duration_ms > 0


def test_span_collector_records_and_queries() -> None:
    collector = SpanCollector()
    import time

    for tid, cat in [("t1", "tool"), ("t1", "supervisor"), ("t2", "tool")]:
        s = Span(name="x", category=cat, task_id=tid, started_at=time.perf_counter())
        s.ended_at = s.started_at + 0.01
        s.duration_ms = 10.0
        collector.record(s)

    assert len(collector.spans_for_task("t1")) == 2
    summary = collector.summary()
    assert summary["tool"]["count"] == 2
    assert summary["supervisor"]["count"] == 1


def test_span_collector_maxlen_trims() -> None:
    collector = SpanCollector(maxlen=2)
    import time

    for i in range(3):
        s = Span(name=f"s{i}", category="tool", task_id=None, started_at=time.perf_counter())
        s.duration_ms = 1.0
        collector.record(s)

    assert len(collector.spans) == 2
    assert collector.spans[0].name == "s1"
    assert collector.spans[1].name == "s2"


def test_timed_convenience_uses_default_collector() -> None:
    _default_collector.spans.clear()

    with timed("test_op", "tool"):
        pass

    assert len(_default_collector.spans) == 1
    assert _default_collector.spans[0].name == "test_op"
    assert _default_collector.spans[0].category == "tool"


def test_correlation_context_sets_and_resets() -> None:
    assert current_task_id.get(None) is None
    assert current_step_id.get(None) is None

    with correlation_context(task_id="t1", step_id="s1"):
        assert current_task_id.get() == "t1"
        assert current_step_id.get() == "s1"

    assert current_task_id.get(None) is None
    assert current_step_id.get(None) is None


def test_tool_handler_records_timing_spans() -> None:
    _default_collector.spans.clear()

    repo = WorldRepository.connect(initialize=False)
    create_schema(repo.connection)
    repo.seed_minimal_lab_world()
    handler = ToolHandlerService(repo)

    handler.handle("resolve_target", {"name": "optics bench"})

    tool_spans = [s for s in _default_collector.spans if s.category == "tool"]
    assert len(tool_spans) >= 1
    assert tool_spans[0].name == "resolve_target"
    repo.close()
