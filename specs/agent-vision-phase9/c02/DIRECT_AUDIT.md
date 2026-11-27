# C02 direct-session follow-up audit

External ChatGPT session, direct Queqiao NB shell edits; no Worker dispatch.
Parent implementation: f6b0415674a162860526d987154033166237d295.

Finding: on NB's case-insensitive filesystem, the original reservation used
case-sensitive JSON keys. A process reserved CaseAlias before writing PNG,
while a second process using casealias could reserve and publish the same
physical file. Both could then commit divergent index rows. Actual filesystem
probe returned case_insensitive=True, os.path.normcase('Probe')='probe'.

Added a real spawn-process test which holds the first publication at an event
barrier before PNG publication. Original implementation failed with DID NOT
RAISE StoreError (1 failed, 11 deselected). Fix checks native normalized
frame-ID path keys across existing index and durable reservation keys while
holding metadata. It preserves exact public frame ID spelling and JSON shape.
The test also verifies winner bytes and permanent reservation after retention.

Direct isolated candidate-store validation:
- New regression: 1 passed, 11 deselected in 4.19s, exit 0.
- Frame Store, frame transactions, C00 contract: 1001 passed in 24.20s, exit 0.
- Existing C02 full suite evidence: 365 passed in 279.27s before this fix;
  the full suite was not rerun after this small fix in this turn.

Scope: Windows native path case normalization, NB verified. Case-insensitive
non-Windows filesystems not qualified by this fix. No Android input, official
Store, main, release, or deployment changes.
