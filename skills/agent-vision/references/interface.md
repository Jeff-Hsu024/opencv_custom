# Phase 8 Agent Interface (candidate, including 8.1)

Discover actual deployed tools before use. Known registered tasks still prefer vision_task_execute. For new UI exploration, open an explicit Recorder session and learn the target using real pixels. A transition is a locked one-click observation/action composition, not a rollback transaction.

## Transition
MCP vision_transition {device,session_id,transition_id,target,postcondition,threshold?,max_ref_age_seconds?,pre_state?,return_image?}.
Generate trans_<32 lowercase hex> once. Explicit device/session, target registered asset, threshold default .98 (0.8..1), max_ref_age_seconds default 15 (0<value<=60). Optional pre_state is a named asset whose unique match is checked on the fresh pre-frame. Postcondition: {mode:"changed",timeout:5,region:[x1,y1,x2,y2],settle_seconds:0.8,min_changed_ratio:0.01}. ROI is optional, but use a meaningful region rather than a click effect. settle_seconds is optional 0..2, strictly below timeout, included in elapsed/budget. Image mode takes target and optional threshold, but cannot be compiled by Builder v1 (which requires changed wait). return_image defaults true; false returns artifact path only.

CLI:
```powershell
vision --session SID transition execute --device SERIAL --transition-id TRANS_ID --target NAME --postcondition '{"mode":"changed","timeout":5}' --return-image false
vision transition inspect --transition-id TRANS_ID
```
Use native subprocess argv or appropriate shell quoting for JSON. Same ID + same request returns receipt; conflict rejects. Inspect after timeout; never make a new ID to compensate. Receipt status observed / needs_agent / interrupted; observed is not semantic PASS. The receipt events.pre/find/action/wait/post identify ordinary Recorder operations. Inspect actual post image, then annotate events.post with semantic PASS/FAIL/UNKNOWN. Failure may have action_outcome unknown/executed_unverified. Do not repeat an uncertain click. Partial chain is preserved. See failure observation contract below.

## Annotation schema
Allowed fields: purpose, state, expected_postcondition, observation, verification, failure_reason, insight, next_step, completed_steps, unresolved_issues. Nonempty object, additional properties rejected, verification PASS/FAIL/UNKNOWN, 8000 serialized character limit. Prefer strings and string arrays for completed_steps/unresolved_issues; legacy JSON values remain accepted for other fields. Do not supply known_assets: Inspector retains asset evidence. INVALID_ANNOTATION includes unknown_fields and allowed_fields, not values. Missing session is SESSION_NOT_FOUND; missing or other-session event is EVENT_NOT_FOUND. Use vision_record_asset_evidence {session_id,limit?,after?} / CLI record asset-evidence --session SID --limit 20 --after CURSOR for distinct asset revisions, ordered by first observation.

## Response modes
Legacy default full. For workflow build/inspect/validate, runtime inspect, task inspect, recovery propose/inspect, record event/events/resume_context use response_mode="summary" for normal decisions. CLI --response-mode summary. Full retains original payload. Detail: workflow/runtime inspect by step ID; task inspect by child run ID; record events/resume_context by visible event ID (detail_id); record event detail is full event. Workflow build detail includes state marker provenance; recovery propose detail adds reconciliation and endpoints. Workflow validate and recovery inspect already bounded and return their normal payload. For data beyond the current page, page or request exact event. No changes to stored evidence or bundle identity.

## Images and transport
Native MCP ImageContent is type=image/mimeType/data; type=text contains JSON metadata, not PNG. Queqiao extension response wraps downstream result.result.content. Forward image blocks through an image renderer, parse only text blocks. Never print raw Base64. With return_image=false on snapshot/crop/resize/transition use the actual artifact path and dev.queqiao.media image_read; use workspace-relative path verified from metadata. CLI emits artifact metadata, not images. This is a supported workaround for wrapper parsing, not a change to the external Queqiao connector. If image cannot be rendered, do not claim visual observation.

## Compatibility
MCP find now accepts max_results and color_mode; wait accepts max_captures, pixel_tolerance, min_changed_ratio, max_changed_ratio, stable_duration and color_mode. CLI --interval maps to poll_interval; legacy defaults differ (0.5 vs 0.2), specify explicitly. Workflow v1 remains same-device Android click-only. No asynchronous task service, no automatic recovery expansion, no Core changes. Full-screen changed is not semantic proof; Builder can reject animation frames. Preserve those receipts and re-record with meaningful ROI/settle if appropriate.

## Phase 8.1 — failure observation contract
All three wait modes retain the last valid FULL screenshot in memory and persist only the terminal observation, not every poll. On WAIT_TIMEOUT (CLI exit 4, MCP isError=true) or a later capture/evaluation failure, operation_result contains condition, verified=false, status, captures, frame_id, artifact, last_capture_timestamp (wall-clock completion of capture), elapsed_seconds and capture_role. A supplied historical baseline is not a capture; fresh_baseline is a real capture from this wait. Zero valid captures => frame_id/artifact/timestamp null. A retention error is separately identified; a timestamp alone is not a retrievable frame. Wait failure is not verification PASS.

Transition receipts now distinguish:
- pre_frame_id: actual initial observation, retained for history.
- last_observed_frame_id / last_frame_id: latest retained observation in the reported phase, not a live-state guarantee.
- post_frame_id: separate successful terminal snapshot after a verified wait; may be null even if there is a post-action wait observation.
- observation_phase: none, pre_action, post_action_unknown, post_action. Once action intent is durable, the current observation pointer and artifact are cleared until there is a real post-action capture. A failed wait can supply a post_action image without proving the intended destination. No successful post-action capture => null last_observed_frame_id and artifact, never the pre-frame.
- wait: condition/status/verified/captures/frame_id/timestamp and elapsed information if known.
- action_outcome remains not_attempted, unknown or executed_unverified. Semantic verification remains UNKNOWN. No automatic retry/replay; inspect same ID and obtain fresh observation before deciding the next action. Duplicate receipt is historical, not a fresh screenshot.
- TARGET_NOT_FOUND (0 matches) and TARGET_AMBIGUOUS (multiple matches, capped at two) stop before action; distinguish unknown asset ASSET_NOT_FOUND.
Legacy receipt inspection projects safe frame semantics from available recorded events without rewriting historical bytes; legacy missing evidence stays missing. A process crash before Recorder has saved a terminal event can lose in-memory observations. Reconciliation never manufactures them.

## Runtime profile discovery
Use vision_runtime_probe_profile {device,package} or CLI:
```powershell
vision runtime probe-profile --device SERIAL --package com.example.app
```
Explicit serial and Android package required; package must be both focused and resumed. The read-only operation returns the actual package, integer version_code, rotation 0..3, locale and lowercase hexadecimal ui_mode (e.g. "0x21", not "night"). Use the returned object unchanged for runtime qualify (CLI: save result object as UTF-8 JSON profile file). Probe is not qualification or a binding, does not start an app, change settings, or send input. APP_MISMATCH/PROFILE_UNKNOWN/PROFILE_PROBE_FAILED must be resolved by fresh observation, not guessed profile fields.
