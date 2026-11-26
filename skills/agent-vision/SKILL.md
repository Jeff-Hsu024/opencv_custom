---
name: agent-vision
description: Operate visual Android or desktop workflows using the installed Vision Platform CLI or Queqiao MCP. Use for screenshot, ROI crop, image templates, scoped references, visual state waits and verified UI navigation, especially when accessibility trees are insufficient. Prefer direct tool calls, not Orca worker orchestration, for interactive UI tasks.
---

# Agent Vision

Use Vision Platform as an observation/action loop, not a blind coordinate macro. Core remains generic Python/OpenCV/ADB; agent orchestration lives here. Read references/transport.md for exact interfaces and NB deployment; read references/workflow.md for decision rules.

## Operational loop

1. Discover reachable tools and devices; choose the user's intended explicit target. Never silently select desktop or another emulator. On NB, the validated MuMu target is 127.0.0.1:16480; confirm live identity before use. Check capabilities before text entry or unsupported actions.
2. Observe a real screenshot. Interpret the actual pixels. Determine expected postcondition before acting. If the screen is unfamiliar, inspect the whole frame, then crop relevant regions from that SAME frame (do not recapture just to crop).
3. Reuse a named visual asset if it matches current app/theme/resolution. Otherwise crop a distinctive static target with context from the actual screen, inspect the crop, then register it. Prefer a stable icon/label; exclude counters, animations and unrelated private content. Names encode app, semantic role, locale/theme when useful. Never treat a template as a semantic accessibility ID.
4. Find on a fresh frame using a high threshold appropriate to the actual asset (start at 0.98 for same-device exact UI, adjust only with visual evidence). Request all matches when uniqueness is important. Check bbox, score, expected region, device, orientation and frame freshness. No match or multiple plausible targets => observe/crop/disambiguate; never pick arbitrary first. For one-off obvious targets, a frame-local point is acceptable; pass the frame ID, not a global coordinate guess.
5. Act once with the fresh scoped ref or validated frame-local point. Set a short explicit max age (e.g. 15 seconds for normal interactive navigation). Ref age alone does not establish unchanged UI. If time elapsed, screen rotated, resolution changed or a popup appeared, observe/re-match first. No automatic retry of an ambiguous action. Respect the task's actual scope; don't operate unrelated accounts/apps/settings or physical desktop.
6. Verify: preserve pre-action frame, use wait changed with baseline_frame_id and meaningful ROI or wait image with a known postcondition asset; wait stable if animations require it. Then inspect a new screenshot or ROI proving the expected state. A changed frame or status=executed is not proof of semantic success. On failure, report observed state and replan; do not blindly repeat.
7. For multi-step tasks, continue only after the preceding postcondition is verified. Record successful steps, asset IDs, frame IDs, observed outcomes and any uncertainty. Restore previous app/page if the task is a reversible POC and restoration is appropriate. Do not claim full restoration without evidence.

## Efficiency and fallback

Use one full screenshot for new screen context, small crops for uncertain details, and structured find results for known targets. Prefer PNG and exact image dimensions; no need for repeated full-frame images after deterministic state recognition. Match known assets in a fresh frame before each state-changing click. Use bounded timeout and poll interval; no unbounded waits or needless sleep. Persist reusable assets; raw coordinates and refs are ephemeral. CLI and MCP use the same application services, but their stores are shared only when explicitly configured to the same directory. No separate OCR model is required to understand readable text in a visual crop.

If MCP is unavailable, try the installed CLI with a workspace-local store and native image read. Check actual errors before concluding a capability is unavailable. Never infer the content of an unseen file. If images cannot be rendered, do not claim visual observation. If Android AX is available and reliable it can complement visual observation; do not assume AX support on MuMu. Do not add a new browser/GUI toolchain or duplicate PlatformService.

## Reporting

Distinguish observed PASS, action executed but unverified, FAILED, BLOCKED, and NOT_ATTEMPTED. State device, target, operation, score/coordinates if relevant, verification and side effects. Preserve evidence outside tracked source. Do not claim generalized game automation or independent agent benchmark success from a single controlled navigation POC.
