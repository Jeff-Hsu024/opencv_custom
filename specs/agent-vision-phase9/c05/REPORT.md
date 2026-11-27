# C05 durable device action epoch

C05 implements the application-layer epoch primitives for UC16, UC08 and
UC09 under R11 and R07, with acceptance references A12 and A06 and finding F02.
The implementation follows CONTRACT v1 K03 and K04 with the frozen K08 amendment.

- The exact device serial keys a monotonic epoch in the existing
  coordinator SQLite database. An active device owner is required to stamp a
  capture or advance an epoch. Derived frames and refs inherit their source
  epoch, including when derived after an intervening input. The ref sidecar
  also records the nullable session ID.
- Frame and ref publication writes the sidecar under the same metadata lock
  before exposing the legacy record. A crash between the two writes can
  reserve an otherwise invisible ID. Published stamped IDs cannot be reused.
  Legacy frame/ref JSON retains its original shape.
- The guarded click service checks scope, epoch, age and existing frame
  geometry under the device owner. It pins the source frame through input.
  A pending step, incremented epoch and
  running claim receipt with unknown outcome commit in one SQLite
  transaction. After committing, the same step cannot dispatch again, and
  an unresolved unknown outcome blocks subsequent steps in that claim.
- Legacy clicks enforce epoch and scope when a ref has a stamp. Unstamped
  references and frame coordinates retain their legacy behavior. Click,
  swipe, text and key input through the action service advance the epoch
  before dispatch even if the platform subsequently fails or times out.
  Repeated explicit ID-less calls each advance the epoch.

Owner-aware captures and guarded actions are available to service callers.
CLI/MCP and Recorder cutover remains C06 work. The compatibility outer gate
remains through C11.

## Verification

Commands ran from the repository root on Windows PowerShell with
`.scratch/c00-env` Python, `PYTHONPATH=core;.` and distinct temporary
`VISION_STORE_DIR` values.

```powershell
$env:PYTHONPATH='core;.'
$env:PATH="$PWD/.scratch/c00-env/Scripts;$env:PATH"
python -m pytest vision_app/test/test_device_epochs.py vision_app/test/test_coordinator.py vision_app/test/test_frame_transactions.py vision_app/test/test_asset_revisions.py -q
python -m pytest specs/agent-vision-phase9/c00/test_contract.py -q
python -m pytest core/test vision_app/test -q
git diff --check
```

| Check | Exit | Result | Evidence |
| --- | --- | --- | --- |
| Epoch, coordinator, frame transactions and asset revisions | 0 | 46 passed in 51.69s | [Output](targeted-output.txt) |
| Frozen contract and legacy transport surface | 0 | 978 passed in 12.74s | [Output](contract-output.txt) |
| Full Core and Vision App regression | 0 | 400 passed in 328.70s | [Output](regression-output.txt) |
| `git diff --check` and `git diff --cached --check` | 0 | No whitespace errors | |

The epoch fixtures use synthetic serials, temporary stores and a platform
stub. They exercise the application input and capture seams, real SQLite and
real owner locks. A subprocess stops at a barrier immediately after committing
pending intent and is killed. The parent directly reads the intent and epoch
from SQLite, then reopens and reconciles the abandoned claim without input.
Neither Android device input nor live qualification was performed.
