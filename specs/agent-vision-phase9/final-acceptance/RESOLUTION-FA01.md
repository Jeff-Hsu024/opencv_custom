# FA-01 / FA-02 Review Resolve — 2026-11-27

## Decision and boundaries

FA-01 HIGH: accepted, reproduced and corrected in production-code commit fc1d2050a4e2f91fe0720a02be22d88a834dd900. FA-02 LOW: final-candidate regression provenance gap addressed. FA-03 INFO: retain same-profile Settings qualification scope; no claim of CZN, heterogeneous devices or production readiness. Original independent BLOCKED verdict, tests, logs and both live campaigns remain unchanged. This is implementer verification, not a substitute for independent closure of the finding.

## Reproduction and correction

On original 770e1de, ran both original auditor-owned tests directly using PYTHONPATH=core;.;vision_app/test and an isolated Store: 2 failed, 1 passed, exit 1, 16.26 s. Both mixed faults completed despite protected wrong-size frames and left active slot generation 1. Geometry-only control correctly failed closed.

Move frame identity, width/height and applicable rotation checks before the second profile probe in WorkflowRuntime._capture, after actual frame journaling. Successful capture retains both profile guards. A confirmed mismatch now escapes transient focus retry and reaches existing QualificationSlots.invalidate CAS. No change to _interpret retry budget, action intent, request identity, receipt shape, family/slot CAS or replay semantics. Inspection identified the equivalent ordering gap in PortableService.preflight; fixed it at the same responsibility boundary, with zero input and actual frame retained in failure receipt. No new contract amendment.

Formal regression test_capture_guard_precedence.py adds 10 cases: width/height/rotation with transient focus or control; valid capture with second focused/resumed probe recovery; read-only preflight mismatch and valid-geometry unknown; legacy mismatch; preserved protected last_frame_id, exact B-slot invalidation once, unchanged A slot, no replay and unchanged preflight epoch. All 10 passed in 39.34 s before commit and again as part of consolidated regression at corrected commit. Original auditor tests rerun unchanged at corrected commit: 3/3 pass, exit 0, 15.71 s.

## Consolidated candidate verification

All 1444 collected cases passed (466 regression + 978 frozen contract), 27 disjoint shards, exit 0 each, zero failure/error/skip, tested at fc1d205. Baseline 308/308 covered. All 26 frozen hashes match, 61 legacy tool definitions exactly preserved, all 29 additive schemas match. Actual per-shard command, tested commit, isolated Store, JUnit hash and exit result in regression-summary-fa01.json; full XML/log/args and process receipts in .scratch/agent-vision-phase9/verification/fa01-resolution. Prior 1429-case suite remains historical and is not added to new total.

Built wheel from git archive of corrected commit, opencv_custom-0.2.0-py3-none-any.whl, 176981 bytes, SHA256 1fe7c1334dd4f8e5a0e6beeb9e612cf372504a7b07ac49624a027683b043f8cc. Retained existing version metadata; candidate only. Installed only to isolated package-target in fa01-resolution. Actual import path confirmed, CLI portable-list equals MCP metadata response, 90 tools. No production install. No live Android rerun because finding is deterministically reproduced and fixed; two positive live campaigns remain evidence for predecessor 770e1de. Full-suite and package verification establish corrected candidate software evidence; they do not themselves establish a new live campaign at fc1d205.

## Acceptance disposition

FA-01 corrected / targeted independent recheck recommended; FA-02 resolved by coherent final-code commit provenance; FA-03 acknowledged. No new DAG/worker/agent, Android input, main/tag change, push, deployment, official Store or frozen archive mutation. Preserve original auditor decision as historical; obtain targeted independent review of diff and new regression before marking V01/V02 formally closed.
