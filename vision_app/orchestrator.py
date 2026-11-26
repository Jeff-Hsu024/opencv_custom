"""Bounded task execution over the existing registered Runtime and Recovery Selector."""
from __future__ import annotations

import json
import re
import time

from vision_app.lifecycle import LifecycleService
from vision_app.recorder import workspace_lock
from vision_app.validation_context import validation_scope
from vision_app.runtime import WorkflowRuntime
from vision_app.store import _atomic_write_json
from vision_app.workflow import require, digest, canonical


class ExecutionOrchestrator:
    def __init__(self, store, *, runtime=None):
        self.store=store
        self.rt=runtime or WorkflowRuntime(store)
        self.lc=LifecycleService(store,runtime=self.rt)
        self.root=store.store_dir/"orchestrator"/"tasks"

    def _path(self,task_id):
        require(isinstance(task_id,str) and re.fullmatch(r"task_[a-f0-9]{32}",task_id),"Invalid task ID")
        return self.root/(task_id+".json")

    def _load(self,task_id):
        p=self._path(task_id)
        require(p.is_file() and not p.is_symlink(),"Task not found")
        return json.loads(p.read_text(encoding="utf-8"))

    def _persist(self,task):
        task["updated_at"]=time.time()
        _atomic_write_json(self._path(task["task_id"]),task)

    @staticmethod
    def _run_id(task_id,role):
        return "run_"+digest(canonical({"task_id":task_id,"role":role}))[:32]

    @staticmethod
    def _receipt(run):
        return {k:run.get(k) for k in ("run_id","workflow_id","binding_id","status","reason",
                 "completed_steps","current_step","last_frame_id","last_confirmed_state","action_outcome")}

    def _finish(self,t,status,code=None,message=None):
        t["status"]=status
        t["finished_at"]=time.time()
        t["reason"]={"code":code,"message":message} if code else None
        self._persist(t)
        return t

    def _reconcile(self,t):
        # Never resume; child journals are authoritative about any attempted effect.
        for child in t["children"]:
            path=self.rt._path("runs",child["run_id"])
            if path.exists():
                run=self.rt._load("runs",child["run_id"])
                require(run["binding_id"]==child["binding_id"] and run["workflow_id"]==child["workflow_id"],
                        "Child run identity mismatch")
                if run["status"]=="running":
                    run=self.rt._run_locked(child["binding_id"],child["run_id"])
                child["receipt"]=self._receipt(run)
        self._handoff_context(t)
        return self._finish(t,"interrupted","TASK_INTERRUPTED",
                            "Previous task ended without terminal receipt. Inspect child journals and fresh state; never replay automatically.")

    def _pin(self,family_id,expected_generation):
        with self.lc.rec.db() as db:
            f=self.lc._family(db,family_id)
            self.lc._cas(f,expected_generation)
            require(f["active_version"] is not None,"Family is disabled")
            v=self.lc._version(db,family_id,f["active_version"])
        return f,v

    def _child(self,t,role,wid,binding_id):
        rid=self._run_id(t["task_id"],role)
        require(not self.rt._path("runs",rid).exists(),"Child run ID collision")
        child={"role":role,"workflow_id":wid,"binding_id":binding_id,"run_id":rid,"receipt":None}
        t["children"].append(child)
        t["phase"]=role
        self._persist(t)
        result=self.rt._run_locked(binding_id,rid)
        require(result["run_id"]==rid and result["workflow_id"]==wid and
                result["binding_id"]==binding_id and not result.get("duplicate_request"),"Unexpected child run receipt")
        child["receipt"]=self._receipt(result)
        self._persist(t)
        return result

    def _eligible(self,run):
        if (run["status"]!="needs_agent" or run["completed_steps"]!=0
                or run["action_outcome"]!="not_attempted"
                or (run["reason"] or {}).get("code")!="PRECONDITION_FAILED"
                or len(run["steps"])!=1):
            return False
        step=run["steps"][0]
        return (step["target"] is None and step["action_receipt"] is None
                and step.get("pre_state") is not None and not step["pre_state"]["ambiguous"])

    def execute(self,family_id,task_id,expected_generation,auto_recover=False):
        self.lc._slug(family_id)
        require(type(expected_generation) is int and expected_generation>=0,"Invalid generation")
        require(type(auto_recover) is bool,"auto_recover must be boolean")
        request={"family_id":family_id,"expected_generation":expected_generation,"auto_recover":auto_recover}
        path=self._path(task_id)
        with workspace_lock(self.store), validation_scope(self.store):
            if path.exists():
                old=self._load(task_id)
                require(old["request"]==request,"Task ID already bound to another request")
                if old["status"]=="running":
                    old=self._reconcile(old)
                return {**old,"duplicate_request":True}
            f,v=self._pin(family_id,expected_generation)
            for role in ("primary","recovery","restart"):
                require(not self.rt._path("runs",self._run_id(task_id,role)).exists(),"Child run ID collision")
            t={"task_id":task_id,"request":request,"family_id":family_id,"generation":f["generation"],
               "version":v["version"],"workflow_id":v["workflow_id"],"device":f["device"],
               "profile":f["profile"],"status":"running","phase":"preflight","children":[],
               "selection":None,"recovered":False,"started_at":time.time(),"finished_at":None,
               "reason":None,"handoff":None}
            self._persist(t)
            try:
                proof,d=self.lc._check_version(v)
                binding_id=proof["binding_id"]
                first=self._child(t,"primary",v["workflow_id"],binding_id)
                if first["status"]=="completed":
                    return self._finish(t,"completed")
                if not auto_recover or not self._eligible(first):
                    return self._handoff(t,"PRIMARY_NEEDS_AGENT","Automatic recovery disabled or failure is not eligible.")
                t["phase"]="select"
                self._persist(t)
                selection=self.lc._select_locked(family_id,first["run_id"])
                t["selection"]=selection
                self._persist(t)
                if selection["status"]!="selected":
                    return self._handoff(t,"RECOVERY_NOT_SELECTED","No unique qualified recovery route.")
                selected=selection["selected"]
                if selected["destination_state"]!=d["initial_state"]:
                    return self._handoff(t,"RECOVERY_ENDPOINT_UNSAFE","Selected route does not return to original initial state.")
                with self.lc.rec.db() as db:
                    route=self.lc._dict(db.execute("SELECT * FROM workflow_routes WHERE route_id=? AND family_id=? AND parent_version=? AND enabled=1",
                                                  (selected["route_id"],family_id,v["version"])).fetchone())
                require(route["child_workflow_id"]==selected["workflow_id"] and
                        route["qualification_id"]==selected["qualification_id"],"Selected route identity mismatch")
                qualified=self.rt._load("runs",route["run_id"])
                child=self._child(t,"recovery",route["child_workflow_id"],qualified["binding_id"])
                if child["status"]!="completed":
                    return self._handoff(t,"RECOVERY_FAILED","Recovery did not complete; no retry.")
                parent,templates=self.rt._definition(v["workflow_id"],f["device"],f["profile"])
                image,_=self.lc._frame(child["last_frame_id"],f["device"],parent["geometry"])
                classification=self.rt._classify(image,parent,templates)
                t["recovery_endpoint"]={"frame_id":child["last_frame_id"],**classification}
                self._persist(t)
                if classification["ambiguous"] or classification["state"]!=d["initial_state"]:
                    return self._handoff(t,"RECOVERY_ENDPOINT_UNVERIFIED","Child final frame does not uniquely match parent initial state.")
                t["recovered"]=True
                self._persist(t)
                retry=self._child(t,"restart",v["workflow_id"],binding_id)
                if retry["status"]=="completed":
                    return self._finish(t,"completed")
                return self._handoff(t,"RESTART_FAILED","Original task did not complete after recovery; no second attempt.")
            except Exception as exc:
                return self._handoff(t,getattr(exc,"code","ORCHESTRATOR_ERROR"),str(exc))

    def _handoff_context(self,t):
        last=t["children"][-1] if t["children"] else None
        receipt=last["receipt"] if last else None
        latest_frame=(receipt or {}).get("last_frame_id")
        if t["selection"] and (not latest_frame or last["role"]=="primary"):
            latest_frame=t["selection"].get("frame_id") or latest_frame
        t["handoff"]={"last_child":last,"selection":t["selection"],"recovery_completed":t["recovered"],
                      "original_task_completed":False,
                      "last_frame_id":latest_frame,
                      "action_outcome":(receipt or {}).get("action_outcome","unknown" if last else "not_attempted"),
                      "next_action":"Inspect child journal and observe fresh actual state before taking any action. Do not blindly replay."}

    def _handoff(self,t,code,message):
        self._handoff_context(t)
        return self._finish(t,"needs_agent",code,message)

    def inspect(self,task_id):
        return self._load(task_id)

    def list(self,limit=20,after=None):
        require(type(limit) is int and 1<=limit<=50,"Invalid limit")
        if after is not None:self._path(after)
        ids=sorted(p.stem for p in self.root.glob("task_*.json")
                   if re.fullmatch(r"task_[a-f0-9]{32}",p.stem) and (after is None or p.stem>after))
        items=[{k:t.get(k) for k in ("task_id","family_id","version","generation","status","recovered","reason","updated_at")}
               for t in (self._load(tid) for tid in ids[:limit])]
        return {"items":items,"next_cursor":items[-1]["task_id"] if len(ids)>limit else None}

    def query(self,action,**args):
        require(action in ("execute","inspect","list"),"Unknown orchestrator action")
        return getattr(self,action)(**args)


def orchestrator_tool_definitions():
    s={"type":"string"};i={"type":"integer","minimum":0}
    specs={
        "execute":({"family_id":s,"task_id":s,"expected_generation":i,"auto_recover":{"type":"boolean","default":False}},
                   ["family_id","task_id","expected_generation"],"Execute active workflow; optional single qualified recovery and safe full restart only before any primary action."),
        "inspect":({"task_id":s},["task_id"],"Inspect persistent task outcome and child run references."),
        "list":({"limit":{"type":"integer","minimum":1,"maximum":50},"after":s},[],"List task receipts.")}
    return [{"name":"vision_task_"+name,"description":desc,
             "inputSchema":{"type":"object","properties":props,"required":required,"additionalProperties":False}}
            for name,(props,required,desc) in specs.items()]
