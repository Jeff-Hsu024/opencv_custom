# Visual workflow playbook

Read only the section relevant to the current task. Use [transport](transport.md) for exact CLI/MCP arguments and [builder](builder.md) for a concrete plan.

## State-driven execution

Define each step as:
- precondition: visible known page or image evidence, device and orientation
- target: semantic role plus template name or visually selected frame-local point
- action: one click/key/swipe/type, explicit bounds
- postcondition: page title or a unique visual marker, or a checked state change with actual screenshot
- on failure: re-observe; return precise error if unknown

Use a high-confidence known target in a known page. A 1.0 score only means the pixels match, not that a button is enabled or that the intended action occurred. Do not use a screenshot from a previous task to act on the current screen. Prefer ROI for animated UIs; check the entire relevant context if there are duplicates. Templates must be reviewed again when resolution, locale, app version, theme, or scale changes.

## Reusable workflow lifecycle

1. Learn with observation and one-off scoped interactions; save stable target assets and state markers.
2. Record the semantic sequence with preconditions/postconditions; separate asset recognition from actions.
3. Replay only within its intended app and device context using fresh frames, not captured coordinates. Bounded state waits; handle unknown state by returning to the agent.
4. Validate multiple fresh runs and changed conditions before declaring repeatability. Use deterministic OpenCV recognition/action execution for known states and LLM reasoning only for unfamiliar cases.

## Controlled POC

Choose reversible navigation with no persistent settings change. Verify original app/page, navigate at least two pages using newly learned targets, validate each postcondition and return to original app/page. Report actual frame IDs and scores. A successful POC is not evidence of unattended game-specific automation, robust UI recovery or performance at scale. Test those separately on the intended application.

## Recorder and handoff

Checkpoint explicit state, verified postconditions, completed_steps, unresolved_issues, next_step and evidence-linked event ID. Use resume_context instead of replaying the whole conversation or raw log. Verify fresh state before acting. Inspect failed/timeout/pending events separately; no automatic retry. Recorder is a faithful exploration memory, not a workflow builder or runtime.

## Builder review sequence
1. Stop source session and discover action candidates with pagination.
2. Inspect source receipts, actual full frames and explicit semantic annotations. Select a connected path; account for every action and reject ambiguous or interrupted transitions.
3. Choose visually distinctive state marker crops, including destination state markers (not merely action targets). The builder tests positive and other-state negative historical frames, checks target uniqueness, and seals template/evidence hashes.
4. Preserve the content-addressed bundle and validate it again across processes. Any evidence or template drift is a failure. Do not promote offline validation to live qualification.

## Runtime execution and handoff

Qualify the immutable bundle on the exact Android device using actual profile evidence. Run once with a unique idempotency ID. Runtime captures fresh state, requires exactly one expected guard and one current target, records pending action before click, and polls fresh postcondition frames within a bounded budget. A click receipt does not prove semantic completion. On needs_agent or interrupted, query runtime inspect, inspect the last actual frame and action outcome, and do not retry blindly. A running receipt is not evidence of success. Never conflate offline Builder PASS, live preflight PASS and actual completed runtime execution. Runtime has no authority to change workflow definitions or learn recovery rules.

## Agent recovery sequence

Use the failure handoff as a bounded context, not a command to replay. Check original action outcome and fresh state. Record the smallest reversible route that returns to a known parent state; a new snapshot after learning is required if the anchor ages. Use an explicit semantic reconciliation and original evidence. Compile, validate, and qualify the child separately. Preserve the verified prefix for review, but do not splice or replay it automatically. A full replacement must start/end at the original task endpoints; a recovery route only recovers state. No automatic promotion or original-task success inference.

## Lifecycle and recovery reuse
Publish a reviewed live-qualified version as a named family; explicitly activate it with the current generation. Preserve version lineage and audit history. Link recovery routes only to the exact qualified parent. Selection uses fresh evidence, never historic coordinates, and only recommends a unique matching route. Treat uncertain action effects as manual review. A disabled family or route rejects new Runtime execution; prior run IDs still return original receipts. Qualify and explicitly execute the selected child, verify returned state, then independently decide whether the original task should resume. No automatic rollback or retry.

## Deterministic task orchestration (preferred for known tasks)
For known tasks, prefer the single task entry over manual per-step or per-child calls. On eligible first-step precondition failure, explicitly enabled auto_recover selects a unique known recovery route from a fresh frame, runs it, checks the parent's initial guard, and restarts the full task once. Any prior primary action, uncertain effect, ambiguous/missing route or failed recovery/restart stops for Agent review. Recovery alone is not task completion. No automatic discovery, promotion or LLM invocation.

## Result classification and session handoff

| Receipt | Meaning | Next action |
| --- | --- | --- |
| operation executed / verified=false | Device input accepted, semantic effect unverified | Observe actual postcondition |
| offline_pass | Builder historical evidence passed | Qualify and run live |
| preflight_pass | Device/profile and starting guard checked | Explicit live run |
| completed (runtime) | All runtime postconditions passed | Register reviewed version if appropriate |
| live_pass (recovery) | Child route verified against parent endpoint | Explicitly link exact parent |
| completed (task) | Full primary run completed | Report result |
| needs_agent / interrupted | Not completed; inspect actual outcome | Inspect task and child run, fresh observation |
| transport timeout | Transport did not return a result | Inspect the same task/run ID, never create a retry ID blindly |

For a new agent session, share the workspace/store, device, goal and the existing session_id, task_id or run_id. Resume an active/paused Recorder session appropriately; stopped sessions remain immutable for operations. For known tasks use lifecycle list/inspect before executing. Never reconstruct a previous agent's action sequence from chat if structured evidence exists.

Phase 8: use [interface](interface.md) for the compact transition and response modes. Existing recorded operation semantics, workflow identities and recovery policy remain unchanged.
