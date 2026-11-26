# Repository agent instructions

For visual automation requests, read [skills/agent-vision/SKILL.md](skills/agent-vision/SKILL.md) first and load only the referenced playbook sections needed for the task. It is the canonical skill; do not recreate the workflow machinery or use a separate raw ADB macro when the existing Vision application tools suffice.

For development, follow the relevant `specs/` contract. Keep agent-specific state in `vision_app/`, not Core. Preserve CLI/MCP compatibility, use the same store across adapters, and test changes with `python -m pytest core/test vision_app/test -q` (from repo root with `PYTHONPATH=core;.` on Windows). Do not modify real acceptance evidence, immutable bundles or other device instances during tests. Use actual tool results for claims. Do not treat a single successful navigation POC as production qualification.
