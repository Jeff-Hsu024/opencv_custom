# C01 strict Android discovery

Implemented only C01 against CONTRACT v1, the C00 freeze and K08 amendment on
the existing local `feat/agent-vision-multi-device` worktree. Traceability:
UC01, UC09, UC21; R01, R16; A01, A17; F07.

`vision phase9 android-devices --request <UTF-8 JSON file>` and
`vision_android_devices {}` invoke the same DiscoveryService and ObservationService
against the selected shared store. The request is exactly an empty object. Success
uses the frozen `{ok:true,result:{devices:[{device_id,platform:"adb"}]}}` shape,
including an empty list for valid empty discovery. Invalid requests exit 2;
discovery failure exits 3 with DISCOVERY_FAILED and retryable=true; MCP isError
matches the error envelope. Unexpected implementation failures return INTERNAL_ERROR.
Error responses omit subprocess diagnostics.

Strict discovery runs configured ADB typed argv through the existing platform
factory and real Adb adapter, explicitly suppressing the legacy `adb` selector
for the global device list. It never calls legacy get_devices as fallback,
connect, start-server, launch, capture or input. Header, serial, exact state,
row shape and duplicate serials are validated before returning any rows. Only
the exact `device` state is online. Other recognized ADB states are excluded;
malformed output, nonzero status, timeout and missing executable are failures.
The reusable admission helper rejects implicit/alias/malformed serials before
discovery and returns DEVICE_UNAVAILABLE for an exact serial absent online.

The only Core edit replaces the legacy substring state test with exact state
comparison. This fixes offline/unauthorized serials containing the word `device`.
Legacy CLI/MCP envelopes, desktop support, tool definitions/defaults and permissive
empty-on-discovery-failure behavior remain compatible. One additive MCP tool is
present (62 total, original 61 unchanged). The existing compatibility outer gate
remains in place; no downstream ownership, epoch, migration or portability work.

Tests use isolated pytest temporary stores and actual Adb/AdbPlatform adapters,
replacing only subprocess.run through the established platform factory seam.
They assert exact argv, shell=False, transport parity, frozen request/response
schemas, multiple online serials, offline/unauthorized exclusions, malformed
rows, duplicates, command failures, timeout/missing executable, explicit serial
validation, no fallback and unexpected internal errors. These are software
fixtures, not live discovery or multi-device qualification evidence. No device
input or official Store/bundle/evidence mutation was performed. Two authorized
compatible Android devices have not been established by this ticket; V02 remains
an independent live gate.

The initial targeted invocation failed collection because `request` is a reserved
pytest parameter name; renaming the test parameter fixed it before validation.
Final command results and output paths follow below.

## Validation environment and results

Repository root, local Windows PowerShell, Python 3.14.3 in the existing isolated
`.scratch/c00-env`. All runs set `PYTHONPATH=core;.` and set VISION_STORE_DIR to
`.scratch/c01-candidate-store` (contract run: `.scratch/c01-contract-store`).
Per-test stores use pytest temporary directories. No official store is selected.

```powershell
$env:PYTHONPATH='core;.'
$env:VISION_STORE_DIR="$PWD/.scratch/c01-candidate-store"
.scratch/c00-env/Scripts/python -m pytest vision_app/test/test_strict_discovery.py -q --tb=short
# exit 0: 46 passed in 3.11s; targeted-output.txt
$env:VISION_STORE_DIR="$PWD/.scratch/c01-contract-store"
.scratch/c00-env/Scripts/python -m pytest specs/agent-vision-phase9/c00/test_contract.py -q --tb=short
# exit 0: 978 passed in 8.51s; contract-output.txt
```

The C00 run verifies every frozen hash and legacy public interface/default
compatibility without refreshing fixtures or changing the freeze manifest.

```powershell
$env:VISION_STORE_DIR="$PWD/.scratch/c01-candidate-store"
.scratch/c00-env/Scripts/python -m pytest core/test vision_app/test -q
# exit 0: 354 passed in 135.74s (0:02:15); regression-output.txt
git diff --check
# exit 0
```

The final regression run includes all 308 original cases and 46 C01 cases.
An earlier full run passed 353 cases in 139.13s; the full suite was rerun after
the final unexpected-internal-error case and error classification were added.
Output files contain actual pytest output normalized to UTF-8 for review.
No known C01 software acceptance work remains. This commit does not qualify live
devices, satisfy downstream ownership/portability gates, or authorize deployment.
