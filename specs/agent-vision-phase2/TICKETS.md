# Phase 2 Ticket Set
| Ticket | Scope | Acceptance evidence |
|---|---|---|
| REC-01 | SQLite lifecycle, durable pending sequence, device/workspace isolation, cross-process lock | Lifecycle, concurrency, pending and process-restart tests |
| REC-02 | Shared operation boundary, failure/timeout receipts, secret masking, TTL pinning, immutable asset revisions | Failure/redaction and evidence tests; actual invalid crop |
| REC-03 | CLI and MCP adapters, explicit session ID, UTF-8 transport, existing compatibility | Original 172 tests, installed CLI subprocess, downstream MCP discovery/refresh and raw UTF-8 test |
| REC-04 | Inspector, cursor pages, filters, semantic annotation, checkpoint and resume | Pagination and resume tests; actual recovered checkpoint and asset history |
| REC-05 | MuMu reversible navigation, regression, skill, evidence and local Git delivery | Live PNGs and database, independent integrity verifier, JUnit, git diff check and bare main sync |
