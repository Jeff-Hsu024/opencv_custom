# Visual workflow and acceptance

## State-driven execution

Define each step as:
- precondition: visible known page or image evidence, device and orientation
- target: semantic role plus template name or visually selected frame-local point
- action: one click/key/swipe/type, explicit bounds
- postcondition: page title or a unique visual marker, or a checked state change with actual screenshot
- on failure: re-observe; return precise error if unknown

Use a high-confidence known target in a known page. A 1.0 score only means the pixels match, not that a button is enabled or that the intended action occurred. Do not use a screenshot from a previous task to act on the current screen. Prefer ROI for animated UIs; check the entire relevant context if there are duplicates. Templates must be reviewed again when resolution, locale, app version, theme, or scale changes.

## Reusable workflow lifecycle

1. Learn with observation and one-off scoped interactions; save stable target assets and state markers.
2. Record the semantic sequence with preconditions/postconditions; separate asset recognition from actions.
3. Replay only within its intended app and device context using fresh frames, not captured coordinates. Bounded state waits; handle unknown state by returning to the agent.
4. Validate multiple fresh runs and changed conditions before declaring repeatability. Use deterministic OpenCV recognition/action execution for known states and LLM reasoning only for unfamiliar cases.

## Controlled POC

Choose reversible navigation with no persistent settings change. Verify original app/page, navigate at least two pages using newly learned targets, validate each postcondition and return to original app/page. Report actual frame IDs and scores. A successful POC is not evidence of unattended game-specific automation, robust UI recovery or performance at scale. Test those separately on the intended application.
