"""Recorded one-click transition: one lock, ordinary primitive receipts, no semantic inference."""
from __future__ import annotations

import json
import hashlib
import math
import re
from pathlib import Path
import time

from vision_app.actions import ActionService
from vision_app.assets import AssetRegistry, MatchingService
from vision_app.observation import ObservationService
from vision_app.recorder import Recorder, RecorderError, workspace_lock
from vision_app.store import _atomic_write_json
from vision_app.waits import WaitService


def check(ok,message):
    if not ok: raise RecorderError(message,code="INVALID_TRANSITION")


def bounded(value,lo,hi):
    return type(value) in (float,int) and math.isfinite(value) and lo<=value<=hi


class TransitionService:
    def __init__(self,store,*,observation=None,matcher=None,actions=None,waits=None):
        self.store=store
        self.rec=Recorder(store)
        self.obs=observation or ObservationService(store)
        self.assets=AssetRegistry(store.store_dir)
        self.matcher=matcher or MatchingService(store=store,assets=self.assets)
        self.actions=actions or ActionService(store,platform_factory=self.obs._platform_factory)
        self.waits=waits or WaitService(store,asset_registry=self.assets,platform_factory=self.obs._platform_factory)
        self.root=store.store_dir/"transitions"

    def _path(self,tid):
        check(isinstance(tid,str) and re.fullmatch(r"trans_[a-f0-9]{32}",tid),"Invalid transition ID")
        return self.root/(tid+".json")

    def _save(self,t):
        t["updated_at"]=time.time()
        _atomic_write_json(self._path(t["transition_id"]),t)

    def _finish(self,t,status,reason=None):
        t["status"]=status;t["reason"]=reason;t["finished_at"]=time.time()
        self._save(t)
        return t

    def _reconcile(self,t):
        # Correlation is persisted in normal event inputs before invocation.
        with self.rec.db() as db:
            rows=db.execute("""SELECT event_id,operation,status,result FROM events
                         WHERE session_id=? AND json_extract(inputs,'$.transition_id')=?
                         ORDER BY sequence""",(t["request"]["session_id"],t["transition_id"])).fetchall()
        for r in rows:
            payload=json.loads(r["result"]) if r["result"] else None
            role="post" if r["operation"]=="snapshot" and "pre" in t["events"] and t["events"]["pre"]!=r["event_id"] else {"snapshot":"pre","find":"find","click":"action","wait":"wait"}[r["operation"]]
            t["events"][role]=r["event_id"]
            if r["operation"]=="click":
                t["action_outcome"]="executed_unverified" if r["status"]=="success" else "unknown"
            if payload and (payload.get("frame") or payload.get("frame_id")):
                t["last_frame_id"]=payload.get("frame",{}).get("frame_id") or payload.get("frame_id")
                if payload.get("artifact"):t["artifact"]=payload["artifact"]
        return self._finish(t,"interrupted",{"code":"TRANSITION_INTERRUPTED","message":"Previous writer ended; inspect receipts and fresh state. Do not replay."})

    def inspect(self,transition_id):
        p=self._path(transition_id)
        check(p.is_file() and not p.is_symlink(),"Transition not found")
        return json.loads(p.read_text(encoding="utf-8"))

    def execute(self,device,session_id,transition_id,target,postcondition,threshold=.98,max_ref_age_seconds=15,return_image=True,pre_state=None):
        check(isinstance(device,str) and device not in ("","adb","desktop"),"Explicit Android device required")
        check(isinstance(session_id,str) and bool(session_id),"Explicit session required")
        check(isinstance(target,str) and bool(target),"Target asset required")
        check(bounded(threshold,.8,1),"threshold must be 0.8..1")
        check(bounded(max_ref_age_seconds,.001,60),"max_ref_age_seconds must be >0 and <=60")
        check(type(return_image) is bool,"return_image must be boolean")
        check(isinstance(postcondition,dict) and set(postcondition)<={"mode","timeout","region","target","threshold","settle_seconds","min_changed_ratio"},"Invalid postcondition fields")
        mode=postcondition.get("mode");timeout=postcondition.get("timeout")
        check(mode in ("changed","image") and bounded(timeout,.001,60),"Postcondition mode/timeout invalid")
        check((mode=="changed" and "target" not in postcondition and "threshold" not in postcondition) or
              (mode=="image" and isinstance(postcondition.get("target"),str) and bool(postcondition["target"]) and bounded(postcondition.get("threshold",.98),0,1)),"Postcondition target/threshold invalid")
        settle=postcondition.get("settle_seconds",0)
        check(bounded(settle,0,2) and settle<timeout,"settle_seconds must be 0..2 and below timeout")
        ratio=postcondition.get("min_changed_ratio",.01)
        check(bounded(ratio,0,1) and (mode=="changed" or "min_changed_ratio" not in postcondition),"Invalid min_changed_ratio")
        region=postcondition.get("region")
        if region is not None:check(isinstance(region,list) and len(region)==4 and all(type(i) is int for i in region) and 0<=region[0]<region[2] and 0<=region[1]<region[3],"Invalid postcondition region")
        if pre_state is not None:check(isinstance(pre_state,str) and bool(pre_state),"Invalid pre_state asset")
        path=self._path(transition_id)
        request={"device":device,"session_id":session_id,"target":target,"postcondition":postcondition,"threshold":threshold,
                 "max_ref_age_seconds":max_ref_age_seconds,"return_image":return_image,"pre_state":pre_state}
        with workspace_lock(self.store):
            if path.exists():
                t=self.inspect(transition_id)
                check(t["request"]==request,"Transition ID already bound to different request")
                if t["status"]=="running":t=self._reconcile(t)
                return {**t,"duplicate_request":True}
            session=self.rec.status(session_id)
            check(session["status"]=="active" and session["device_id"]==device,"Active session/device mismatch")
            for name in (target,pre_state,postcondition.get("target")):
                if name:
                    a=self.assets.get(name)
                    check(a.device_id in (None,device),"Asset device mismatch")
                    self.assets.load_image(name)
            t={"transition_id":transition_id,"request":request,"status":"running","action_outcome":"not_attempted",
               "events":{},"last_frame_id":None,"match_count":None,"target_score":None,"wait":None,
               "artifact":None,"semantic_verification":"UNKNOWN","started_at":time.time(),"finished_at":None,"reason":None}
            self._save(t)
            def op(role,operation,inputs,invoke):
                r=self.rec._execute_locked(session_id,operation,{**inputs,"transition_id":transition_id},invoke)
                t["events"][role]=r["event_id"]
                if r.get("frame") or r.get("frame_id"):
                    # Find also carries frame_id; retain its actual last observation artifact.
                    t["last_frame_id"]=r.get("frame",{}).get("frame_id") or r.get("frame_id")
                    if r.get("artifact"):t["artifact"]=r["artifact"]
                self._save(t)
                if not r.get("ok"):
                    err=r.get("error") or {}
                    raise RecorderError(err.get("message","Primitive failed"),code=err.get("code","TRANSITION_PRIMITIVE_FAILED"))
                return r
            def snap():return {"ok":True,"device":device,**self.obs.snapshot(device)}
            try:
                pre=op("pre","snapshot",{"device":device},snap)
                frame=pre["frame"];fid=frame["frame_id"]
                if region:check(region[2]<=frame["width"] and region[3]<=frame["height"],"Postcondition region outside frame")
                if pre_state:
                    # Read-only guard match; not an extra action or replacement for recorded find.
                    asset=self.assets.get(pre_state)
                    guard=self.matcher.opencv.find_all(self.store.load_image(fid),self.assets.load_image(pre_state),
                                                       threshold=threshold,max_results=2,color_mode="gray")
                    t["pre_state_guard"]={"asset":pre_state,"asset_sha256":hashlib.sha256(Path(asset.image_path).read_bytes()).hexdigest(),
                                          "frame_id":fid,"count":len(guard),"score":guard[0].score if guard else None}
                    self._save(t)
                    if len(guard)!=1:return self._finish(t,"needs_agent",{"code":"PRECONDITION_FAILED","message":"Pre-state marker not unique"})
                find=op("find","find",{"frame_id":fid,"target":target,"all":True,"threshold":threshold,"max_results":2,"color_mode":"gray"},
                        lambda:{"ok":True,**self.matcher.find(fid,target,find_all=True,threshold=threshold,max_results=2)})
                t["match_count"]=find["count"]
                if find["count"]!=1:return self._finish(t,"needs_agent",{"code":"TARGET_NOT_UNIQUE","message":"Expected one target"})
                match=find["matches"][0];t["target_score"]=match["score"]
                if not 0<=time.time()-frame["timestamp"]<=max_ref_age_seconds:
                    return self._finish(t,"needs_agent",{"code":"FRAME_STALE","message":"Pre-frame expired"})
                rid=match["ref_id"]
                t["action_outcome"]="unknown";self._save(t)
                op("action","click",{"device":device,"ref":rid,"max_age_seconds":max_ref_age_seconds},
                   lambda:{"ok":True,**self.actions.click(device,ref_id=rid,max_age_seconds=max_ref_age_seconds)})
                t["action_outcome"]="executed_unverified";self._save(t)
                wi={"device":device,"mode":mode,"timeout":timeout,"region":region,"settle_seconds":settle}
                if mode=="changed":
                    wi.update(baseline_frame_id=fid,min_changed_ratio=ratio)
                else:
                    wi.update(target=postcondition["target"],threshold=postcondition.get("threshold",.98))
                def invoke():
                    started=time.monotonic()
                    if settle:time.sleep(settle)
                    remaining=timeout-(time.monotonic()-started)
                    if remaining<=0:
                        raise RecorderError("Wait budget exhausted during settle",code="WAIT_TIMEOUT")
                    if mode=="changed":
                        r=self.waits.wait_changed(device,baseline_frame_id=fid,region=tuple(region) if region else None,
                                                  timeout=remaining,interval=.2,min_changed_ratio=ratio)
                    else:
                        r=self.waits.wait_image(device,target_name=wi["target"],region=tuple(region) if region else None,
                                               timeout=remaining,interval=.2,threshold=wi["threshold"])
                    return {"ok":True,**r,"elapsed_seconds":time.monotonic()-started}
                wait=op("wait","wait",wi,invoke)
                t["wait"]={k:wait.get(k) for k in ("condition","verified","frame_id","elapsed_seconds")}
                if not wait.get("verified"):return self._finish(t,"needs_agent",{"code":"WAIT_UNVERIFIED","message":"Wait did not verify"})
                op("post","snapshot",{"device":device},snap)
                return self._finish(t,"observed")
            except Exception as exc:
                return self._finish(t,"needs_agent",{"code":getattr(exc,"code","TRANSITION_ERROR"),"message":str(exc)})


def transition_tool_definitions():
    s={"type":"string"};n={"type":"number"}
    post={"type":"object","properties":{"mode":{"enum":["changed","image"],"type":"string"},"timeout":{"type":"number","exclusiveMinimum":0,"maximum":60},"region":{"type":"array","items":{"type":"integer"},"minItems":4,"maxItems":4},"target":s,"threshold":{"type":"number","minimum":0,"maximum":1},"settle_seconds":{"type":"number","minimum":0,"maximum":2,"default":0},"min_changed_ratio":{"type":"number","minimum":0,"maximum":1,"default":.01}},"required":["mode","timeout"],"additionalProperties":False}
    props={"device":s,"session_id":s,"transition_id":s,"target":s,"postcondition":post,"threshold":{"type":"number","minimum":.8,"maximum":1,"default":.98},"max_ref_age_seconds":{"type":"number","exclusiveMinimum":0,"maximum":60,"default":15},"return_image":{"type":"boolean","default":True},"pre_state":s}
    return [{"name":"vision_transition","description":"Record one fresh unique click and observed post-frame; annotate semantic result separately.","inputSchema":{"type":"object","properties":props,"required":["device","session_id","transition_id","target","postcondition"],"additionalProperties":False}},
            {"name":"vision_transition_inspect","description":"Read persisted transition receipt without action.","inputSchema":{"type":"object","properties":{"transition_id":s},"required":["transition_id"],"additionalProperties":False}}]
