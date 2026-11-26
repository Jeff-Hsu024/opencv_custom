# Phase 8.1 — Fresh Agent Feedback Patch

Status: CANDIDATE TECHNICAL PASS; targeted independent Fresh Agent requalification pending.
Candidate base: 9ded6a1383d5ea78730931cf06e35a49af5ecfeb. Frozen main/tag: 645747eb37033210a140124fc4a5a4f671650265.
The user cancelled Orca Run run_89238768bdae before implementation. Coordinator and worker ctx_d7163a0dd9f8 stopped, worker liveness exited, terminal released, eight tasks marked failed with explicit cancellation result; no Orca worker code changes. Direct ChatGPT implementation in existing Phase 8 worktree, no new repo or worktree.

## Patch scope and results

| Ticket | Result |
|---|---|
| AO-F01a | WaitService retains last valid full-frame capture and actual capture completion timestamp on failure/timeout for image, changed and stable. Only terminal observation persisted. Historical baseline never substituted. Zero valid capture and retention failure explicit. |
| AO-F01b | Typed WaitFailure, Recorder operation_result and protected frame evidence, native MCP and CLI failed payloads; WAIT_TIMEOUT exit 4 and isError preserved. Cross-device and disk-retention failures tested. |
| AO-F01c | Transition explicit pre/last-observed/post frame IDs, observation phase, wait status and timestamps. Clears current pointer at action intent, uses retained wait observation on failure; no pre-click image presented as current. Duplicate/interrupt reconciliation from durable events, legacy projection without historical rewrite. |
| AO-F02 | Read-only vision_runtime_probe_profile and CLI runtime probe-profile; actual device/package validated; lowercase hex ui_mode. |
| AO-F03 | Candidate/native stdio launch recipe, explicit store isolation and version/module diagnostics; 61 candidate tools. |
| AO-F04 | Typed image/text filtering and actual Queqiao wrapper/media instructions. Native MCP ImageContent SHA matches PNG; actual media renderer viewed timeout and final images. External wrapper unchanged, not candidate-registered. |
| AO-F06 | TARGET_NOT_FOUND vs TARGET_AMBIGUOUS (capped count), session scope/inactive and SESSION_NOT_FOUND vs EVENT_NOT_FOUND, CLI asset error mapping. |
| AO-F08 | 281 original + 27 new = 308 distinct tests passed, no failures/skips. Raw SQLite/PNG/JSON audit and live targeted failure/success smoke completed. Independent fresh-agent rerun remains pending. |

## Live reproduction

Isolated store: ../acceptance-20261126/agent-vision-phase8/phase81-direct/store
Device: 127.0.0.1:16480 only; original stage-info -> graphics settings -> stage-info. No settings, accounts or resources changed.

Original Fresh Agent F01 evidence remains intact in ../fresh-phase8-qualification-20261126-1349/store; original journal SHA-256 90a9faadc347876b5f9bafdcab009e93d206bed2e72bcf500cf70f37316b8b0e, old failed wait operation_result remains null. No rewrite or backfill.

New session ses_9e892f235cb942bdb75037dd940e7e48:
- trans_20261126810000000000000000000001: deliberately wait for old gear after clicking it. needs_agent/executed_unverified, WAIT_TIMEOUT, four captures. Pre frm_9086277a74ce; retained real post-action graphics frame frm_a6c55ed8b738, post_frame_id null, observation_phase post_action, timestamp 1795676429.1748724. Wait evt_a32f77bebdcd46cf8d73d4fa8d6a5ad9 timeout, verified=false, protected frame in evidence. Native ImageContent hash 51d850eccd80661ff8ce9109d79aec5355ade2841c83ab7424a1d68998b244f3 matches raw PNG. Repeated same ID returned identical receipt; one click event only.
- trans_20261126810000000000000000000002 closed settings with fresh reference, observed stage-info frm_6e410acbcf6b.
- changed wait evt_e2406c082d8c42b28dec3c001538e2f7, frame frm_03f7de29cc62; stable wait evt_e787d9f1c3c94b639bfc2d779f8afd38, frame frm_f0a789f48936; both timed out, two captures each, real full frames protected; no clicks.
- Profile probe actual package com.smilegate.chaoszero.stove.google, version_code 171008530, rotation 1, locale zh-Hant-TW, ui_mode 0x21.

Success smoke: ses_6e1920c6254c44e1b828a48c0f4bfbf5, trans IDs ending 03 and 04. Two successful observed transitions, two semantic PASS annotations, stopped session. Offline workflow wf_bdece3e5ba809bfddb97742a23d72b2b95f3d4c23fceb013b502e611cb70e5b5 (12/12 state and 2/2 target checks). Actual profile qualification bind_63b76d4178c85c9a4497386c5020e0f91a9eed9e6692cf35b42598e5d3b6d34b; live run run_20261126810000000000000000000001 completed 2/2; final frm_b50db50b1df3 visually confirmed original stage-info. Raw cv2 audit independently recomputed state/target matches and fresh refs from stored files, not separate LLM agent.

## Regression and integrity

Batched suite: 245+31+29 = 305, then expanded failure-evidence suite 27/27 (24 overlap, 3 added; total 308 unique). XMLs in phase81-direct. No application code changed after batched suite; last additions are tests only. One initial negative-test fixture produced an actual changed result (all pixels changed); corrected to unchanged ROI and changed outside, then passed. Core unchanged.
Raw audit confirmed all 372 hashes in official store and frozen archive, official skill byte-for-byte identical to frozen version, existing 60 candidate tools retained plus profile probe. All successful and failed operation data remains in isolated stores.

## Limitations / decision

No merge or official deployment. Not a fresh independent LLM qualification; direct implementation plus raw evidence audit only. External Queqiao wrapper not changed; native MCP and media workaround verified. No new capability to compile image-mode waits, swipe/type/key, or auto-promote recovery. Retained observation is historical and not proof of current state or semantic success. Hard process termination before event persistence can lose in-memory capture; no fabricated recovery. A bounded wait can overrun nominal deadline by in-flight capture/persistence latency (live 3s request measured 3.156s wait); no hard real-time guarantee. Plan-skeleton UX and token telemetry/cross-LLM handoff deferred. GitHub not attempted.
Evidence: ../acceptance-20261126/agent-vision-phase8/phase81-direct/ includes calls.jsonl (typed metadata and hashes), audit.py, raw-audit.json, regression XMLs, smoke-plan.json, store; cancelled Orca manifest remains in sibling phase81-orca.
