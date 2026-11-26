# Agent Vision 0.2.0 — Release decision
Date: 2026-11-26 (Asia/Taipei). Package opencv-custom 0.2.0; release tag agent-vision-v0.2.0 (separate from legacy GUI tags).
Accepted application commit: cab66a8ab5a72881e02db81148bda82915f6bbd2. Frozen predecessor: 645747eb37033210a140124fc4a5a4f671650265, tag agent-vision-fresh-qualified-20261126. Main fast-forwarded; release-only changes update package/server version and documentation, no new automation behavior.

## Independent acceptance
Fresh Agent verdict ACCEPT_CANDIDATE. RQ0–RQ8 PASS, 308 distinct tests passed, zero failures/skips, all five original findings closed. Actual failure transition trans_81a10000000000000000000000000003 retained post-action frame frm_28b0838c7224 (7 captures, protected, timestamp verified, identical fresh PNG, single click despite duplicate). Live runtime run_81a60000000000000000000000000001 completed 2/2 steps. 372 official store hashes unchanged at acceptance; 61 native MCP tools. Reviewer independently read SQLite, journals, PNG hashes, JUnit XML and Git refs; no new merge blockers.
Evidence directory: ../fresh-phase81-qualification-20261126-1532/ ; qualification-report.md SHA-256: 6a556c680c93dad8cfb78541a575a68a61761af606a5a79faa0594a1bdf3d852.
Previous phase evidence and isolated qualification stores are retained separately; do not merge them into official registry.

## Non-blocking backlog
- N01: Image wait may match a transient pre-destination frame. Consider documenting settle/meaningful ROI or future multi-frame confirmation; semantic verification remains separate. No change to runtime contract in release.
- N02: image/changed max-captures timeout diagnostic may describe configured time instead of cap; future termination_reason.
- N03: Expected package discovery can require one read-only foreground query; keep explicit package verification, consider documented discovery.
No new phase or extra requalification for these items. External wrapper modification, token telemetry, true cross-LLM handoff, plan skeleton and new workflow action types deferred.

## Deployment / rollback
Official NB checkout clean-working, installed CLI/MCP in acceptance-20261126/fresh-venv, shared clean-working/.vision_store. Retain frozen tag, pre-release git bundle, rollback 0.1.0 wheel, official store/skill backup, and candidate evidence archive under ../acceptance-20261126/agent-vision-release-0.2.0/. Existing Registry families remain active; do not import qualification stores. Preserve all original evidence bytes. Historical absolute paths in archived candidate evidence may still name the former checkout; use archival location for raw evidence inspection. Do not silently restore an old store over later live data. Rollback must be explicit and use a consistent backup/version.
Release deployment verification recorded outside repository in the release evidence directory. GitHub sync is not part of this local release. Controlled navigation qualification does not prove arbitrary unattended game automation.
