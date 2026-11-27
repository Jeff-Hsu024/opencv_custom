# Independent acceptance findings

## FA-01 — Confirmed geometry drift suppressed by transient focus retry

- Severity: HIGH. Blocking: yes. Verified defect, not a hypothetical concern.
- Requirements: SPEC R03/R06/R13; CONTRACT K04/K05; UC09/UC17; A14. The guarded execution path must fail closed on confirmed geometry/profile mismatch and invalidate the matching active qualification slot.
- Code: `vision_app/runtime.py`, WorkflowRuntime._capture (approximately lines 123–141), WorkflowRuntime._interpret (approximately lines 342–365), final commit 770e1de. _capture takes an actual frame, calls observe(fid), then probes profile again, then validates geometry. A transient PROFILE_UNKNOWN during that second probe prevents the geometry check from running. _interpret catches the matching transient error and observes again. QualificationSlots.invalidate receives no geometry-mismatch signal in this path.
- Independent evidence: `test_focus_geometry_audit.py`; `focus-geometry-audit.xml`, `focus-geometry-audit.log`, `focus-geometry-audit.exit.json` (exit 1, one failing assertion), VERIFICATION.json check focus_geometry_guard. Actual service invocation on an injected, independently qualified B: task ptask_ffffffffffffffffffffffffffffffff, run prun_268a1560bedfdf7128e8b75e09d64ec6. Captured protected frame frm_45ba51086fb6 had actual 140x90 vs required 140x100; second profile probe raised "Cannot establish unique focused package"; subsequent capture returned valid geometry. Task completed with verified action outcome, final frame frm_3f73ff6b85bb; slot stayed active generation 1. The wrong-sized frame remained protected but absent from steps[0].post_observations. Expected: needs_agent, GEOMETRY_MISMATCH, slot invalidated at generation 2. One action only; exact duplicate returned original receipt.
- Scope: shared interpreter, impacts C08, P02, P05/P06/P08 and B02 by dependency. Not evidence of cross-device substitution or replay. Existing positive campaigns use matching geometry and do not contradict this failure.
- Minimal remediation: validate captured frame identity/geometry/rotation before the second profile probe (or make confirmed mismatch take precedence over transient retry); preserve actual frame and terminal evidence, propagate GEOMETRY_MISMATCH to matching qualification CAS once, maintain second profile check, bounded postcondition deadline and existing no-replay rules. Add regression for this mixed fault; test valid-geometry transient focus both pre/post capture, persistent focus unknown and confirmed drift. Rerun impacted suites at corrected HEAD. Do not merely add a retry or relax the guard.
- No indispensable additional live test for this finding: the deterministic service-level counterexample is already sufficient. Corrected wheel may need targeted same-route verification before final closure.

## FA-02 — Historical regression provenance differs from final candidate

- Severity: LOW. Blocking independently: no. Evidence limitation, not a product defect.
- Requirements: V01 and regression preservation; C00 freeze / R16.
- Evidence: 26 shard XMLs and exit receipts at 5a8b262 (1,429 cases); transport-fix.xml at cb76086 (26); post-focus-regression.xml at 770e1de (1,004); no separate process-exit receipt located for the latter two historical invocations. Auditor reran 21 Runtime cases at final HEAD, exit 0. Auditor's new negative case fails separately.
- Remediation: retain explicit tested-commit boundaries, attach exit receipts to future invocations and preferably rerun consolidated tests at the corrected candidate HEAD. No claim of a 1,429-case final-HEAD rerun.

## FA-03 — Qualification coverage limits

- Severity: INFORMATIONAL. Blocking independently: no. Agreed scope boundary, not a verified defect.
- Requirements: V02, platform-level same-profile qualification and evidence integrity; explicit non-goals in SPEC/CONTRACT.
- Evidence: direct Apps and independent Sound campaigns, two explicit Android endpoints, matching Settings profiles, actual 720x1280 screenshots, two independent definitions. No observed cross-device substitution. Independent image checks used decoded pixels and best template correlation, not a second exhaustive multi-match implementation. Raw Store evidence is not an external physical-device identity attestation.
- Remediation: do not generalize to CZN automation, cross-host execution, heterogeneous profiles, arbitrary third-party controllers, or production deployment. Qualify such workloads separately if later required.

## Audit execution notes

The initial verification script encountered mixed frame/ref proof keys and was corrected; both independent raw checks subsequently completed. The first fresh Runtime test collection failed due to missing core in PYTHONPATH; corrected the invocation and retained the failure receipt as well as the successful 21-case run. No production code or original evidence was repaired or modified.

## Independent recheck (current audit session)

FA-01 independently corroborated by a different width-drift scenario and resumed-package ambiguity, with geometry-only control: test_recheck_mixed_fault.py, recheck-mixed-fault.xml, recheck-mixed-fault.log, recheck-mixed-fault.exit.json. Control: 132x100 vs 140x100, needs_agent/GEOMETRY_MISMATCH, slot invalidated generation 2. Mixed fault: protected frame frm_b1d3461bbf3f, completed, slot active generation 1. Exactly one injected action in each; exact duplicate did not replay. HIGH / blocking; SPEC R06/R13, CONTRACT K04/K05, UC09/UC17, A14. Remediation unchanged: check confirmed captured geometry/identity before transient second probe can mask it, preserve evidence, invalidate exact qualification CAS, retain both profile checks and bounded wait. No Android input required to reproduce.

Independent raw checks 33/33 successful. Existing 1429/1004/21 test provenance and scope limitations remain as reported; no new consolidated rerun. The initial recheck script encoding issue was auditor-only, corrected and rerun. Existing final-acceptance artifacts were already present and were supplemented, not treated as newly authored work. No implementation or original campaign evidence was modified.
