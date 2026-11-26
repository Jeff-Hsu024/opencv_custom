"""Opt-in adapter projections. Durable service payloads and legacy defaults are untouched."""
from __future__ import annotations
from vision_app.recorder import RecorderError

MODES=("summary","detail","full")
SUPPORTED={
    "workflow":{"build","inspect","validate"},
    "runtime":{"inspect"},
    "task":{"inspect"},
    "recovery":{"propose","inspect"},
    "record":{"event","events","resume-context"},
}

def schema_for(tool):
    for scope,actions in SUPPORTED.items():
        prefix="vision_"+scope+"_"
        if tool["name"].startswith(prefix) and tool["name"][len(prefix):].replace("_","-") in actions:
            props=tool["inputSchema"]["properties"]
            props["response_mode"]={"type":"string","enum":list(MODES),"default":"full"}
            props["detail_id"]={"type":"string","description":"Specific step/event/child run ID for detail where supported."}

def validate(scope,action,mode,detail_id):
    if mode not in MODES or ((scope not in SUPPORTED or action not in SUPPORTED[scope]) and (mode!="full" or detail_id is not None)):
        raise RecorderError("Unsupported response mode for this operation",code="INVALID_RESPONSE_MODE")
    if detail_id is not None and (mode!="detail" or not isinstance(detail_id,str) or not detail_id):
        raise RecorderError("detail_id requires detail mode",code="INVALID_RESPONSE_MODE")
    requires=(scope,action) in {("workflow","inspect"),("runtime","inspect"),("task","inspect"),("record","resume-context"),("record","events")}
    if mode=="detail" and requires and not detail_id:
        raise RecorderError("detail mode requires a specific detail_id",code="INVALID_RESPONSE_MODE")
    if detail_id is not None and not requires:
        raise RecorderError("detail_id not supported for this operation",code="INVALID_RESPONSE_MODE")

def pick(obj,*keys):
    return {k:obj[k] for k in keys if k in obj}

def event_summary(e):
    return {**pick(e,"event_id","sequence","operation","status","error"),
            "evidence":{k:len(v) for k,v in e.get("evidence",{}).items() if isinstance(v,list)}}

def detail(items,key,value):
    match=next((i for i in items if i.get(key)==value),None)
    if match is None:raise RecorderError("Detail ID not found in result; inspect/list full evidence",code="DETAIL_NOT_FOUND")
    return match

def step_summary(s):
    return pick(s,"step_id","from","to","status","pre_frame_id","post_frame_id","target","action_receipt")

def project(scope,action,r,mode="full",detail_id=None):
    if mode=="full":return r
    if scope=="workflow":
        if action=="validate":return r
        d=r["definition"];v=d["validation"]
        out={**pick(r,"workflow_id","bundle_path"),**pick(d,"name","goal","initial_state","final_state"),
             "status":v["status"],"states":len(d["states"]),"steps":len(d["steps"]),
             "state_checks":{"passed":len(v["state_checks"]),"total":len(v["state_checks"])},
             "target_checks":{"passed":len(v["target_checks"]),"total":len(v["target_checks"])},
             "live_runtime_qualified":v["live_runtime_qualified"],"source_session_id":d["source"]["session_id"],
             "state_ids":[s["id"] for s in d["states"]],"step_ids":[s["id"] for s in d["steps"]]}
        if mode=="detail":
            if action=="inspect":out["step"]=detail(d["steps"],"id",detail_id)
            else:out["state_markers"]=[pick(s,"id","label","provenance") for s in d["states"]]
        return out
    if scope=="runtime":
        out=pick(r,"run_id","workflow_id","binding_id","device","status","reason","current_step","last_frame_id","last_confirmed_state","action_outcome","completed_steps","started_at","finished_at")
        out["steps"]=[step_summary(s) for s in r["steps"]]
        if mode=="detail":out["step"]=detail(r["steps"],"step_id",detail_id)
        return out
    if scope=="task":
        out=pick(r,"task_id","family_id","version","generation","workflow_id","status","phase","recovered","reason","handoff","selection","recovery_endpoint","started_at","finished_at")
        out["children"]=r["children"]
        if mode=="detail":out["child"]=detail(r["children"],"run_id",detail_id)
        return out
    if scope=="recovery":
        if action=="propose":
            p=r["payload"]
            out={**pick(r,"proposal_id","case_id","created_at"),**pick(p,"parent_workflow_id","child_workflow_id","failed_run_id","recovery_session_id","kind","destination_state","status","automatic_resume","automatic_promotion","original_action_outcome")}
            out["anchor_frame_id"]=p["anchor"]["frame_id"];out["endpoint_frame_id"]=p["endpoint"]["frame_id"]
            if mode=="detail":out["reconciliation"]=p["reconciliation"];out["anchor"]=p["anchor"];out["endpoint"]=p["endpoint"]
            return out
        return r # already bounded handoff and paged proposals
    if scope=="record":
        if action=="event":return r if mode=="detail" else event_summary(r)
        if action=="events":
            if mode=="detail":return {"item":detail(r["items"],"event_id",detail_id),"next_cursor":r["next_cursor"]}
            return {"items":[event_summary(e) for e in r["items"]],"next_cursor":r["next_cursor"]}
        out={**r,"recent_events":[event_summary(e) for e in r["recent_events"]],
             "recent_non_success":[event_summary(e) for e in r["recent_non_success"]]}
        if mode=="detail":out["event"]=detail(r["recent_events"],"event_id",detail_id)
        return out
    return r
