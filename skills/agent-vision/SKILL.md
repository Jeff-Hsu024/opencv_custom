---
name: agent-vision
description: Use Vision Platform to observe and operate Android/desktop UI, resume recorded visual exploration, build and qualify reusable click workflows, manage workflow versions, or execute registered tasks with bounded recovery. Use when a task involves screenshots, OpenCV assets, scoped device actions, Recorder, Workflow Builder, Runtime, Recovery, Lifecycle or Orchestrator through Vision CLI/MCP (including Queqiao NB).
---

# Agent Vision

Use the installed application tools, not a blind coordinate macro. The LLM is the explorer of unknown UI; deterministic execution is preferred for known tasks. Keep all state in the same workspace store.

## Choose the entry point

| Situation | First action |
| --- | --- |
| Known task / repeat a registered workflow | `vision_lifecycle_list`, inspect matching family, then `vision_task_execute` |
| Continue an exploration | `vision_record_resume_context` for the existing session |
| Unknown task / learn a UI | `vision_record_start`, then fresh recorded snapshot |
| Convert stopped exploration to reusable workflow | `vision_workflow_candidates`, review evidence, build |
| Qualify an offline workflow | `vision_runtime_qualify`, then explicit runtime run |
| Runtime failure with no known recovery | Inspect task/run; `vision_recovery_open` if recovery exploration is appropriate |
| Manage a reviewed version or route | `vision_lifecycle_inspect`, generation-checked mutation |

Never silently pick a family, device, profile or store. Discover actual tools first. Read [transport](references/transport.md) for exact calls and NB environment. For Phase 8 compact interaction, read [interface](references/interface.md). Read [workflow playbook](references/workflow.md) only for the relevant stage; for compilation read [builder plan](references/builder.md).

## Known task: prefer the single entry

1. Inspect the relevant registered family; use its actual active version/device/profile and current generation. Confirm the goal matches the user request.
2. Call `vision_task_execute` with family_id, caller-generated unique task_<32 lowercase hex> ID, expected_generation, and optional auto_recover (default false). Enable recovery only when a previously qualified recovery and restart are in scope.
3. Read the domain status, not transport ok. Only completed means the full primary task finished. needs_agent/interrupted require inspection. On transport timeout inspect the same ID, never send a new one as a retry.
4. Use CLI for longer synchronous runs if MCP request limits are restrictive. No detached task API is provided.

Automatic recovery is limited to first-step precondition failure before any primary action, a unique enabled exact-version route, verified return to original initial state, then one full restart. No partial-prefix replay, uncertain-action retry or second recovery.

## Unknown UI: record, observe, act, verify

1. Discover devices/capabilities; use an explicit authorized device. NB's validated example is MuMu `127.0.0.1:16480`, not a universal default. Avoid desktop and unrelated emulator instances.
2. Start or resume a Recorder session. Pass its session_id to every recordable operation (CLI global --session before command). Observe a fresh full screenshot; render actual pixels. A path or base64 text alone is not observation.
3. Learn stable target assets via ROI crop/register. If the target and intended postcondition are understood, prefer vision_transition with explicit session and unique transition ID; use a meaningful changed ROI and optional bounded settle for animation. Otherwise find on a fresh frame, request all matches and inspect uniqueness, bbox, score, device and freshness. For a one-off frame point, use frame ID and validated local point; reusable workflows require reference clicks.
4. Act once (vision_transition already includes the click; never click again after it). Use short explicit ref age (e.g. 15 seconds); ref age does not prove unchanged UI. No-match, ambiguity or stale state => observe again, never pick an arbitrary target.
5. For a primitive click, wait for an appropriate visual condition. For transition, inspect the returned actual post-snapshot; its observed status is not semantic PASS. Use return_image=false plus real artifact image read if the connector wraps image data. `executed`, match score, exit code 0, or changed pixels alone do not prove task success.
6. Annotate PASS/FAIL/UNKNOWN on the actual observation event; checkpoint goal, state, steps, evidence, uncertainties and next step. Resume via Inspector, not conversation reconstruction.

## Compile, qualify, publish

Stop the session, review every action and select explicit connected transitions. For build/inspect request response_mode=summary; full remains available for legacy/audit. The transition receipt exposes the exact primitive event IDs. [Builder plan](references/builder.md) defines exact required fields. Offline PASS is not live success. Qualify exact Android device/profile, perform controlled live run, then explicitly register and activate reviewed version. No auto promotion. Compiled v1 accepts reference-based clicks only; interactive swipe/type/key/desktop are available where capability permits but cannot be compiled.

## Failure and handoff

Inspect task and child run. Treat unknown or pending action as unknown, not failed-with-no-effect. Do not replay blindly. Open a linked recovery case when appropriate, fresh full snapshot first, explicit observed-state annotation before actions, record smallest safe route, compile/qualify/run/verify child separately, link to exact parent version only with live qualification. Recovery success is not original-task success. Do not overwrite existing bundle or original failure receipt.

## Invariants

- Use explicit task scope, real evidence and fresh pixels; avoid unrelated settings/accounts and irreversible actions without appropriate intent.
- Discover actual capability before declaring unavailable. Prefer MCP or installed CLI; raw ADB only for verified setup/inspection or capabilities absent from the application API.
- Do not put secrets in text annotations or capture sensitive UI unnecessarily. Type input is masked in records; screenshots are not automatically redacted.
- Distinguish transport status, operation outcome, semantic verification, offline PASS, live preflight, live completed run and task completion.
- Keep existing store intact; immutable bundles and retained evidence are not scratch files. Report blockers and verified side effects. Do not claim unattended production readiness from the navigation POC.
