# Phase 8 — Frozen Acceptance Criteria
Status: planned. All metrics must be recorded as actual, target, NOT_MEASURED or NOT_ATTEMPTED.

| Gate | Criterion | Required evidence |
| --- | --- | --- |
| A0 Baseline | main/tag/local bare still resolve 645747e, isolated worktree/test store and venv | git refs, paths, baseline manifest; original Registry/receipt hashes unchanged |
| A1 Regression | all 258 baseline tests pass plus new tests | JUnit XML, command, test counts, no hidden skips |
| A2 Schema/errors | known annotation fields enumerated, unknown rejected with actionable error, no mutation/secret leak | tools/list schema, CLI/MCP negative/positive tests |
| A3 Transition | exactly one fresh scoped click, normal ordered Recorder primitive events, post frame and explicit Agent semantic annotation, Builder works unchanged | event/annotation/ref IDs, hashes, compiled bundle and offline validation |
| A4 Failure/idempotency | zero/multiple match, stale, wait/capture error, click unknown, interrupted/duplicate/concurrent request, mismatched ID payload | count real attempted actions in fixture; terminal receipts; no replay |
| A5 Payload | Builder summary <=8 KiB ordinary four-step success and >=70% reduction vs full; details/full retain evidence | same bundle ID, byte measurement, full response regression, failure reason visible |
| A6 Images | actual pixels render through supported path; zero Base64 text pollution in tested agent path | MCP content shape, image evidence, connector boundary report; no unverified external fix claim |
| A7 Parity | inventory all 57 baseline tools, shared supported options tested, deliberate exceptions documented | schema/help matrix, parity tests, original calls continue working |
| A8 Profiling | actual stage counts/durations and before/after comparison; reduced duplicate immutable validations if safe | profiling report, tamper tests; if not safe defer with reason; live safety checks unchanged |
| A9 Inspector | recovery anchor/path marker example, bounded asset query as justified | docs/schema checks, pagination/provenance tests |
| A10 Live | comparable 4-transition recorded path, 3 repeat runs (12/12), known recovery and full restart, no-match handoff, restore original page | raw task/run journals, independently recomputed OpenCV checks, source hashes |
| A11 Agent efficiency | <=20 calls on comparable 4-step exploration target, one Runtime invocation after qualification, report timing and bytes | external invocation count incl start/stop/annotation/checkpoint/inspector; separate internal event count; same task scope and count definition |
| A12 Fresh Agent | independent baseline/candidate sessions if available; actual cross-session handoff only if performed | session IDs/report, tool traces, context constraints; otherwise NOT_ATTEMPTED |
| A13 Delivery | documented failures/limits, candidate worktree commits, no official installation/merge before user review | clean candidate branch, local bare sync, evidence manifest, final report |

Baseline reported 35 calls / 109.64 s exploration; 1 call / mean 13.38 s runtime; recovery task 46.54 s. These are report metrics not controlled repeated benchmark. Compare same task and device/profile; count failed calls and asset learning, exclude onboarding/build/registration from exploration metrics as in baseline, report excluded costs separately. Never count internal primitives as external agent calls; never equate bytes with tokens. For actual device work use only 127.0.0.1:16480, reversible navigation, no resource/account/settings changes. Keep original store and official deployment untouched; separate candidate store and installed skill. Report transport timeout distinctly and inspect original request ID; asynchronous execution API out of scope.
