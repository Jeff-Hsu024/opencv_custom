# C02 frame transactions and active pins

Scope: UC13/UC14, R07/R15, A06/A09/A16, F06; frozen CONTRACT v1
K03/K04 and C00 K08 amendment. Local existing feature worktree only.

`vision_app.metadata.metadata_transaction(store)` supplies a shared short,
reentrant metadata boundary. Permanent hashed lock files use canonical store
paths (including Windows case normalization), actual OS locks and process-local
thread exclusion. Lifetime owners are acquired before metadata; cleanup probes
them nonblocking. Metadata is never held across capture, polling, matching,
PNG encoding/publication or image decoding. The existing compatibility outer
gate is unchanged and remains required until C11.

FrameStore serializes save publication, protection, unprotection, reads and
retention. An additive `frame_lifetimes.json` records durable ID reservations
and active pins without changing `index.json` or FrameRecord serialization.
IDs are never reused, including after failed publication or later retention.
Save reserves an ID, publishes fsynced PNG bytes outside metadata, then commits
the index pointer. Cleanup commits pointer removal before deleting bytes and
recovers unindexed PNGs only after excluding live claims and pins. Protected
frames remain outside the transient cache budget. A crash can leave orphan
bytes or an abandoned reservation, but cannot publish a pointer before bytes.

`pin_frames(ids, device_id=...)` yields coherent records with OS-owner lifetime
retention. `load_image` uses this context while reading and decoding outside
metadata. Cleanup preserves live owners and reconciles only owners whose actual
lock it acquires; process death and normal context exit are both tested. Future
asset/ref/evidence consumers use this seam in their assigned migration tickets;
C02 does not claim to complete C03/C06/C09 or remove the outer gate.

The existing rotation-staleness regression deliberately overwrote an existing
frame ID to construct corrupt fixture metadata. Its setup now changes only the
temporary fixture index under metadata; its original validation assertions
remain. This preserves the case while enforcing the frozen no-overwrite rule.

## Concrete validation

All tests use pytest temporary stores and `.scratch/c02-candidate-store`, with
`.scratch/c00-env` Python and `PYTHONPATH=core;.`. No device input, official
Store, immutable acceptance bundle, registration evidence, coordinator status
file, Core source, CLI/MCP interface or source-device guard was changed.

```powershell
$env:PYTHONPATH='core;.'
$env:PATH="$PWD/.scratch/c00-env/Scripts;$env:PATH"
$env:VISION_STORE_DIR="$PWD/.scratch/c02-candidate-store"
python -m pytest vision_app/test/test_frame_store.py vision_app/test/test_frame_transactions.py -q
# exit 0: 22 passed in 19.13s; targeted-output.txt
python -m pytest specs/agent-vision-phase9/c00/test_contract.py -q --tb=short
# exit 0: 978 passed in 6.56s; contract-output.txt
```

New cases execute real spawn barriers: four concurrent save/protect/unprotect/
cleanup writers retain all 48 rows and correct PNGs; two colliding publishers
produce exactly one winner; live publication claims resist orphan cleanup;
live pins survive cleanup and killed owners reconcile. Abrupt process exits
before PNG, after PNG, after index, and after cleanup index removal verify
orphan-only ordering and protected retention. A codec hook probes the real
metadata lock from another thread during encoding/decoding; JSON shape and PNG
SHA-256 equality to unchanged encoding verify legacy storage compatibility.
Nested metadata and thread pin/cleanup are exercised too. C00 tests verify
frozen hashes and public defaults without regenerating frozen assets.

An initial full run was interrupted (output retained in
`initial-interrupted-output.txt`) after the Windows canonical-path lock change
was made while its processes were running. That mixed-version run is not
acceptance evidence; its failure markers included the independently reproduced
rotation fixture setup described above. The source was held fixed for the
subsequent complete regression run reported below.

```powershell
python -m pytest core/test vision_app/test -q
# exit 0: 365 passed in 279.27s (0:04:39); regression-output.txt
git diff --check
# exit 0
```

This includes all 308 original cases, 46 C01 cases and 11 new C02 cases.
The full run was slower than C01's recorded 135.74 seconds; C02 adds durable
pin transactions to image reads and process/crash tests, and makes no throughput
claim. Output files are actual pytest output normalized to UTF-8. No known C02
software acceptance work remains. The delivery commit is supplied in the
worker completion receipt; live device qualification, independent acceptance
and downstream migration/ownership gates remain outside C02.
