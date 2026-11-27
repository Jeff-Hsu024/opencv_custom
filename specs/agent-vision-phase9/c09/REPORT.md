# C09 Evidence snapshot and publication seal

This slice implements SPEC R15 and CONTRACT v1 K04 on the existing feature
worktree after C08 (`58b7ce4`). It covers the evidence consistency portion of
UC03, UC13 and UC19 under A02, A06 and A16.

- Recorder session, event and annotation mutations advance a per-session
  revision in the same SQLite transaction. Annotation and checkpoint writes
  use the shared metadata lock. Frame protection revisions advance in the
  existing lifetime sidecar before an index change, so restoring protection
  to its original value still invalidates an in-flight snapshot.
- The Builder captures source metadata and file identities under metadata and
  reuses the Store's OS-backed frame pins. Content hashing, template matching
  and bundle staging happen outside the metadata lock. Publication rechecks
  the seal and revisions immediately before the atomic bundle rename. Recovery
  child workflow publication uses the same check.
- New bundles retain a source seal beside the definition, plan and templates.
  Workflow IDs and public result shapes are preserved. Preexisting bundles
  without the seal remain readable and use the same pinned validation path.
  Later source changes invalidate sealed workflows for new validation.
  Historical inspection leaves published files intact.
- The task-local cache uses both complete content seals and a metadata
  comparison on hits. Concurrent evidence changes surface as
  `EVIDENCE_CHANGED` through the existing CLI and MCP error envelopes.

Tests exercise a cooperating annotation writer while validation is in
progress, an annotation after staging but before publication, frame retention
under cleanup, and a protection revision that changes back to its original
value. The existing tamper matrix covers frame, ref, annotation, retained
asset, template and plan changes after a cached pass.

The C11 compatibility gate remains in place. This slice covers software
verification with isolated stores. Live Android input and independent
two-device qualification are outside the reported results.

## Verification

Commands ran from the Windows repository root with `PYTHONPATH=core;.` and
Python from `.scratch/c00-env/Scripts`. Each invocation used a separate
temporary candidate `VISION_STORE_DIR`.

| Command | Result |
| --- | --- |
| Compare LF-normalized bytes with `c00/FREEZE.json` | Exit 0, all 26 hashes matched |
| `python -m pytest vision_app/test/test_frame_transactions.py vision_app/test/test_workflow.py vision_app/test/test_agent_interface.py vision_app/test/test_recovery.py specs/agent-vision-phase9/c00/test_contract.py -q --tb=short` | Exit 0, 1,042 passed in 129.53s |
| `python -m pytest core/test vision_app/test -q` | Exit 0, 413 passed in 442.65s |

The initial regression run caught the legacy `index.json` shape assertion.
It was still running when the protection revision storage moved to the
lifetime sidecar, and it also reported two subprocess failures, for 3 failed
and 410 passed in 450.71s (exit 1). The three
affected cases were rerun together on the corrected tree, exit 0 with
3 passed in 11.52s.
