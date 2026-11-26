# Verified transport and CLI reference

Validated on NB 2026-11-26, repo main at f212447 before this skill change. Tool names and schemas can evolve: discover actual tools each session.

## ChatGPT / Queqiao NB

Use the installed Queqiao NB extension tool, workspaceId=develop. Discover via:
- extension(operation="list")
- extension(operation="describe", extensionId="dev.queqiao.mcp", capability="mcp")
- extension(operation="call", extensionId="dev.queqiao.mcp", capability="mcp", arguments={"workspaceId":"develop","operation":"search","query":"vision","limit":30})

Invoke:
```json
{
  "workspaceId":"develop",
  "operation":"call",
  "extensionId":"dev.queqiao.mcp",
  "capability":"mcp",
  "arguments":{
    "workspaceId":"develop",
    "operation":"call",
    "server":"vision-platform",
    "tool":"vision_snapshot",
    "arguments":{"device":"127.0.0.1:16480"}
  }
}
```

The current MCP proxy wraps downstream content as JSON: result.result.content entries with type=image (mimeType/data) and type=text (JSON metadata). Decode/display the actual image through a supported image viewer, not by printing the base64. Alternatively use dev.queqiao.media/image_read, with workspace-relative path (e.g. opencv_custom_recovery/clean-working/.vision_store/frames/<actual-id>.png); the native response has image content. The extension call schema must be discovered, and the path must come from actual metadata; never guess it. Image blocks in tool responses may be wrapped differently by clients. Report transport limitations rather than treating a path as an observed image.

| Tool | Arguments (required unless shown optional) |
|---|---|
| vision_devices | {} |
| vision_capabilities | device (optional; use explicit target) |
| vision_snapshot | device, optional region |
| vision_crop | frame_id, region |
| vision_resize | frame_id, scale |
| vision_assets_register | name, frame_id, optional region |
| vision_assets_list | {} |
| vision_find | frame_id, target, optional all, threshold |
| vision_click | device and ref OR frame_id+point, optional max_age_seconds |
| vision_swipe | device, from_point, to_point, optional duration_ms |
| vision_type | device, text |
| vision_key | device, key (Android back: "4") |
| vision_wait | device, mode (changed/stable/image), optional baseline_frame_id (changed), target (required for image), region, timeout, poll_interval, threshold |

Regions are integer [x1,y1,x2,y2] half-open in the given image. Frame IDs and refs are opaque. Frame metadata has width/height, source dimensions, timestamp, transform and optional rotation. Crop and resize coordinates are frame-local; reference and frame-point clicks map back to original device. Use matching source dimensions and current orientation; the current implementation does not guarantee live rotation validation or semantic freshness, so observe again. Actions return status=executed, verified=false; verify separately. Error metadata is nested in content text and isError must be checked. A no-match query is normal, count=0.

MCP's current vision_find schema lacks CLI color-mode/max-results; its vision_wait schema exposes fewer tuning options than CLI. Do not invent unsupported fields. NB ADB advertises unicode_text=false; use only supported text entry. Long press capability exists in Core, but this MCP/CLI surface has no dedicated long-press command.

## Local CLI on NB

Current tested Python installation:
C:\Users\jeffh\Downloads\develop\opencv_custom_recovery\acceptance-20261126\fresh-venv\Scripts\vision.exe
Repository:
C:\Users\jeffh\Downloads\develop\opencv_custom_recovery\clean-working
ADB tools are under the repository's ignored platform-tools directory; use the installed official SDK or set PATH/ANDROID_HOME appropriately. No need to install again if the current tools work.

Examples (replace placeholders with actual IDs and values):
```powershell
vision --store-dir <workspace-store> devices --json
vision --store-dir <workspace-store> snapshot --device <serial> --json
vision --store-dir <workspace-store> crop --frame <id> --region 10,20,110,100 --json
vision --store-dir <workspace-store> resize --frame <id> --scale 0.5 --json
vision --store-dir <workspace-store> assets register --name <name> --frame <crop-id> --json
vision --store-dir <workspace-store> find --frame <fresh-id> --target <name> --all --threshold 0.98 --json
vision --store-dir <workspace-store> click --device <serial> --ref <ref-id> --max-age 15 --json
vision --store-dir <workspace-store> wait --device <serial> --changed --baseline <pre-action-id> --timeout 5 --interval 0.3 --json
vision --store-dir <workspace-store> wait --device <serial> --image <postcondition-asset> --timeout 5 --json
```
Run --help for each command. CLI exit 0 success, 2 usage, 3 operation error, 4 timeout. JSON stdout, diagnostics stderr. Image artifact path must be read using a real image tool if visual reasoning is needed. Do not use raw ADB for normal typed Vision actions. ADB can be used for verified device setup/foreground activity inspection or explicit app launch where the current Vision API has no equivalent.

## Recorder Phase 2

Discover vision_record_* via the MCP adapter. Start with vision_record_start {name,goal,device}; use returned session_id with snapshot/crop/resize/assets_register/find/click/swipe/type/key/wait. For lifecycle: vision_record_status/pause/resume/stop {session_id}; vision_record_list {limit?,after?}. For inspection: vision_record_summary/inspect, vision_record_events {session_id,limit?,after?,operation?,status?}, vision_record_event {session_id,event_id}, vision_record_history, vision_record_annotations, vision_record_latest_checkpoint, vision_record_resume_context {session_id,limit?}. Annotation/checkpoint: {session_id,event_id,annotation:{state,verification,next_step,...}}. No automatic semantic success. Use the same store dir across processes.

CLI examples (global --session precedes ordinary commands):
    vision --store-dir <store> record start --name exploration --goal "Inspect two pages" --device <serial>
    vision --store-dir <store> --session <id> snapshot --device <serial> --json
    vision --store-dir <store> record events --session <id> --limit 10 --status failed
    vision --store-dir <store> record event --session <id> --event <event-id>
    vision --store-dir <store> record checkpoint --session <id> --event <event-id> --annotation <JSON>
    vision --store-dir <store> record resume-context --session <id>
The recorder DB and protected evidence remain in the store; do not delete the store to reset transient data. Session IDs are not authentication credentials. A bound operation with invalid device/frame scope is recorded as failed and not executed. Invalid CLI syntax rejected before dispatch is not an operation receipt.

## Workflow Builder Phase 3

MCP: vision_workflow_candidates {session_id,limit?,after?}; vision_workflow_build {session_id,plan}; vision_workflow_inspect/validate {workflow_id}; vision_workflow_list {limit?,after?}. Build plan exact fields: name, goal, states[], steps[], excluded_actions[]. State fields: id, label, event_id (full path snapshot), region [x1,y1,x2,y2], threshold. Step fields: from, to, pre_event_id, find_event_id, action_event_id, wait_event_id, post_event_id, annotation_id. Exclusions: {event_id,reason}; all action events must be accounted for. V1 accepts reference-based clicks only. Candidate list is not approval.
CLI:
    vision --store-dir STORE workflow candidates --session SID
    vision --store-dir STORE workflow build --session SID --plan plan.json
    vision --store-dir STORE workflow inspect --workflow WF_ID
    vision --store-dir STORE workflow validate --workflow WF_ID
    vision --store-dir STORE workflow list
Bundle: STORE/workflows/WF_ID/{definition.json,plan.json,templates/<sha256>.png}. Source evidence revalidation requires original Recorder store. Never edit a published bundle; a changed plan/evidence produces a new ID.

## Workflow Runtime Phase 4

MCP: vision_runtime_qualify {workflow_id,device,profile:{package,version_code,rotation,locale,ui_mode}}; vision_runtime_run {binding_id,run_id}; vision_runtime_inspect {run_id}; vision_runtime_list {limit?,after?}. The run result is a domain outcome: completed, needs_agent, interrupted. Transport ok does not mean workflow success. A running journal may belong to an active or interrupted process. Duplicate run ID under workspace lock never acts twice. Qualify checks actual foreground/resumed package, installed version, rotation, system locale and UI mode; the app's internal theme/locale are only checked indirectly through visual guards. Use explicit serial, never desktop.
CLI:
    vision --store-dir STORE runtime qualify --workflow WF_ID --device SERIAL --profile profile.json
    vision --store-dir STORE runtime run --binding BIND_ID --run-id run_<32 lowercase hex>
    vision --store-dir STORE runtime inspect --run-id RUN_ID
    vision --store-dir STORE runtime list
CLI run exits 0 only for completed, 3 for other terminal results. Journals: STORE/runtime/runs/RUN_ID.json; bindings: STORE/runtime/bindings/BIND_ID.json. Live frames remain protected in FrameStore. No change to source Recorder session or immutable workflow definition.
