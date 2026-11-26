# Vision Automation Platform — SPEC v1.0
Status: proposed / implementation planning. Baseline: e1b132f, 24 Python Core tests previously passing on NB. Target Python 3.12, Windows NB first, portable adapters.

## Architecture and responsibility
Existing opencv_custom becomes a reusable visual automation library plus agent-facing application. Core must serve ordinary Python scripts independently of LLM, CLI, MCP, session or network services.
- Platform adapters (ADB, Robot): device-specific capture and primitive actions, lifecycle and capability reporting.
- MatUtility/OpenCvService: pure image processing on NumPy arrays, no device or transport.
- PlatformService: generic high-level composition of capture, vision and action; no frame IDs, semantic refs, session, asset registry, history, JSON envelope or token optimization.
- Application layer: common CLI/MCP orchestration, frame/session store, coordinate transforms, named assets, scoped references, state waits and action receipts.
- CLI/MCP adapters: parsing, schemas, serialization, image delivery. MCP uses same application service; no duplicated orchestration.
- Existing Wails and ScriptInterface remain consumers. Dependency direction interfaces -> application -> Core; Core cannot import higher layers. No mandatory daemon.

## Core observation
Keep snapshot() and legacy Optional[np.ndarray] signature; success is uint8 HxWx3 BGR for both platforms, no implicit resize/grayscale. Failure None in legacy API, typed diagnostics available in new path. Current ADB decoder uses IMREAD_GRAYSCALE; introduce explicit color decode while preserving legacy grayscale callers. Audit algorithm consumers. Convert at matching/OCR boundaries, not at capture.
Region: integer (x1,y1,x2,y2), half-open, positive area, inside source bounds. Reject negative/inverted/empty/out-of-bounds by default; no abs() or silent clipping. Preserve OcrRegion import and constructor compatibility. Crop returns independent data; coordinates local to input. Pure MatUtility methods: crop, resize (size or scale, mutually exclusive), PNG encode/decode, save/load with Unicode paths; optional JPEG explicit quality. Validate shape/dtype/size, expose errors. PNG round trip preserves color. No device capture for transformations of existing image.
PlatformService adds snapshot_region(region), save_snapshot(path, region=None), snapshot_regions(regions) (single capture). Delegate processing to pure Core. Keep old script methods and NumPy return types; no Frame DTO or agent IDs in Core.

## Generic vision
Keep legacy find_match(source,target), MatchPattern.similar (SQDIFF distance) and get_similar() (1-distance); document distinction. Add structured result score (higher better, 0..1), half-open bbox, center, optional scale; no agent fields. Existing template and OCR paths retain grayscale behavior through explicit conversion; new match supports explicit BGR. Validate template/source sizes, channel, threshold; no-match empty/None, invalid input explicit error. Multi-match supports deterministic NMS, max_results, consistent local coordinates and score. PlatformService maps ROI to full-device coordinates and supports matching supplied image without recapture; legacy find_image returns center. Existing character/pattern OCR remains template-based; correct channel mismatch and unbounded loops, no large general OCR model. Pure compare reports changed-pixel ratio and tolerance with shape validation. Generic wait_image uses monotonic time and bounded polling. Optional cache bounded and invalidated; color/multiscale/features later after profiling. Agent waits on changes/stability belong in application.

## Generic actions
Keep legacy bool methods; derive success from process exit code, not stdout substring. Typed ADB argv, explicit serial, timeout, unavailable device, invalid input and nonzero exit distinguished; raw shell exec only legacy escape hatch, not typed agent path. No implicit global daemon restart/kill during capture/actions. Preserve official ADB installer and PATH fallback. Desktop failsafe on by default for new instances, documented explicit opt-out. Long press generic capability when supported; unsupported and Unicode limitations explicit; no silent simulated capability or ambiguous action retry.

## Packaging
Only after Core gate: installable Python package with pyproject, optional desktop deps, headless ADB imports without eagerly importing pyautogui. Compatibility wrappers for entry.py and ScriptInterface; Wails release/CI adjust as needed. No GUI redesign; no committed SDK binaries, screenshots, reports, venv. Use isolated interpreter and sys.executable in subprocess tests. Do not add Playwright/Chromium for this project.

## Agent application and CLI (separate layer)
Proposed executable vision. Workspace-local persisted bounded state across invocations; explicit device selection. Frame record: opaque ID, device/display, timestamp, source dimensions, image path, parent, transform to source coordinates. Compose crop offsets and actual resize ratios, document pixel rounding and bounds. Path-safe IDs, atomic writes, bounded TTL cleanup never deletes registered assets.
Commands:
- vision devices --json
- vision snapshot --device SERIAL [--region X1,Y1,X2,Y2] [--out PATH] [--json]
- vision crop --frame ID --region X1,Y1,X2,Y2 [--out PATH] [--json]
- vision resize --frame ID --scale NUMBER [--json]
- vision assets register --name NAME --frame ID [--region ...]
- vision assets list --json
- vision find --frame ID --target NAME [--all] [--threshold FLOAT] --json
- vision click --device SERIAL --frame ID --point X,Y
- vision click --device SERIAL --ref REF
- vision swipe --device SERIAL --from X,Y --to X,Y
- vision type --device SERIAL --text TEXT
- vision key --device SERIAL --key KEY
- vision wait --device SERIAL --changed|--stable|--image NAME [--region ...] --timeout SECONDS
- vision capabilities --json

JSON stdout only, diagnostics stderr. Result: ok, command, device, result or error(code,message,retryable), artifact metadata. Exit 0 success, 2 usage, 3 operation failure, 4 timeout. No-match is successful query with empty matches. Artifact path/metadata, not base64 by default. References tie to frame/device/bbox; reject stale/mismatched references, check resolution/rotation where available. Age does not prove unchanged screen; explicit re-observe/re-match, no automatic action retries. Map ROI/resize-local points back to device; separate execution status from visual verification.

## MCP/Queqiao
Discover actual NB extension/transport contract before implementation. MCP uses same application methods, typed schemas, returns actual image content (PNG/JPEG MIME and bytes or supported equivalent), not just paths or base64 text. Include metadata and transform. Verify image visible to caller through real Queqiao tool; if not supported, record evidence and retain CLI export. Explicit device/workspace scopes and bounded artifacts.

## Non-goals / gates
No game-specific workflow, agent planner, OCR model download, arbitrary shell MCP, GUI redesign, screen streaming or further Git history rewriting. Baseline plus new tests; real NB read-only screenshot and crop first; verify serial 127.0.0.1:16480 only, do not touch other devices, accounts, desktop inputs or restart daemon. Mutating E2E uses controlled test screen with scoped action. Separate real/mocked evidence; see ACCEPTANCE.md and TICKETS.json.
