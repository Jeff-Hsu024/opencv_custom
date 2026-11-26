# MCP / CLI inventory

Generated from actual parser and MCP definitions. All 57 baseline tools retained; three additive tools. CLI command mapping, not a claim of identical wire formats. Full schemas, defaults and parser flags in parity-inventory.json in acceptance evidence.

| MCP tool | CLI command | Change |
|---|---|---|
| vision_devices | `vision devices` | unchanged |
| vision_capabilities | `vision capabilities` | unchanged |
| vision_snapshot | `vision snapshot` | schema updated |
| vision_crop | `vision crop` | schema updated |
| vision_resize | `vision resize` | schema updated |
| vision_assets_register | `vision assets register` | unchanged |
| vision_assets_list | `vision assets list` | unchanged |
| vision_find | `vision find` | schema updated |
| vision_click | `vision click` | unchanged |
| vision_swipe | `vision swipe` | unchanged |
| vision_type | `vision type` | unchanged |
| vision_key | `vision key` | unchanged |
| vision_wait | `vision wait` | schema updated |
| vision_record_start | `vision record start` | unchanged |
| vision_record_list | `vision record list` | unchanged |
| vision_record_status | `vision record status` | unchanged |
| vision_record_pause | `vision record pause` | unchanged |
| vision_record_resume | `vision record resume` | unchanged |
| vision_record_stop | `vision record stop` | unchanged |
| vision_record_inspect | `vision record inspect` | unchanged |
| vision_record_summary | `vision record summary` | unchanged |
| vision_record_events | `vision record events` | schema updated |
| vision_record_event | `vision record event` | schema updated |
| vision_record_annotate | `vision record annotate` | schema updated |
| vision_record_checkpoint | `vision record checkpoint` | schema updated |
| vision_record_annotations | `vision record annotations` | unchanged |
| vision_record_history | `vision record history` | unchanged |
| vision_record_asset_evidence | `vision record asset-evidence` | new |
| vision_record_resume_context | `vision record resume-context` | schema updated |
| vision_record_latest_checkpoint | `vision record latest-checkpoint` | unchanged |
| vision_workflow_candidates | `vision workflow candidates` | unchanged |
| vision_workflow_build | `vision workflow build` | schema updated |
| vision_workflow_inspect | `vision workflow inspect` | schema updated |
| vision_workflow_validate | `vision workflow validate` | schema updated |
| vision_workflow_list | `vision workflow list` | unchanged |
| vision_runtime_qualify | `vision runtime qualify` | unchanged |
| vision_runtime_run | `vision runtime run` | unchanged |
| vision_runtime_inspect | `vision runtime inspect` | schema updated |
| vision_runtime_list | `vision runtime list` | unchanged |
| vision_recovery_open | `vision recovery open` | unchanged |
| vision_recovery_inspect | `vision recovery inspect` | schema updated |
| vision_recovery_propose | `vision recovery propose` | schema updated |
| vision_recovery_proposal | `vision recovery proposal` | unchanged |
| vision_recovery_verify | `vision recovery verify` | unchanged |
| vision_recovery_list | `vision recovery list` | unchanged |
| vision_lifecycle_register | `vision lifecycle register` | unchanged |
| vision_lifecycle_activate | `vision lifecycle activate` | unchanged |
| vision_lifecycle_disable | `vision lifecycle disable` | unchanged |
| vision_lifecycle_rollback | `vision lifecycle rollback` | unchanged |
| vision_lifecycle_link | `vision lifecycle link` | unchanged |
| vision_lifecycle_route_status | `vision lifecycle route-status` | unchanged |
| vision_lifecycle_inspect | `vision lifecycle inspect` | unchanged |
| vision_lifecycle_history | `vision lifecycle history` | unchanged |
| vision_lifecycle_list | `vision lifecycle list` | unchanged |
| vision_lifecycle_select | `vision lifecycle select` | unchanged |
| vision_task_execute | `vision task execute` | unchanged |
| vision_task_inspect | `vision task inspect` | schema updated |
| vision_task_list | `vision task list` | unchanged |
| vision_transition | `vision transition execute` | new |
| vision_transition_inspect | `vision transition inspect` | new |

Legacy defaults are retained: CLI wait interval 0.5s vs MCP 0.2s; set explicitly for equivalence. CLI file output and MCP ImageContent are transport-specific. Summary is opt-in; full response remains default.
