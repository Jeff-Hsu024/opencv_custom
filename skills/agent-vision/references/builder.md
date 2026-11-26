# Evidence-bound workflow plan

Read this only when compiling or reviewing a reusable workflow. The source is one stopped Recorder session, on one device. All actual action events must be accounted for. Do not turn conversation descriptions into invented event IDs.

## Record the evidence in order

For each transition collect:
1. Fresh full snapshot of source state. Register target from actual image if needed. If asset learning takes time, capture a fresh pre-action snapshot.
2. Find with all=true, unique result, threshold chosen from actual evidence. Preserve find event and reference.
3. Click the resulting current reference once, with explicit short max age.
4. Wait changed against the pre-frame (bounded timeout).
5. Take a separate full destination snapshot. Inspect actual pixels and annotate the snapshot event with state, observation, verification=PASS. A wait success is not semantic verification.

Use distinctive stable state marker regions, separate from action target templates. State markers must uniquely match their own positive historical frames and not match other states (including wait result frames).

## Exact plan shape

Illustrative placeholders only: replace every ID and ROI with real recorded evidence. This example defines one transition. JSON field names are exact.

```json
{
  "name": "Open settings",
  "goal": "Open the intended settings page",
  "states": [
    {"id":"home","label":"Home","event_id":"ACTUAL_PRE_SNAPSHOT_EVENT","region":[10,20,110,60],"threshold":0.98},
    {"id":"settings","label":"Settings","event_id":"ACTUAL_POST_SNAPSHOT_EVENT","region":[20,30,140,70],"threshold":0.98}
  ],
  "steps": [
    {
      "from":"home","to":"settings",
      "pre_event_id":"ACTUAL_PRE_SNAPSHOT_EVENT",
      "find_event_id":"ACTUAL_FIND_EVENT",
      "action_event_id":"ACTUAL_CLICK_EVENT",
      "wait_event_id":"ACTUAL_WAIT_EVENT",
      "post_event_id":"ACTUAL_POST_SNAPSHOT_EVENT",
      "annotation_id":"ACTUAL_PASS_ANNOTATION"
    }
  ],
  "excluded_actions":[]
}
```

Exclusions use {event_id,reason}; they cannot conceal actions in or between selected transitions. A recovery plan cannot exclude any action. States must be connected; no repeated action IDs, unsupported actions or ambiguous state/target evidence. Source limits: up to 1000 events/annotations, 20 states/steps, 64 KiB plan. Regions are half-open [x1,y1,x2,y2] in actual full-frame coordinates.

Use `vision_workflow_build {session_id,plan}`, then inspect/validate the returned immutable workflow_id. CLI: `vision workflow build --session SID --plan plan.json`. Never edit the published bundle. A changed plan produces a new content-addressed ID.

## Qualification and promotion

Use actual observed Android package, version_code, rotation, locale, ui_mode and device to qualify; no invented profile. Preflight verifies initial state/first target without clicking. Run once with a unique run_<32 lowercase hex> ID; a complete live run is required for registry registration. Use same goal and actual parent endpoint guards for replacement versions. Activate explicitly with current generation. See [workflow playbook](workflow.md) and [transport](transport.md).
