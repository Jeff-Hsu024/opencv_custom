# C06 primitive and Recorder migration

C06 covers UC01, UC08, UC13, UC15 and UC16 under R01, R07, R10, R11
and R14. It uses the C03 asset revision store, C04 owner and claim ledger,
and C05 epoch and pending intent primitives.

- CLI `phase9 scoped-find` and `phase9 guarded-click` share request validation
  and execution with the equivalent MCP tools. Scoped matching reads the
  requested immutable revision. Recorder events retain that revision and its
  PNG digest even after another revision replaces the alias.
- Snapshots and wait observations stamp the current device epoch under the
  device owner. Recorded matches carry the session scope. Legacy input uses
  the same owner and advances the epoch before platform dispatch, including
  attempts that time out or return failure.
- Guarded click persists pending intent before input. A successful dispatch
  returns `completed` with `executed_unverified`, and duplicate IDs return a
  durable receipt. An interrupted pending click retains an unknown outcome.
- The compatibility gate still serializes these entry points and Recorder
  status changes. An old frame can be searched, with a null epoch for
  historical unstamped frames. An unstamped reference is ineligible for
  guarded dispatch.

## Verification

Commands used the repository's `.scratch/c00-env` Python on Windows with
`PYTHONPATH=core;.` and isolated temporary stores.

| Check | Result |
| --- | --- |
| Primitive, epoch, coordinator, Recorder and Transition tests | 31 passed |
| Primitive and discovery tests plus frozen contract tests | 1,029 passed |
| Full Core and Vision App regression | 405 passed in 370.91s |

The tests use synthetic serials and an injected platform. A real subprocess
drives the MCP adapter while a raw CLI client contends against the same store
and serial. A second subprocess test kills the caller after the injected
click and confirms that a duplicate request reconciles the intent without
another dispatch. No Android device input or live qualification was performed.
