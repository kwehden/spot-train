# Control-Path Separation

## Control path (latency-sensitive)

The control path carries every request from the agent through to a
persisted state change:

    tool handler → supervisor runner → adapter → memory write

Each hop is synchronous and on the calling thread. Latency here
directly affects task throughput and operator responsiveness.

## Observer path (not latency-sensitive)

The observer path captures telemetry that is useful for debugging,
profiling, and UI refresh but must never block the control path:

- **Logging** – structured log lines written to stderr via stdlib
  `logging`. The `_CorrelationFormatter` injects `task_id` /
  `step_id` from `contextvars` so every line is traceable.
- **Span collection** – `SpanCollector.record()` appends a `Span`
  dataclass to an in-memory list. No I/O.
- **Ridealong UI** – polls on its own refresh interval; never called
  from the control path.

## Current separation

Logging and span recording are synchronous but intentionally
lightweight (list append / stderr write). Neither performs blocking
network or disk I/O beyond the OS write buffer. The ridealong UI
refreshes independently on a timer, so a slow render cannot stall
task execution.

## Future considerations

If observer-path work grows (e.g. shipping spans to an OTLP
collector, writing structured logs to a file, or streaming events
over a socket), move emission to:

1. An async background task (if the process already runs an event
   loop), or
2. A dedicated daemon thread with a bounded queue.

Either approach keeps the control path free of observer-induced
latency.
