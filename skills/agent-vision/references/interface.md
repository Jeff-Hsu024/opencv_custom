# Phase 8 Agent Interface (candidate)

Discover actual deployed tools before use. Known registered tasks still prefer vision_task_execute. For new UI exploration, open an explicit Recorder session and learn the target using real pixels. A transition is a locked one-click observation/action composition, not a rollback transaction.

## Transition
MCP vision_transition {device,session_id,transition_id,target,postcondition,threshold?,max_ref_age_seconds?,pre_state?,return_image?}.
Generate trans_<32 lowercase hex> once. Explicit device/session, target registered asset, threshold default .98 (0.8..1), max_ref_age_seconds default 15 (0<value<=60). Optional pre_state is a named asset whose unique match is checked on the fresh pre-frame. Postcondition: {mode:"changed",timeout:5,region:[x1,y1,x2,y2],settle_seconds:0.8,min_changed_ratio:0.01}. ROI is optional, but use a meaningful region rather than a click effect. settle_seconds is optional 0..2, strictly below timeout, included in elapsed/budget. Image mode takes target and optional threshold, but cannot be compiled by Builder v1 (which requires changed wait). return_image defaults true; false returns artifact path only.

CLI:
```powershell
vision --session SID transition execute --device SERIAL --transition-id TRANS_ID --target NAME --postcondition '{"mode":"changed","timeout":5}' --return-image false
vision transition inspect --transition-id TRANS_ID
```
Use native subprocess argv or appropriate shell quoting for JSON. Same ID + same request returns receipt; conflict rejects. Inspect after timeout; never make a new ID to compensate. Receipt status observed / needs_agent / interrupted; observed is not semantic PASS. The receipt events.pre/find/action/wait/post identify ordinary Recorder operations. Inspect actual post image, then annotate events.post with semantic PASS/FAIL/UNKNOWN. Failure may have action_outcome unknown/executed_unverified. Do not repeat an uncertain click. Partial chain is preserved.

## Annotation schema
Allowed fields: purpose, state, expected_postcondition, observation, verification, failure_reason, insight, next_step, completed_steps, unresolved_issues. Nonempty object, additional properties rejected, verification PASS/FAIL/UNKNOWN, 8000 serialized character limit. Prefer strings and string arrays for completed_steps/unresolved_issues; legacy JSON values remain accepted for other fields. Do not supply known_assets: Inspector retains asset evidence. INVALID_ANNOTATION includes unknown_fields and allowed_fields, not values. Use vision_record_asset_evidence {session_id,limit?,after?} / CLI record asset-evidence --session SID --limit 20 --after CURSOR for distinct asset revisions, ordered by first observation.

## Response modes
Legacy default full. For workflow build/inspect/validate, runtime inspect, task inspect, recovery propose/inspect, record event/events/resume_context use response_mode="summary" for normal decisions. CLI --response-mode summary. Full retains original payload. Detail: workflow/runtime inspect by step ID; task inspect by child run ID; record events/resume_context by visible event ID (detail_id); record event detail is full event. Workflow build detail includes state marker provenance; recovery propose detail adds reconciliation and endpoints. Workflow validate and recovery inspect already bounded and return their normal payload. For data beyond the current page, page or request exact event. No changes to stored evidence or bundle identity.

## Images and transport
Native MCP ImageContent is type=image/mimeType/data; type=text contains JSON metadata, not PNG. Queqiao extension response wraps downstream result.result.content. Forward image blocks through an image renderer, parse only text blocks. Never print raw Base64. With return_image=false on snapshot/crop/resize/transition use the actual artifact path and dev.queqiao.media image_read; use workspace-relative path verified from metadata. CLI emits artifact metadata, not images. This is a supported workaround for wrapper parsing, not a change to the external Queqiao connector. If image cannot be rendered, do not claim visual observation.

## Compatibility
MCP find now accepts max_results and color_mode; wait accepts max_captures, pixel_tolerance, min_changed_ratio, max_changed_ratio, stable_duration and color_mode. CLI --interval maps to poll_interval; legacy defaults differ (0.5 vs 0.2), specify explicitly. Workflow v1 remains same-device Android click-only. No asynchronous task service, no automatic recovery expansion, no Core changes. Full-screen changed is not semantic proof; Builder can reject animation frames. Preserve those receipts and re-record with meaningful ROI/settle if appropriate.
