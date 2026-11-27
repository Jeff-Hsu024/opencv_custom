# V01/V02 grouped verification

## V01 compatibility: PASS (software candidate)

Full coverage executed on 5a8b26298dc4ba9cf43cb90306173f9cc629c644. The initial monolithic invocation exceeded the Queqiao shell 120-second limit and yielded no completion receipt; the complete collected suite was then divided into 26 disjoint direct pytest invocations, each with its own isolated Store. JUnit and process exit receipts confirm 1429/1429 passed, zero failure/error/skip (451 regression, 978 frozen contract). Baseline source exported from bfbec17 and collected independently: all 308 baseline cases retained, including test_transition_buildable_and_idempotent now covered by its [False] parameter. All 26 frozen hash entries match. See regression-summary.json; raw per-shard XML/logs, collection lists and scripts are in .scratch/agent-vision-phase9/verification.

Actual runtime MCP catalog: 90 tools, all 61 legacy definitions exactly unchanged and all 29 additive input schemas equal the frozen request catalog. Production portable normalizer matched 223 frozen request examples. Native ImageContent and metadata-only behavior covered by integration regressions. The final timeout mapping correction in cb760869c74e4bbd8c769f2f19d3b7260aea4c0d returns CLI exit 4 for pre-admission preflight capture timeout while retaining the failed receipt; inspect returns 0. All 26 portable tests (25 existing plus new timeout regression) passed after that correction in 87.10s. The entire 1429-case suite was not repeated after this narrow delta.

Frozen v0.2.0 candidate-store-archive restored through its archive restore utility to a new isolated directory: 164 SHA-256 verified files, 78 indexed frames including 67 protected. All three historical completed source runs published portable definitions with actual verified source proof, no device input. All pre-existing non-DB file hashes unchanged; all pre-existing SQLite table rows unchanged after additive schema initialization; integrity_check ok before and after. Source archive and official Store not modified. Rollback: quiesce writers, restore a verified backup into a separate directory, point the previous release at that copy; do not overwrite frozen evidence.

Built candidate wheel from exported cb76086 source without deploying it. Wheel opencv_custom-0.2.0-py3-none-any.whl (candidate only, existing metadata version retained), 176631 bytes, SHA-256 61fd3b7468cd483b1548358c6397537801751e6aabcb1b937fd25e2ef0f01526. Installed only into isolated package-target using --no-deps; import provenance confirmed package-target, 90 tool definitions, actual CLI portable-list and MCP call_tool metadata matched. Candidate Skill/portable playbook updated. No release/version bump, merge, push or production installation.

## V02 independent live gate: BLOCKED_LIVE_DEVICE / NOT_ATTEMPTED

Read-only adb devices -l returned only 127.0.0.1:16480 (SM_A536E). No second explicit authorized compatible Android target available. Fixture overlap and copied historical proofs are software evidence, not fresh two-device qualification. No live UI input was performed, no independent agent was launched, and no live PASS or production-readiness assertion is made.

All P/B implementation direct by this ChatGPT session. Cancelled native DAG retained as historical evidence; not restarted.
