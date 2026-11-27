# Vision Platform (opencv_custom)

Evidence-driven visual automation for Android/ADB and desktop/Robot. An LLM explores unknown UI, captures evidence and defines reusable workflows; deterministic OpenCV execution handles known paths and explicitly qualified recovery routes.

**Agent entry point:** [Agent Vision Skill](skills/agent-vision/SKILL.md). For repository-aware agents, [AGENTS.md](AGENTS.md) routes to the same skill. Do not load every reference at once.

## Architecture

| Layer | Responsibility |
| --- | --- |
| Core / PlatformService | Generic device actions and OpenCV operations; no agent state |
| Vision Application / CLI / MCP | Frame and asset store, scoped references, observation and verified action primitives |
| Recorder / Inspector | Persistent exploration events, annotations, checkpoints and resume context |
| Workflow Builder | Explicit evidence-bound, immutable workflow definitions and offline checks |
| Runtime | Fresh state guards, unique target matching, scoped clicks and verified postconditions |
| Recovery / Lifecycle | Separate recovery proposals, live qualification, version management and exact-parent links |
| Execution Orchestrator | Execute active workflow, optionally one qualified recovery and one full restart |

A known task uses the Orchestrator; an unknown task uses recorded exploration. The Recorder is not a macro recorder. Offline validation is not live qualification; a successful click is not semantic success.

## Installation

Python 3.10+ is declared by the package. In the repository root:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\vision.exe --help
```

Android requires a working ADB installation and the intended device connected. Use the existing ADB tools or configure PATH/ANDROID_HOME appropriately. For desktop primitives, install the optional desktop dependency (`pip install -e ".[desktop]"`). Do not install another toolchain if the installed environment works.

Use a single absolute store directory for CLI, MCP and all agents. For a PowerShell session:

```powershell
$env:VISION_STORE_DIR = Join-Path (Get-Location) ".vision_store"
vision devices --json
vision lifecycle list
```

If not using an activated venv, replace `vision` with its installed executable path. The NB deployment already has an installed venv; see [Transport & CLI](skills/agent-vision/references/transport.md#local-cli-on-nb).

## MCP / agent setup

The package exposes `vision-mcp`, a UTF-8 stdio MCP server. Configure your MCP client to launch that executable with `VISION_STORE_DIR` set to the same absolute directory as CLI. Discover tools via `tools/list`; do not assume a client-specific config format. On Queqiao NB, use the existing `vision-platform` server through the MCP extension, not a second server or a different store.

Install the canonical skill by copying the entire `skills/agent-vision/` directory (including references) into the agent's supported skill directory. On the NB environment this is `~/.agents/skills/agent-vision/`. Loading the skill does not authorize device actions. See [NB transport](skills/agent-vision/references/transport.md).

## Quick start: known task

1. List registered families and inspect the relevant family. Confirm device, profile, active version and current generation; choose a family only if it matches the requested goal.
2. Generate a unique task ID. Execute once with the generation you actually read. Enable recovery only if within the requested scope.
3. Inspect the same ID after a disconnect or timeout; never generate a fresh ID to compensate.

Example, only for the existing NB demonstration family (verify its current generation first):

```powershell
vision lifecycle inspect --family czn-stage-settings
$task = "task_" + [guid]::NewGuid().ToString("N")
# Replace GENERATION with the current value from inspect:
vision task execute --family czn-stage-settings --task-id $task --generation GENERATION
vision task inspect --task-id $task
```

The optional `--auto-recover` permits one qualified recovery before any primary action and one full restart after returning to the initial state. By default it is off. A task is completed only when the entire primary workflow completes. No-match, uncertain effect, or failure after a primary action requires Agent review.

## Quick start: new task

Start a Recorder session for the explicit device/goal. Observe a full screenshot, use a crop/asset and a fresh scoped reference, execute one action, wait and verify actual pixels, annotate semantic outcome, checkpoint. Pass the session ID to each recorded operation. Stop the session when exploration is complete.

For reusable tasks, build from selected actual event chains, validate offline, qualify the exact device/profile, run a controlled live test, then register and explicitly activate a reviewed version. For new recovery, open a case on the failed Runtime run and use the dedicated session. See the [Workflow playbook](skills/agent-vision/references/workflow.md) and [Builder plan](skills/agent-vision/references/builder.md).

## Capabilities and limits

- Interactive CLI/MCP: snapshot, crop, resize, template assets, find, click, swipe, type, key, wait. Check device capabilities; ADB Unicode entry is not universally available.
- Compiled workflow/runtime: reference-based click transitions only; same-source Android device/profile. Swipe/type/key and desktop primitives are not yet compiled workflows.
- Registry activation and recovery linking require live evidence; task execution is synchronous and bounded per step, not by a hard task deadline. MCP calls may time out while a task journal continues to update; inspect the original ID.
- No scheduler, autonomous LLM invocation, unattended recovery learning, automatic promotion, or arbitrary goal-to-workflow inference.
- Protected evidence is retained indefinitely in the current implementation. Screenshots and free-form annotations may contain sensitive information; avoid collecting secrets. Keep evidence outside tracked Git source. Do not delete the store to reset a task.

## State and evidence

```text
VISION_STORE_DIR/
  recorder.sqlite            # sessions, events, annotations, recovery and registry
  frames/                    # actual screenshots/crops
  refs/                      # scoped references
  recorded_assets/           # retained asset revisions
  workflows/wf_<sha256>/      # immutable definitions, plans and PNG templates
  runtime/bindings/          # qualified device/profile bindings
  runtime/runs/              # durable execution receipts
  orchestrator/tasks/        # durable task journals
```

Keep the original store for source evidence revalidation; a workflow bundle alone is insufficient for the current validator. Back up the store consistently when no task is running; do not modify journals, hashes or bundles manually.

## Development and validation

```powershell
$env:PYTHONPATH = "core;."
python -m pytest core/test vision_app/test -q
```

Phase 7 baseline: 258 regression tests passed; MuMu controlled settings navigation, known recovery + full task restart, and no-match handoff were live-tested. This is not evidence of generalized unattended Android automation. See [Phase 7 specification](specs/agent-vision-phase7/SPEC.md) and earlier specs under `specs/`. For the NB deployment, acceptance evidence is stored outside the repository in `../acceptance-20261126/agent-vision-phase*/`.

## References

- [Agent Vision Skill](skills/agent-vision/SKILL.md): agent instructions and reference routing.
- [Transport & CLI](skills/agent-vision/references/transport.md): verified commands and MCP setup.
- [Workflow playbook](skills/agent-vision/references/workflow.md): exploration, recovery, registry and task decisions.
- [Builder plan](skills/agent-vision/references/builder.md): exact plan fields and evidence collection.
- [Core README](core/README.md): legacy core library context, not the current agent entry point.

## Agent Vision 0.3.0 (Phase 9)

Learn once, qualify per explicit Android device, execute many. Immutable portable definitions, independent qualification slots, family generation CAS and bounded batch execution share the existing CLI/MCP Store. 90 MCP tools preserve the 61 legacy definitions. See [portable playbook](skills/agent-vision/references/portable.md) and [release notes](specs/agent-vision-phase9/RELEASE.md). Same-profile Android devices on one host were qualified with two live Settings campaigns; CZN-specific, heterogeneous-profile and cross-host readiness are not established.

## Agent Vision 0.2.0 (Phase 8 + 8.1)
The release adds recorded one-click transitions, explicit annotation fields/errors, opt-in response projections, metadata-only screenshots, CLI/MCP parity improvements, asset pagination, task-local sealed offline validation reuse, retained failure observations, and read-only runtime profile discovery. Existing workflow format and legacy full response defaults remain compatible. See [interface](skills/agent-vision/references/interface.md) and [release notes](specs/agent-vision-phase8/RELEASE.md). The NB official deployment uses the main checkout and shared .vision_store; independent qualification stores remain separate. Controlled settings navigation is qualified; generalized unattended game automation is not.
