# Acceptance matrix
| Gate | Criteria |
|---|---|
| Regression | Original 172 tests and all added tests pass; Core unchanged |
| Persistence | Independent CLI and MCP subprocess restart use same SQLite session and next sequence; interrupted pending receipt stays unknown |
| Lifecycle/scope | Pause/stop reject bound execution; wrong device rejected before action; parallel sessions have isolated sequence/logs |
| Fidelity | Success, failure and timeout recorded; click executed remains semantically unverified; no fake before/after |
| Evidence | Frame survives TTL and transient capacity; same-name asset prior revision digest unchanged; ref metadata resolvable; no base64 in rows |
| Privacy | Typed secret and errors absent in DB; Windows raw UTF-8 annotation round-trip |
| Inspector | Bounded cursor pagination and filters; traceable annotation/checkpoint; known assets and recent errors returned in resume |
| Live | Explicit MuMu idx3; actual pixels; learn templates; navigate two page layers; no persistent settings changed; return to original screen; resume via separate process and append event |
| Delivery | Installed CLI/MCP and skill, independent raw SQLite/evidence integrity check, JUnit and live evidence outside Git; git diff --check, commit main and update local bare; no new worktree/project/branch |
