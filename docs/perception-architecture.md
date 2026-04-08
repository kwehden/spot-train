# Perception Architecture Overview

## Layer Diagram

```
┌─────────────────────────────────────────────────────────────┐
│  Strands Agent (Claude Sonnet 4 via Bedrock)                │
│  Natural language instructions from operator                │
│                                                             │
│  Calls: capture_evidence() / verify_condition()             │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  agent/tools.py — @tool wrappers                            │
│  Sets active task context, delegates to handler             │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  tools/handlers.py — ToolHandlerService                     │
│  Validates request, builds supervisor step, calls runner    │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  supervisor/runner.py — SupervisorRunner                    │
│  Owns task lifecycle, persists steps + observations,        │
│  applies retry/timeout/recovery/inconclusive policies       │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  adapters/perception.py — RealPerceptionAdapter             │
│                                                             │
│  Layer 1: SENSOR CAPTURE (Spot SDK)                         │
│  ├─ ImageClient.get_image_from_sources()                    │
│  ├─ All 5 cameras: frontleft, frontright, left, right, back │
│  ├─ Fisheye (JPEG-compressed greyscale) + Depth (U16 mm)   │
│  ├─ Intrinsics (focal length, principal point) per camera   │
│  └─ Frame transforms (camera → head → body → odom)         │
│                                                             │
│  Layer 2: POINT CLOUD (perception/pointcloud.py)            │
│  ├─ depth_to_points_camera_frame() — depth + intrinsics     │
│  ├─ build_transform_chain() — camera frame → body frame     │
│  ├─ transform_points() — apply rigid transform              │
│  ├─ compute_depth_stats() — min/max/mean/coverage           │
│  └─ save_ply() — write PLY files to data/artifacts/         │
│                                                             │
│  Layer 3: VLM ANALYSIS (Nova Lite via Bedrock)              │
│  ├─ Scene description with depth-aware prompts              │
│  └─ Condition verification with structured verdicts         │
└─────────────────────────────────────────────────────────────┘
```

## Data Flow: capture_evidence

```
Agent: "capture evidence at home"
  │
  ├─ tools.py: capture_evidence(place_id="plc_home", capture_kind="photo")
  │    └─ h.handle("capture_evidence", {...}, task_id="tsk_xxx")
  │
  ├─ handlers.py: _run_side_effect_tool()
  │    └─ runner.run_task(tsk_xxx, [SupervisorStep(operation=...)])
  │         └─ step operation calls perception_adapter.capture_evidence()
  │
  ├─ RealPerceptionAdapter.capture_evidence():
  │    ├─ _capture_all_cameras() → 10 SDK image requests
  │    │    ├─ Sort: fisheye first (intrinsics), then depth
  │    │    ├─ Per fisheye: check JPEG magic → encode → base64
  │    │    ├─ Per depth: decode U16 → depth_stats → point cloud → PLY
  │    │    └─ Returns: {camera: {image_b64, depth, depth_stats, pointcloud_path}}
  │    │
  │    ├─ _depth_context_summary() → text for VLM prompt
  │    │    "frontleft: nearest=350mm, farthest=13000mm, mean=2819mm, 7.4%"
  │    │
  │    ├─ _vlm_analyze() → Bedrock converse() with Nova Lite
  │    │    Input: 5 JPEG images + depth context + capture prompt
  │    │    Output: scene description text
  │    │
  │    └─ Returns CapturedEvidence:
  │         observation_id, summary, confidence, artifact_uri,
  │         structured_data_json: {cameras: {per-camera metadata}, vlm_model}
  │
  ├─ handlers.py: persists Observation to repository
  │
  └─ Agent receives: {status: "success", data: {summary, evidence_ids, ...}}
```

## Data Flow: verify_condition

```
Agent: "is the equipment powered on at the optics bench?"
  │
  ├─ Same path through tools → handler → supervisor → adapter
  │
  ├─ RealPerceptionAdapter.verify_condition():
  │    ├─ _capture_all_cameras() → fresh images + depth
  │    ├─ _vlm_analyze() with structured prompt:
  │    │    "VERDICT: TRUE|FALSE|INCONCLUSIVE"
  │    │    "CONFIDENCE: 0.0-1.0"
  │    │    "RATIONALE: explanation"
  │    ├─ Parses response → ConditionVerdict enum + confidence
  │    └─ Returns ConditionAnalysisResult
  │
  ├─ handlers.py: persists ConditionResult to repository
  │
  └─ Agent receives: {status: "success", data: {result, confidence, rationale}}
```

## Camera Configuration

All 5 Spot stereo camera pairs, each with fisheye + aligned depth:

| Camera | SDK Source | Rotation (°CCW) | Body-frame Coverage |
|--------|-----------|-----------------|---------------------|
| Front-left | frontleft_fisheye_image | -78 | Forward-left, ~315°-45° |
| Front-right | frontright_fisheye_image | -102 | Forward-right, ~315°-45° |
| Left | left_fisheye_image | 0 | Left side, ~225°-315° |
| Right | right_fisheye_image | 180 | Right side, ~45°-135° |
| Back | back_fisheye_image | 0 | Rear, ~135°-225° |

Each camera provides:
- Fisheye image (480×640, JPEG-compressed greyscale reported as PIXEL_FORMAT_GREYSCALE_U8)
- Depth in visual frame (480×640, U16 millimeters, raw)
- Pinhole intrinsics (focal length, principal point)
- Frame transforms via transforms_snapshot (camera → head → body → odom)

## Point Cloud Pipeline

Per camera, per capture:

1. Decode depth U16 array (480×640, values in millimeters)
2. Filter: discard pixels < 50mm or > 10000mm
3. Project to 3D using pinhole intrinsics: `x = (u - cx) * z / fx`
4. Transform from camera optical frame to body frame using the frame tree
5. Compute depth statistics (min/max/mean distance, valid pixel coverage)
6. Save as PLY file to `data/artifacts/<task_id>/<camera>_cloud.ply`

The point cloud and depth stats are stored independently of the VLM analysis
and are available for future spatial reasoning (change detection, obstacle
mapping, spatial queries) even if the VLM is unavailable.

## Image Format Handling

Spot cameras report `PIXEL_FORMAT_GREYSCALE_U8` but deliver JPEG-compressed
data. The adapter detects the actual format by checking JPEG magic bytes
(`0xFFD8`) before labeling images for the VLM:

- JPEG magic present → use directly as `format: "jpeg"`
- No magic → attempt `cv2.imdecode`, fall back to raw reshape, re-encode as JPEG
- Only verified JPEG images are sent to Bedrock Nova Lite
- Cameras that fail encoding are silently skipped

## VLM Integration

Nova Lite (`us.amazon.nova-lite-v1:0`) is used as a lightweight analysis layer:

- **capture_evidence**: receives all 5 camera images with orientation labels
  and depth context, generates a factual scene description
- **verify_condition**: receives images + a condition to evaluate, returns
  a structured VERDICT/CONFIDENCE/RATIONALE response

The VLM prompt includes per-camera depth statistics so the model can
reference distances in its descriptions (e.g., "desk ~1.2m at front-left").

## Stored Artifacts Per Capture

| Artifact | Path | Format |
|----------|------|--------|
| Fisheye image | `data/artifacts/<task_id>/<camera>_rgb.bin` | Raw SDK bytes |
| Depth image | `data/artifacts/<task_id>/<camera>_depth.bin` | U16 raw |
| Point cloud | `data/artifacts/<task_id>/<camera>_cloud.ply` | ASCII PLY |
| Observation record | SQLite `observations` table | Pydantic model |
| Condition result | SQLite `condition_results` table | Pydantic model |

Per-camera metadata in `structured_data_json`:
- Image path, resolution, intrinsics
- Depth path, depth stats (min/max/mean/coverage)
- Point cloud path, point count
- VLM model ID and summary text

## Design Principle

Spot's onboard sensors are the source of truth. The VLM is an analysis
layer — it interprets what the cameras already captured, it does not
drive the robot's actions. All sensor data is persisted before VLM
analysis runs, so raw evidence is never lost even if the VLM fails.
