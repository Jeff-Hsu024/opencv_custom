# Phase 9 — Independent final acceptance audit

Decision: **BLOCKED**  
Candidate: `770e1de7c53c71de957c69f41291e3b089b0a5c4`  
Branch: `feat/agent-vision-multi-device`  
Baseline / existing release tag: `bfbec17fe55b25a2ea7ddbd9051cc3937ccd3efb` / `agent-vision-v0.2.0`  
Environment: Queqiao NB, existing agent-vision-multi-device worktree; 2026-11-27.

## Executive assessment

The retained direct Apps and independent Sound campaigns substantiate the intended Learn Once, Qualify Per Device, Execute Many behavior for the exercised same-profile Android Settings routes. Raw receipts, both isolated Stores, decoded PNGs, immutable asset/template hashes, qualification CAS, source/trial proofs and actual interleaved action timestamps substantiate these successful executions. They do not establish that every required negative path is fail-closed.

The independent auditor reproduced a previously uncovered HIGH contract violation at the candidate HEAD: a confirmed post-action frame geometry mismatch can be suppressed when the second profile probe raises transient PROFILE_UNKNOWN. The subsequent observation can complete the task while leaving the qualification active. This violates the guard and qualification invalidation requirements. Finding FA-01 blocks closure of final V01/V02 notwithstanding successful positive campaigns. No implementation repair was made.

## Method and provenance

The auditor read USE_CASES, SPEC, CONTRACT, CONTRACT_SCHEMAS, RESOLUTION, TICKETS, IMPLEMENTATION_STATUS, c00/FREEZE, group-v01-v02/REPORT, direct supporting report and independent campaign report, then compared their claims against Git objects, existing regression artifacts, request/response receipts, actual databases and image bytes. Newly authored verify.py and supplement.py perform independent checks; the existing campaign audit script was not used as a substitute. SQLite opened with mode=ro and query_only. Image examination used Pillow decoding, pixel comparison and OpenCV template correlation locally; no screenshots were exported. Best-match independent correlation is not a separate exhaustive implementation of every multi-match algorithm. An independent adversarial pytest exercises the actual shared execution service with an injected device in a temporary isolated store. No Android inputs, agents, DAG, production Store, frozen archive, release tags, main, deployment, merge or push were performed.

VERIFICATION.json records 55 checks, 54 successful and one failed (focus_geometry_guard), raw IDs, timestamps, hash comparisons and command evidence. These counts are auditor assertions, not pytest test counts.

## V01 — compatibility and regression evidence

| Evidence | Actually tested / observed | Assessment |
|---|---|---|
| C00 freeze | 26/26 LF-normalized SHA-256 match | Verified |
| MCP catalog | 61 legacy definitions exactly preserved; 29 additive input schemas, 90 total; 29 Draft 2020-12 schemas checked | Verified |
| Original regression cases | 308/308 collected baseline cases represented in candidate collection; transition idempotency case now parameterized | Verified |
| Consolidated suite | 5a8b26298dc4ba9cf43cb90306173f9cc629c644: 1,429 distinct JUnit cases, 26 disjoint shard argument sets and 26 exit receipts = 0; no failures/errors/skips | Verified at this commit only |
| Timeout correction | cb760869c74e4bbd8c769f2f19d3b7260aea4c0d: transport-fix.xml, 26 passing cases; separate process exit receipt not located | JUnit verified; exit evidence limited |
| Final focus correction | 770e1de: existing post-focus-regression.xml, 1,004 Portable/Contract cases, zero failure/error; separate exit receipt not located | JUnit verified; exit evidence limited |
| Fresh auditor Runtime rerun | 770e1de: runtime-final-head.xml, 21 passing, exit 0, 31.60 s | Independently verified |
| Fresh auditor negative regression | 770e1de: focus-geometry-audit.xml, 1 failed, exit 1 | Verified contract violation; FA-01 |
| Copied legacy Store | 164 retained archive files reconciled; immutable files and pre-existing Recorder rows unchanged; 78 indexed frames, 67 protected; 3 completed legacy proofs published to copied Store | Verified |
| Candidate wheel provenance | Old cb76086 wheel SHA-256 61fd3b7468cd483b1548358c6397537801751e6aabcb1b937fd25e2ef0f01526; final wheel 76827327e7fd5228788e742f893f12dd07787789bc925db1ccbbd533fb3272e8; 59 shipped Python files per wheel match commit source (LF normalized) and installed bytes | Verified; isolated installation, not release approval |

The 1,429-case suite is **not** a full rerun against final HEAD. 0099a36 is documentation-only in the examined sequence; final focus fix changes runtime and runtime tests. The historical passing results remain valid evidence at their actual revisions. The first auditor Runtime collection attempt failed because PYTHONPATH lacked core; corrected environment (core;.) and retained both receipts. The first verification-script attempt assumed frame-only proof hash entries; corrected the auditor script to include refs, then reran successfully. Neither was a product change.

## V02 — existing live campaign evidence

Both campaigns use explicit A=127.0.0.1:16480 and B=127.0.0.1:16416. Within each campaign the same immutable definition and four exact template hashes are used on both devices. The two campaigns intentionally learned different workflows and definitions. Profile: com.android.settings, version 32, 720x1280, rotation 0, zh-Hant-TW, UI mode 0x21.

| Metric | Direct Apps | Fresh Agent Sound |
|---|---:|---:|
| Source Recorder sessions on A | 1 | 1 |
| Recorder events on A / B | 13 / 0 | 13 / 0 |
| Learned assets A / B | 2 / 0 | 2 / 0 |
| Source proof completed | 1 | 1 |
| B preflight then completed target trial | 1 | 1 |
| Separate active slots, each generation 1 | 2 | 2 |
| Standalone executions A / B completed | 2 / 2 | 2 / 2 |
| Batch children completed | 2 | 2 |
| Terminal request claims | 18 | 17 |
| Durable action intents | 19 | 18 |
| Final A / B action epochs | 12 / 8 | 10 / 8 |
| Indexed PNGs decoded | 52 | 44 |
| Protected indexed PNGs | 44 | 41 |
| SQLite integrity and foreign key checks | 3/3 | 3/3 |
| Independent correlation-checked source + portable steps | 16 | 16 |
| Distinct fresh portable refs / pre-post frames | 14 / 28 | 14 / 28 |

Direct source: run_84529c1d97bc45dfbc8b58dbb0c81a34; target trial prun_f1140f681bef472cb6ff8d04d162f287; batch batch_73e3e5ec264143f199dcad3537f2eb70. Direct's initial unsuccessful source run run_0ed252eb4eb645958cd726a143e7b88b is retained; it stopped after one action with PROFILE_UNKNOWN. Explicit legacy Back recovery is evidenced by recovery-back.json and epoch 4 (no durable request intent for that legacy raw operation). It was not hidden or counted as successful.

Fresh agent: agent-observation.json records the Codex transcript/session d8a5aea2-c2b2-4c65-955d-9cec6be08f5d; stated model/effort GPT-6.2-Sol Low comes from the campaign identification, not an independent model-serving attestation. Source run_e67c913ddbbb4eeb9c770cfddfac6189; B trial prun_8aaff6d586744666a8aa08d1515f7ae1; batch batch_7ea48a8e6bb24b0cae97f24f118cd033. Separate fresh Store, distinct Sound assets and learning session substantiate independence.

### Actual action overlap (Unix seconds)

| Event | Direct | Independent |
|---|---:|---:|
| B first action | 1795784434.104249 | 1795784843.9532177 |
| A first action | 1795784434.1458287 | 1795784843.9848735 |
| Earlier second action | B 1795784437.0719686 | A 1795784846.7003062 |
| Later second action | A 1795784437.2008371 | B 1795784846.9695604 |

Both first actions occur before either second action. The intersection of the observed first-to-last action spans is approximately 2.926 s and 2.715 s, respectively. This is evidence of interleaving, not an inference from admission times.

### Reversibility and ownership

Actual initial/final indexed frame pairs, compared RGB rows 50:1200 (exclude changing system bars):

| Campaign / device | Initial | Final | Pixel agreement |
|---|---|---|---:|
| Direct A | frm_463b64cd2e04 | frm_7598bb761786 | 100% |
| Direct B | frm_cfe7fde84949 | frm_dd4adda46784 | 100% |
| Independent A | frm_2be5fc17e672 | frm_052debfb46ff | 100% |
| Independent B | frm_694a91bd2acb | frm_0a734ae566ed | 100% |

Raw frame metadata, referenced evidence, device IDs, epochs, template bytes, step chronology and receipts support correct device-local operation in the exercised paths. Source and trial proof evidence and independently recomputed qualification identities/mutation hashes agree. Both slots started absent at generation 0, committed at generation 1; family generation progresses independently to 2. Exact batch duplicate and conflict rejection verified in both campaigns; standalone duplicate and conflicting request independently verified in the fresh campaign. Direct stale-family and unqualified-B rejections also verified. Fresh campaign selected CLI exit receipts: 16/16 expected results (successful exit 0; conflicts exit 3). No cross-device substitution found in retained successful runs.

## Responsibility boundaries

C00–C07 and C09–C11: historical and raw evidence supports frozen contract, discovery, frame transactions, immutable assets, coordinator ownership, device epochs, primitives/Recorder, transitions, evidence snapshots and legacy registry/gate contraction. C08 shares the affected interpreter and cannot be finally closed without FA-01 correction. P01/P03/P04/P07 evidence supports portable proof resolution, publication, preflight and registry. P02/P05/P06/P08 share or depend on the affected runtime/slot behavior. B01 reservation and B02 batch reconciliation/parallel execution have positive direct and historical evidence; B02 inherits the shared execution issue, not a separately reproduced batch-specific defect. V01 historical compatibility is substantiated; V02 positive real-device evidence is substantiated; final closure is withheld. See EVIDENCE_MATRIX.json for requirement-to-artifact mapping and FINDINGS.md for dispositions.

## Required remediation and retest boundary

Resolve FA-01 without loosening the second profile probe, deadlines, action identity or evidence retention. Confirmed frame geometry mismatch must take precedence over transient-focus retry; retain frame evidence, stop and invalidate matching active slot once by CAS. Add mixed-fault regression and positive transient-focus controls, then rerun Runtime and Portable/Contract tests at the corrected commit; a consolidated regression rerun at the corrected HEAD is recommended for clean provenance. No extra live testing is indispensable to reproduce the present failure. After correction, assess whether targeted same-route candidate-wheel requalification is necessary for final sign-off; do not represent the historical campaigns as executions of a new commit.

The Settings tests demonstrate platform-level qualification only. CZN-specific automation, heterogeneous profile transfer, physical-device attestation, external controllers and cross-host operation are not established by these campaigns. Acceptance is not deployment authorization.

## Delivery

REPORT.md, EVIDENCE_MATRIX.json, FINDINGS.md, VERIFICATION.json are the audit deliverables. Additional newly authored scripts and independent test/exit artifacts in this folder are reproducibility evidence. Existing campaign evidence remains in its original isolated directories.

## Independent recheck (current audit session)

The existing final-acceptance artifacts were already present at initial NB inspection. They were retained; this section and the independent_recheck_20261127 JSON entries document a separate audit, not a relabeling of the previous auditor's work. Candidate HEAD, branch, main and dereferenced annotated release tag independently match the required values. GitHub repository metadata was read only.

New auditor-authored recheck.py (not a rerun of verify.py or supplement.py) returned 33/33 successful raw-evidence checks: 26 frozen hashes, 61 legacy definitions, 29 schemas, baseline coverage 308, 26 disjoint shards/1429 JUnit tests and receipts, final targeted XMLs, both wheel source/installed byte provenance, copied 164-file archive and both campaign databases, PNGs, source proof, qualification generations, action intents and request idempotency. All four initial/final content-region image comparisons were exactly equal; 14 distinct portable refs and 28 pre/post frames per campaign; action-span overlap 2.9261398 s and 2.7154326 s. No screenshots left NB. The first script invocation exited 1 due to UTF-16 collection text; corrected only the new script, rerun exit 0.

A newly authored adversarial test uses a different dimension and the resumed-package variant, with a geometry-only negative control. Actual fixture results at 770e1de: expected width 140; actual width 132; height 100. Control captured protected frm_a018f93f5d38, returned needs_agent/GEOMETRY_MISMATCH, slot invalidated generation 2. Mixed fault captured protected frm_b1d3461bbf3f, returned completed with no reason, slot active generation 1. Both performed exactly one injected action; duplicate returned prior receipt. New pytest: 1 passed, 1 failed, exit 1, 11.56 s. This independently confirms FA-01; the issue is not merely inferred from previous narrative. Existing focused-package counterexample and new resumed-package counterexample agree. Existing 21 Runtime and 1004 Portable/Contract results were inspected, not rerun by this session; 1429 applies only to 5a8b262. Current decision remains BLOCKED. No new live testing is indispensable to establish this failure. No source fix or deployment was performed.
