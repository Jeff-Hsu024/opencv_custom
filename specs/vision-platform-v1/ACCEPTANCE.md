# Acceptance matrix
Baseline e1b132f: 24 tests previously observed PASS, not rerun in planning. This is an acceptance specification, not frozen executable tests.

| Gate | Tickets | Evidence |
|---|---|---|
| A | CORE-01..04 | Synthetic BGR PNG; adapter mocks; ROI validation; one capture; encode/save round trip; legacy compatibility |
| B | CORE-05..08 | Match score/bbox/NMS/ROI offsets, OCR color and bounded loops, deterministic comparison and timeout |
| C | CORE-09..10 | Typed argv/returncode/explicit serial, timeout, desktop failsafe; CORE-10 P1 optional for baseline gate |
| D | CORE-11 | All existing and new tests, dependency boundary, real read-only NB capture/crop |
| E | PKG-01..02 | Fresh install, headless ADB, legacy entry/scripts, Go/Wails smoke when available |
| F | CLI-01..05 | Actual subprocess JSON and artifact, persistence, assets/refs, nested transforms, exit codes, waits |
| G | MCP-01 | Real Queqiao discovery, actual image visible, metadata and device scope |
| H | E2E-01 | Controlled live observation, mapped action and observed postcondition |
| Optional | OPT-01 | Benchmark and correctness |

Coordinate fixture: 720x1280; crop [100,300,400,500] => 300x200; local (60,80) -> (160,380). Resize to 150x100; local (30,40) -> (160,380) under documented mapping. Nested crop composes; reject invalid local point, wrong device, stale ref, changed rotation where detectable. Half-open coordinates.
Core command: from root set PYTHONPATH to core and root; isolated Python -m pytest core/test -q; subprocess uses sys.executable. git diff --check; no SDK binaries, generated reports. Package fresh venv pip install .; CLI real subprocess JSON parse, PNG dimensions. MCP path-only output is NOT PASS.
Real NB: verify explicit 127.0.0.1:16480 only, read-only screenshot/crop first; no other serials, daemon restart, account mutation or physical input. Controlled test screen and scoped action required for mutation. Record before/after, receipt, actual visible image. If unavailable, mark BLOCKED with concrete tool evidence; mock != real.
Independent verifier records commit, environment, commands, counts, artifacts, real/mock distinction. Full E2E requires gate H, not only unit tests.
