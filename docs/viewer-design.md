# Spot-Train Visual Viewer Design

## Overview

Tkinter-based X11 window that provides live situational awareness during
agent REPL sessions. Runs in a background thread, does not block the REPL.

## Layout

```
┌─────────────────────────────────────────────────────────┐
│                                                         │
│   ┌──────────┐ ┌──────────┐ ┌──────────┐               │
│   │ Front-L  │ │ Front-R  │ │  Back    │               │  75%
│   │ (-78°)   │ │ (-102°)  │ │  (0°)   │               │  of
│   └──────────┘ └──────────┘ └──────────┘               │  window
│   ┌──────────┐ ┌──────────┐                             │
│   │  Left    │ │  Right   │   ← depth overlay toggle   │
│   │  (0°)   │ │  (180°)  │                             │
│   └──────────┘ └──────────┘                             │
│                                                         │
├─────────────────────────────┬───────────────────────────┤
│  VLM Descriptions (scroll)  │  Command Trace (scroll)   │  25%
│  [HH:MM:SS] scene desc...  │  [HH:MM:SS] tool call...  │  of
│  [HH:MM:SS] scene desc...  │  [HH:MM:SS] tool call...  │  window
│                             │                           │
└─────────────────────────────┴───────────────────────────┘
```

## Camera Grid (top 75%)

### 5-camera layout

All 5 Spot cameras displayed simultaneously in a 3-over-2 arrangement:
- Row 1: front-left, front-right, back (3 panels)
- Row 2: left, right (2 panels, centered or left-aligned)

Each panel shows:
- Camera label + orientation badge
- Live fisheye image, rotated to correct orientation
- Optional depth overlay (toggled with button or 'd' key)

### Orientation corrections

See the camera configuration table in
[docs/perception-architecture.md](perception-architecture.md#camera-configuration)
for rotation angles and body-frame coverage per camera.

Images are rotated before display so "up" in the panel corresponds
to "away from the robot body" for that camera's perspective.

### Depth overlay

When enabled, the matching `*_depth_in_visual_frame` source is
colorized (blue=close, red=far) and alpha-composited onto the
fisheye image. Depth is U16 millimeters, clamped to 0-10m range.

### Resizing

- Panels resize proportionally with the window
- Images are scaled with `Image.LANCZOS` to fill each panel
- Aspect ratio preserved (letterboxed if needed)
- `<Configure>` events debounced to avoid excessive redraws

## Bottom Bar (25%)

Split into two scrollable text panes with a draggable sash:

### Left pane: VLM Descriptions

Rolling log of scene descriptions from `RealPerceptionAdapter` and
the auto-description callback. Format:

```
[18:42:15] Front-left: desk with monitor, ~1.2m. Right: corridor clear to ~4m.
[18:42:45] Front-left: person walking, ~2m at 15° left. Back: wall ~0.8m.
```

Fed from:
- `RealPerceptionAdapter.capture_evidence()` VLM summaries
- Auto-description callback (configurable interval, default 5s)
- `_depth_context_summary()` depth stats

### Right pane: Command Trace

Rolling log of supervisor events, tool calls, and state transitions.
Replaces the current behavior of leaking tool traces into the REPL
stdout. Format:

```
[18:42:10] resolve_target("office 1") -> success (0.4ms)
[18:42:12] navigate_to_place(plc_office_1) -> executing
[18:42:12] task tsk_abc123 -> executing
[18:42:25] task tsk_abc123 -> completed
```

Fed from:
- `SpanCollector` timing spans
- Supervisor runner `_log.info()` calls (redirect to viewer)
- Tool handler dispatch events

## Video Feed

Background thread polls `ImageClient.get_image_from_sources()` at
~2 fps for all 10 sources (5 fisheye + 5 depth). Images are:
1. Decoded (JPEG-compressed greyscale → RGB)
2. Rotated per camera orientation table
3. Depth colorized and composited if overlay is on
4. Scaled to panel size
5. Displayed via `ImageTk.PhotoImage`

## History Navigation

- ◀/▶ buttons or left/right arrow keys to browse captured snapshots
- "● LIVE" button returns to live video feed
- History mode freezes the video feed display but keeps capturing
- Bottom panes scroll to match the history position

## Integration Points

### From session.py

```python
from spot_train.ui.viewer import SpotTrainViewer

viewer = SpotTrainViewer(
    image_client=spot._robot.ensure_client(ImageClient.default_service_name),
    span_collector=observability._default_collector,
    artifact_dir="data/artifacts",
)
viewer.start()
# ... on shutdown:
viewer.stop()
```

### From observability.py

The viewer subscribes to the `SpanCollector` for command trace entries.
Either via a callback registered on the collector, or by polling
`collector.spans[-N:]` on a timer.

### From perception adapter

When `capture_evidence()` or `verify_condition()` runs, the VLM
summary is pushed to the viewer's description pane.

## Dependencies

- `tkinter` (stdlib, requires `python3-tk` on Debian/Ubuntu)
- `Pillow` (already in venv for image processing)
- `numpy` (already in perception extra)
- No additional pip packages required

## Files

- `src/spot_train/ui/viewer.py` — `SpotTrainViewer` class
- Update `src/spot_train/agent/session.py` — wire viewer into robot session
- Update `src/spot_train/agent/repl.py` — redirect tool traces to viewer

## Open Questions

- Should the viewer also show the ridealong task status (task_id,
  supervisor state, approval pending)? Could add a thin status bar
  between the camera grid and the bottom panes.
- Should auto-description use a separate Nova Lite call, or reuse
  the perception adapter's capture pipeline?
- Should the viewer save video frames to disk for post-run review,
  or only save on explicit capture_evidence calls?
