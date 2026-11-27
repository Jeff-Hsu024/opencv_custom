# C00 contract fixture freeze

C00 contract work completed on the existing local feature worktree
`feat/agent-vision-multi-device`, planning parent
`9a3bffcf9b8a2d5090343121d01cceda74a9456e`. No production source, official
Store, main, tag, deployment or device input was changed. The unrelated preexisting
untracked `IMPLEMENTATION_STATUS.md` was left untouched. No downstream dispatch.

## Actual validation

All 29 request and 29 response operation schemas passed
`jsonschema.Draft202012Validator.check_schema` using jsonschema 4.26.0.
All original four positive/ten negative examples passed, plus 317 supplemental
request examples (31 positive, 286 negative) and 556 response shape examples
(239 positive, 317 negative). Request examples roundtrip an actual UTF-8 request
file and MCP argument envelope through the same validation/default normalization.
The complete C00 suite passed **978 cases in 5.81 seconds**; output is
`contract-output.txt`. The production Phase9 CLI/MCP operations do not exist yet;
these are executable transport/schema design fixtures, not Phase9 invocation or
live acceptance evidence.

The unchanged regression suite passed **308 cases in 147.87 seconds** in a new
candidate virtual environment; output is `baseline-output.txt`. Baseline source
is `bfbec17fe55b25a2ea7ddbd9051cc3937ccd3efb`. Git tree objects at that baseline
and the planning HEAD were identical: core
`85a322296ca5b3ec318cc06e106671b26980eb49`, vision_app
`e59244c196172ea146b412e4820d6f24bb54c215`. Working-tree source diff against
that baseline was empty. Existing tests use temporary stores and fake device
effects; existing subprocess device discovery is read-only. No official Store
copy or actual device workflow qualification was performed.

`LEGACY_BASELINE.json` captures all **61** actual MCP tool definitions, their full
input/default shapes, the complete recursive CLI parser/default surface, actual
CLI/MCP devices and empty-asset responses, unknown-tool error, and actual fake-frame
MCP snapshot defaults and metadata-only projection. Dynamic frame IDs, times and
temporary paths are explicitly replaced by named placeholders; codec-dependent
PNG byte counts are normalized, while decoded pixel shape/hash are retained.
Legacy default image-first content order remains frozen; new K01 metadata-first
rules apply only to additive APIs. The compatibility test permits additive tools
and parser commands while checking every frozen legacy definition/default.

`SEMANTIC_EXAMPLES.json`, `semantic_model.py` and `STATES.md` freeze qualification
slot CAS/revoke/drift/restore/duplicate rules; owner-dependent batch reconciliation;
batch precedence; immutable terminal receipts; lock ordering; storage publication,
pinning, retention and evidence-revision commit rules. Additional executable
vectors cover exact disjoint ID prefixes, golden child task/run hashes, atomic
all-child collision reservation, reserved-child rejection, response-only identity,
array-order identity, guarded ref scope/epoch, and CLI exit/MCP isError mapping.
These pure oracles are design tests. They do not mock a real proof verifier,
qualify OS/SQLite locking, prove multiprocess concurrency, or authorize input.
Those implementation/integration/live gates remain with C01–V02; the compatibility
outer gate remains until C11.

## Explicit design amendment

CONTRACT K08 records contradiction evidence and its resolution before any source
implementation:

1. K02 required duplicate_request=true for duplicate qualification commits but
   omitted that field from its otherwise closed result-key catalog. Commit/revoke
   responses now explicitly require the boolean; immutable record inspection
   returns the original commit record. Duplicate projection never mutates a slot.
2. K02 required summary counts and IDs while omitting child bodies. Batch summaries
   explicitly retain `child_ids` with device/task/run IDs; task summaries retain
   completed_steps and run_id. Response collection typing is frozen in
   `RESPONSE_SCHEMAS.json`, including the previously unspecified digest-array type.
3. Actual Draft 2020-12 validation of the original preflight schema accepted both
   a portable ID and serial suffixed with LF, contrary to exact serial/namespace
   contracts. All **57** request regex patterns now append `(?![\s\S])` after `$`.
   The original schema is preserved in `ORIGINAL_REQUEST_SCHEMAS.json`; a test
   reproduces original acceptance, verifies amended rejection, and proves that
   removing this suffix yields the byte-content-equivalent original JSON object.
   No request fields, defaults, limits, names or original examples changed.

Only SPEC, CONTRACT and request-schema hashes changed in the planning manifest.
Original use-case/example hashes remain unchanged, and all original hashes are
retained in `FREEZE.json`. Response steps intentionally retain the existing open
legacy evidence extension shape; target epoch and other known target fields are
typed, while semantic chronology and complete proof remain verifier obligations.
Shape examples alone are not valid trial proof, a slot enrollment, or a semantic
PASS assertion about any device.

Current UTF-8 LF-normalized normative hashes:

| Asset | SHA-256 |
|---|---|
| SPEC.md | 6011ce89ad766a6be1c3ed3137a7c0900d273a943ab10ad472c49fdcb583d32d |
| CONTRACT.md | c032178e4d072058bac98f9132f3c37b6e56d3363ead42fcd6574aafacd8d701 |
| CONTRACT_SCHEMAS.json | be3d1b3fbd88fbfda43320bc7abbc0ddeeb16beaa7af68d31274850310c9a415 |
| CONTRACT_FIXTURES.json (unchanged) | 5f6e5e6adab8dc74e9fa22bc098e546690f73213a775e39e54c8cd4aae75b49a |

`FREEZE.json` records all nine planning files and every supplemental acceptance
asset, generator, oracle, baseline capture, output and environment receipt.
The report and hash manifest exclude themselves to avoid recursive hashes.
`freeze.py` is an explicit refresh utility; tests never rewrite frozen assets.

## Commands and environment

Run from repository root in PowerShell. The isolated environment is
`.scratch/c00-env`, Python 3.14.3; exact installed packages are in
`candidate-requirements.txt`. Hostname returned `user`; Orca worktree receipt
confirms local execution, project/repo/parent IDs and existing child worktree.
No remote environment, new project or extra worktree was created.

```powershell
python -m venv .scratch/c00-env
.scratch/c00-env/Scripts/python -m pip install --no-cache-dir pytest jsonschema opencv-python numpy Pillow requests beautifulsoup4 lxml pyautogui allure-pytest
$env:PYTHONPATH='core;.'
$env:PATH="$PWD/.scratch/c00-env/Scripts;$env:PATH"
$env:VISION_STORE_DIR="$PWD/.scratch/c00-candidate-store"
python -m pytest core/test vision_app/test -q
# 308 passed in 147.87s (0:02:27)
.scratch/c00-env/Scripts/python specs/agent-vision-phase9/c00/baseline.py
.scratch/c00-env/Scripts/python specs/agent-vision-phase9/c00/build_assets.py
.scratch/c00-env/Scripts/python specs/agent-vision-phase9/c00/freeze.py
.scratch/c00-env/Scripts/python -m pytest specs/agent-vision-phase9/c00/test_contract.py -q --tb=short
# 978 passed in 5.81s
git diff bfbec17fe55b25a2ea7ddbd9051cc3937ccd3efb --exit-code -- core vision_app
# exit 0, no output
git diff --check
# exit 0; only Git LF/CRLF conversion notices
```

System Python initially lacked jsonschema. The first candidate pip attempt hit a
permission-denied cached PyAutoGUI wheel; `--no-cache-dir` completed successfully
without changing system/official Python. Initial generator mistakes were corrected
before the final green run. Regeneration and freeze are maintenance actions, not
steps required for ordinary test execution. No real acceptance evidence, immutable
workflow bundle, source-device proof, or other device instance was edited.
