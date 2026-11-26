# C03 immutable scoped asset revisions

Implemented C03 on the existing `feat/agent-vision-multi-device` worktree
against CONTRACT v1 K01–K04 and the C00 K08 amendment. Resumed the preserved
handoff and verified its tracked patch and two new files against the retained
copies before editing.

## Acceptance evidence

- Same-label registrations for different fixture serials and sessions resolve to
  their exact scoped revisions. Tests check the canonical ID, source-frame
  digest, crop dimensions and region, and exact immutable PNG bytes. Foreign
  device/session use fails and resolution never falls back to the legacy alias.
- Spawned workers race scoped and legacy commits in one candidate Store. Real
  process exits at blob publication, pointer commit, and each legacy projection
  replacement exercise interruption boundaries. Upgraded readers return the
  committed revision and can repair compatibility files. A late repair verifies
  the observed generation before replacing files. A raw reader of the two
  compatibility files can see a mixed pair between replacements, so the SQLite
  pointer is authoritative for upgraded readers.
- Legacy named API records retain their original shape and last-committed alias
  semantics, including Windows case variants. Hashes of the fixture historical
  PNG and JSON remain identical through reads and validated lazy adoption.
- The Recorder seam takes an exact revision, verifies the source and blob
  digests while pinned, and retains the same PNG digest in its evidence item.
  A moved alias cannot change that item. Source frame pins span registration
  through commit and explicit use, and owner-death reconciliation clears stale
  pins. Explicit use fails if the source frame has expired. A stopped session
  cannot publish a revision even when encoding began while it was active.
- C03 exposes asset alias generations and the exact revision seam. Recorder
  operation migration and the full dependency snapshot/proof commit belong to
  their successor tickets. The compatibility workspace gate remains in place.

## Verification

All invocations ran from the repository root in Windows PowerShell using the
existing candidate Python and a fresh temporary `VISION_STORE_DIR` per command.
The tests did not operate any devices or use the official Store. Device serials
in C03 tests are fixture identifiers.

```powershell
$env:PYTHONPATH='core;.'
$env:VISION_STORE_DIR=Join-Path ([IO.Path]::GetTempPath()) ('vision-c03-'+[guid]::NewGuid())
& .scratch/c00-env/Scripts/python.exe -m pytest vision_app/test/test_asset_revisions.py vision_app/test/test_strict_discovery.py -q --tb=short
& .scratch/c00-env/Scripts/python.exe -m pytest specs/agent-vision-phase9/c00/test_contract.py -q --tb=short
& .scratch/c00-env/Scripts/python.exe -m pytest core/test vision_app/test -q
```

| Check | Exit | Result | Evidence |
| --- | --- | --- | --- |
| Scoped asset and strict discovery | 0 | 69 passed | [Output](targeted-output.txt) |
| Frozen contract | 0 | 978 passed | [Output](contract-output.txt) |
| Full Core and Vision App regression | 0 | 389 passed | [Output](regression-output.txt) |
