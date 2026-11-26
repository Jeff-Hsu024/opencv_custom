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
