# Phase 8 — Implementation Ticket Set
Status: planned, not dispatched. Baseline tag agent-vision-fresh-qualified-20261126. All implementation occurs in feat/agent-vision-phase8. No Orca DAG or new projects. Every ticket: focused regression, diff check, explicit evidence; no unrelated changes.

| ID | Owner boundary | Dependencies | Deliverable | Acceptance |
| --- | --- | --- | --- | --- |
| AO-00 | Baseline + isolated harness | none | isolated venv/store/server, baseline fixture snapshot, tool/call/byte measurements | Frozen tag/main unchanged; original store read-only; reproducible baseline and 258 tests |
| AO-01a | Recorder annotation contract | AO-00 | exact schema, shared validation and errors | valid legacy values accepted; extra fields named; no mutation; no secret values |
| AO-01b | Adapter error mapping | AO-01a | consistent CLI/MCP structured domain errors | invalid fields not INTERNAL_ERROR; unexpected faults still internal; tests |
| AO-02a | Recorder lock boundary | AO-00 | private locked execute, public behavior unchanged | no nested lock, original recorder tests, concurrent sequence uniqueness |
| AO-02b | Transition service/journal | AO-02a, AO-01a | idempotent trans ID, bounded snapshot/find/click/wait/post chain | exact evidence, one click, no match/ambiguous/stale/timeout/crash, no semantic PASS |
| AO-02c | Transition CLI/MCP | AO-02b, AO-01b | typed tools/flags and compact receipt | parity, valid image content, no base64 text, source Builder compiles |
| AO-03a | Response projections | AO-00 | summary/detail/full projection contract and functions | same IDs/status, preserve all evidence; legacy default full; bounded bytes |
| AO-03b | Response adapter integration | AO-03a, AO-01b | flags/schema for selected large responses | legacy clients pass, explicit summary, pagination, full exact compatibility |
| AO-04a | Image transport diagnosis | AO-00 | trace actual MCP wrapper, native vs connector boundary | actual reproducer and layer attribution; no claim external fix |
| AO-04b | Image response controls / guide | AO-04a, AO-02c | metadata-only optional, correct content forwarding and fallback | actual PNG rendered, no Base64 text/log, legacy image compatibility |
| AO-05a | Adapter parity inventory | AO-00 | matrix of baseline 57 tools/CLI flags/defaults | actual schema/parser extraction; deliberate differences documented |
| AO-05b | Shared overlapping options | AO-05a, AO-01b | parity for supported parameters and validation | cross-adapter same behavior, no new action types, old flags preserved |
| AO-06a | Task validation profiling | AO-00 | stage timings/counters, comparable primary/recovery baseline | identify measured duplication, no sensitive payloads, no behavior change |
| AO-06b | Task-scoped reuse | AO-06a | cache only proven safe immutable verification within lock | identical safety decisions, tamper tests, reduced duplicate work; no live data cache |
| AO-07a | Recovery/Inspector usability | AO-01a, AO-03a | anchor guidance, bounded asset evidence query if justified | deterministic pagination and provenance; no added annotation duplication |
| AO-07b | Agent documentation | AO-02c, AO-03b, AO-04b, AO-05b, AO-07a | README/SKILL/refs with new routing and exact schemas | no stale instructions; tool discovery, links and installed isolated skill check |
| AO-08a | Regression + controlled live A/B | all previous implementation tickets | full regression, controlled 4-step exploration/replay/recovery | ACCEPTANCE.md; no original store mutation, final page restored |
| AO-08b | Fresh Agent qualification/report | AO-08a | independent session A/B if available, metrics and limitations | evidence-based status; no fake token or agent metric; user review before merge |

## Boundaries and sequencing
AO-00 first. AO-01, AO-02a, AO-03a, AO-04a, AO-05a, AO-06a can be reviewed separately after harness; no concurrent mutation of overlapping adapter files without coordination. AO-02b owns application service, not Core or adapter schema. AO-02c and AO-03b/AO-05b coordinate common adapter files sequentially or via explicit integration review. AO-06b only proceeds if profiling justifies it and tamper tests hold; otherwise document deferred optimization. AO-08 is independent acceptance, not self-certification by implementation. Do not merge into main or install candidate into official skill/MCP environment until approval.
