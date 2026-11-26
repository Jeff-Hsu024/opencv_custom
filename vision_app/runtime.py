"""Deterministic, evidence-bound Android workflow execution. No LLM or recovery loop."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from service.core.opencv.open_cv_service import OpenCvService
from vision_app.actions import ActionService
from vision_app.assets import RefRegistry, _map_match_to_ref
from vision_app.observation import ObservationService
from vision_app.recorder import workspace_lock
from vision_app.store import FrameStore, _atomic_write_json, protect_new_frames
from vision_app.workflow import WorkflowBuilder, canonical, digest, decode, require, fields

PROFILE_FIELDS = ("package", "version_code", "rotation", "locale", "ui_mode")
MAX_CAPTURES = 20
POLL_SECONDS = 0.25


class RuntimeFault(Exception):
    def __init__(self, code, message, details=None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


def check(condition, code, message, details=None):
    if not condition:
        raise RuntimeFault(code, message, details)


def profile_shape(profile):
    fields(profile, PROFILE_FIELDS, "Android profile")
    require(isinstance(profile["package"], str) and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+", profile["package"]),
            "Invalid Android package")
    require(type(profile["version_code"]) is int and profile["version_code"]>0,"Invalid version code")
    require(type(profile["rotation"]) is int and 0<=profile["rotation"]<=3,"Invalid rotation")
    require(isinstance(profile["locale"],str) and re.fullmatch(r"[A-Za-z0-9_-]{2,40}",profile["locale"]),"Invalid locale")
    require(isinstance(profile["ui_mode"],str) and re.fullmatch(r"0x[0-9a-f]+",profile["ui_mode"]),"Invalid UI mode")


def adb_profile(device, package):
    """Read-only typed ADB argv; no arbitrary shell command or package launch."""
    from service.platform.adb.adb import Adb
    from service.platform.adb.adb_command import AdbCommand
    adb=Adb(device_id=device)
    binary=AdbCommand.SCREEN_CAP.get_argv(device_id=device)[0]
    def shell(*args):
        result=adb.run_argv([binary,"shell",*args],timeout=5)
        check(result.ok,"PROFILE_PROBE_FAILED","Android identity probe failed",
              {"query":args[0],"timed_out":result.timed_out,"returncode":result.returncode})
        return result.stdout
    def one(pattern,text,what):
        values=set(re.findall(pattern,text,re.MULTILINE))
        check(len(values)==1,"PROFILE_UNKNOWN",f"Cannot establish unique {what}")
        return next(iter(values))
    focus=one(r"mCurrentFocus=Window\{[^\r\n]*?\bu\d+\s+([\w.]+)/",shell("dumpsys","window"),"focused package")
    activities=shell("dumpsys","activity","activities")
    resumed=one(r"(?:topResumedActivity|mResumedActivity)\s*[:=]\s*ActivityRecord\{[^\r\n]*?\bu\d+\s+([\w.]+)/",activities,"resumed package")
    check(focus==resumed==package,"APP_MISMATCH","Expected app is not both focused and resumed",
          {"expected":package,"focused":focus,"resumed":resumed})
    rotation=int(one(r"SurfaceOrientation:\s*([0-3])\b",shell("dumpsys","input"),"display rotation"))
    locale=shell("getprop","persist.sys.locale").strip() or shell("getprop","ro.product.locale").strip()
    version=int(one(r"^\s*versionCode=(\d+)\b",shell("dumpsys","package",package),"version code"))
    mode=one(r"\bmCurUiMode=(0x[0-9a-fA-F]+)\b",shell("dumpsys","uimode"),"UI mode").lower()
    observed={"package":focus,"version_code":version,"rotation":rotation,"locale":locale,"ui_mode":mode}
    profile_shape(observed)
    return observed


class WorkflowRuntime:
    def __init__(self,store:FrameStore,*,observation=None,actions=None,probe=None,clock=None,sleep=None):
        self.store=store
        self.builder=WorkflowBuilder(store)
        self.obs=observation or ObservationService(store)
        self.actions=actions or ActionService(store,platform_factory=self.obs._platform_factory)
        self.refs=RefRegistry(store.store_dir)
        self.probe=probe or adb_profile
        self.clock=clock or time.monotonic
        self.sleep=sleep or time.sleep
        self.cv=OpenCvService()
        self.root=store.store_dir/"runtime"

    def _path(self,kind,identifier):
        pattern=r"bind_[a-f0-9]{64}" if kind=="bindings" else r"run_[a-f0-9]{32}"
        require(isinstance(identifier,str) and re.fullmatch(pattern,identifier),"Invalid runtime identifier")
        return self.root/kind/(identifier+".json")

    def _load(self,kind,identifier):
        path=self._path(kind,identifier)
        require(path.is_file() and not path.is_symlink(),"Runtime receipt not found")
        return json.loads(path.read_text(encoding="utf-8"))

    def _persist(self,run):
        run["updated_at"]=time.time()
        _atomic_write_json(self._path("runs",run["run_id"]),run)

    def _definition(self,wid,device,profile):
        profile_shape(profile)
        require(isinstance(device,str) and device not in ("adb","desktop") and re.fullmatch(r"[A-Za-z0-9_.:-]+",device),
                "Explicit Android serial required")
        self.builder._validate(wid)
        item=self.builder.inspect(wid)
        d=item["definition"]
        require(d["schema_version"]==1 and d["validation"]["status"]=="offline_pass","Unsupported workflow schema")
        require(d["source"]["device_id"]==device,"Device differs from source workflow")
        require(d["geometry"]["rotation"] is None or d["geometry"]["rotation"]==profile["rotation"],"Source rotation differs")
        templates={}
        directory=Path(item["bundle_path"])
        for spec in [s["guard"]["template"] for s in d["states"]]+[s["action"]["template"] for s in d["steps"]]:
            sha=spec["sha256"]
            require(spec["path"]==f"templates/{sha}.png","Invalid template path")
            data=(directory/spec["path"]).read_bytes()
            require(digest(data)==sha,"Template hash mismatch")
            templates[sha]=decode(data)
        return d,templates

    def _profile(self,device,expected):
        observed=self.probe(device,expected["package"])
        check(observed==expected,"PROFILE_MISMATCH","Android profile changed",{"expected":expected,"observed":observed})
        return observed

    def _capture(self,device,profile,definition,observe):
        self._profile(device,profile)
        token=protect_new_frames.set(True)
        try:
            snap=self.obs.snapshot(device)
        finally:
            protect_new_frames.reset(token)
        f=snap["frame"]
        fid=f["frame_id"]
        # Journal actual frame even if the subsequent profile/geometry check fails.
        observe(fid)
        self._profile(device,profile)
        geometry=definition["geometry"]
        check(f["device_id"]==device and f["width"]==geometry["width"] and f["height"]==geometry["height"],
              "GEOMETRY_MISMATCH","Live frame geometry differs from workflow",
              {"frame_id":fid,"width":f["width"],"height":f["height"]})
        return self.store.get_frame(fid,device_id=device),self.store.load_image(fid,device_id=device)

    def _matches(self,image,spec,templates):
        return self.cv.find_all(image,templates[spec["template"]["sha256"]],threshold=spec["threshold"],
                                max_results=2,color_mode=spec["color_mode"])

    def _classify(self,image,definition,templates):
        matches={}
        for state in definition["states"]:
            m=self._matches(image,state["guard"],templates)
            matches[state["id"]]={"count":len(m),"score":round(m[0].score,7) if m else None}
        hits=[sid for sid,v in matches.items() if v["count"]==1]
        ambiguous=any(v["count"]>1 for v in matches.values()) or len(hits)>1
        return {"state":hits[0] if len(hits)==1 and not ambiguous else None,
                "ambiguous":ambiguous,"guards":matches}

    def _target(self,image,step,templates):
        m=self._matches(image,step["action"],templates)
        check(len(m)==1,"TARGET_NOT_UNIQUE","Expected exactly one live action target",
              {"match_count":len(m),"step_id":step["id"]})
        return m[0]

    def qualify(self,workflow_id,device,profile):
        """Read-only live preflight. Does not assert runtime completion."""
        with workspace_lock(self.store):
            d,templates=self._definition(workflow_id,device,profile)
            frames=[]
            f,img=self._capture(device,profile,d,frames.append)
            state=self._classify(img,d,templates)
            check(state["state"]==d["initial_state"] and not state["ambiguous"],"INITIAL_STATE_MISMATCH",
                  "Current screen is not uniquely the workflow initial state",{"frame_id":f.frame_id,**state})
            m=self._target(img,d["steps"][0],templates)
            body={"workflow_id":workflow_id,"device":device,"profile":profile}
            bid="bind_"+digest(canonical(body))
            path=self._path("bindings",bid)
            if not path.exists():
                _atomic_write_json(path,{"binding_id":bid,**body,"qualified_at":time.time(),
                                         "frame_id":f.frame_id,"state":state,"first_target_score":m.score})
            else:
                saved=self._load("bindings",bid)
                require(all(saved.get(k)==v for k,v in {"binding_id":bid,**body}.items()),"Binding changed")
            return {"binding_id":bid,**body,"status":"preflight_pass","frame_id":f.frame_id,
                    "state":state,"first_target_score":m.score,"live_runtime_qualified":False}

    def _binding(self,bid):
        binding=self._load("bindings",bid)
        body={k:binding[k] for k in ("workflow_id","device","profile")}
        require(binding["binding_id"]==bid and "bind_"+digest(canonical(body))==bid,"Binding content changed")
        return binding

    def _summary(self,run):
        result={k:run.get(k) for k in ("run_id","workflow_id","binding_id","device","status","started_at",
                "updated_at","finished_at","current_step","last_frame_id","last_confirmed_state","reason",
                "action_outcome","completed_steps","profile")}
        result["steps"]=[{**{k:v for k,v in step.items() if k!="post_observations"},
                          "post_capture_count":len(step["post_observations"]),
                          "latest_post_observation":step["post_observations"][-1] if step["post_observations"] else None}
                         for step in run["steps"]]
        return result

    def run(self,binding_id,run_id):
        with workspace_lock(self.store):
            return self._run_locked(binding_id,run_id)

    def _run_locked(self,binding_id,run_id):
        path=self._path("runs",run_id)
        if path.exists():
            old=self._load("runs",run_id)
            require(old["binding_id"]==binding_id,"Run ID already bound to another request")
            # Lock acquired: an unfinished receipt has no active writer. Never replay it.
            if old["status"]=="running":
                old["status"]="interrupted"
                old["reason"]={"code":"INTERRUPTED","message":"Previous process ended without terminal receipt; inspect actual state before any new action."}
                old["finished_at"]=time.time()
                self._persist(old)
            return {**self._summary(old),"duplicate_request":True}
        b=self._binding(binding_id)
        device,profile,wid=b["device"],b["profile"],b["workflow_id"]
        run={"run_id":run_id,"workflow_id":wid,"binding_id":binding_id,"device":device,"profile":profile,
             "status":"running","started_at":time.time(),"finished_at":None,"current_step":None,
             "last_frame_id":None,"last_confirmed_state":None,"reason":None,
             "action_outcome":"not_attempted","completed_steps":0,"steps":[],"frames":[]}
        self._persist(run)
        def observe(fid):
            run["frames"].append(fid)
            run["last_frame_id"]=fid
            self._persist(run)
        try:
            from vision_app.lifecycle import LifecycleService
            LifecycleService(self.store, runtime=self).guard_run(wid,device,profile)
            d,templates=self._definition(wid,device,profile)
            for step in d["steps"]:
                rec={"step_id":step["id"],"from":step["from"],"to":step["to"],"status":"observing",
                     "pre_frame_id":None,"post_frame_id":None,"target":None,"action_receipt":None,
                     "post_observations":[]}
                run["steps"].append(rec)
                run["current_step"]=step["id"]
                run["action_outcome"]="not_attempted"
                self._persist(run)
                f,img=self._capture(device,profile,d,observe)
                rec["pre_frame_id"]=f.frame_id
                classification=self._classify(img,d,templates)
                rec["pre_state"]=classification
                check(classification["state"]==step["from"] and not classification["ambiguous"],
                      "PRECONDITION_FAILED","Expected state is not uniquely recognized",classification)
                run["last_confirmed_state"]=step["from"]
                m=self._target(img,step,templates)
                ref=self.refs.save(_map_match_to_ref(f,"workflow_"+step["id"],m))
                rec["target"]={"ref_id":ref.ref_id,"frame_id":f.frame_id,"score":m.score,
                               "device_bbox":list(ref.device_bbox),"template_sha256":step["action"]["template"]["sha256"]}
                self._profile(device,profile)
                age=step["action"]["max_ref_age_seconds"]
                check(0<=time.time()-f.timestamp<=age,"FRAME_STALE","Live pre-frame expired before click")
                rec["status"]="action_pending"
                run["action_outcome"]="unknown"
                self._persist(run)
                receipt=self.actions.click(device,ref_id=ref.ref_id,max_age_seconds=age)
                rec["action_receipt"]=receipt
                rec["status"]="verifying"
                run["action_outcome"]="executed_unverified"
                self._persist(run)
                deadline=self.clock()+step["postcondition"]["timeout_seconds"]
                for _ in range(MAX_CAPTURES):
                    if self.clock()>deadline:
                        break
                    post,pimg=self._capture(device,profile,d,observe)
                    state=self._classify(pimg,d,templates)
                    rec["post_observations"].append({"frame_id":post.frame_id,**state})
                    self._persist(run)
                    if self.clock()>deadline:
                        break
                    check(not state["ambiguous"],"POST_STATE_AMBIGUOUS","Ambiguous live post-state",state)
                    if state["state"]==step["to"]:
                        rec["status"]="verified"
                        rec["post_frame_id"]=post.frame_id
                        run["last_confirmed_state"]=step["to"]
                        run["completed_steps"]+=1
                        run["action_outcome"]="verified"
                        self._persist(run)
                        break
                    check(state["state"] in (None,step["from"]),"UNEXPECTED_STATE","Unexpected known destination state",state)
                    remaining=deadline-self.clock()
                    if remaining>0:
                        self.sleep(min(POLL_SECONDS,remaining))
                check(rec["status"]=="verified","POSTCONDITION_TIMEOUT","Destination guard not verified within wait budget")
            run["status"]="completed"
            run["current_step"]=None
        except Exception as exc:
            run["status"]="needs_agent"
            run["reason"]={"code":getattr(exc,"code","RUNTIME_ERROR"),"message":str(exc),
                           "details":getattr(exc,"details",{})}
            if run["steps"] and run["steps"][-1]["status"]!="verified":
                run["steps"][-1]["status"]="needs_agent"
        run["finished_at"]=time.time()
        self._persist(run)
        return self._summary(run)


    def inspect(self,run_id):
        run=self._load("runs",run_id)
        return {**run,"note":"running receipt may be active or interrupted; never blindly replay. Same run ID is idempotent."}

    def list(self,limit=20,after=None):
        require(type(limit)==int and 1<=limit<=50,"Invalid limit")
        if after is not None: self._path("runs",after)
        ids=sorted(p.stem for p in (self.root/"runs").glob("run_*.json")
                   if re.fullmatch(r"run_[a-f0-9]{32}",p.stem) and (after is None or p.stem>after))
        items=[]
        for rid in ids[:limit]:
            r=self._load("runs",rid)
            items.append({k:r.get(k) for k in ("run_id","workflow_id","device","status","completed_steps","updated_at","reason")})
        return {"items":items,"next_cursor":items[-1]["run_id"] if len(ids)>limit else None}

    def query(self,action,**args):
        require(action in ("qualify","run","inspect","list"),"Unknown runtime action")
        return getattr(self,action)(**args)


def runtime_tool_definitions():
    string={"type":"string"}
    integer={"type":"integer"}
    profile={"type":"object","properties":{"package":string,"version_code":integer,"rotation":integer,
             "locale":string,"ui_mode":string},"required":list(PROFILE_FIELDS),"additionalProperties":False}
    specs={
        "qualify":({"workflow_id":string,"device":string,"profile":profile},["workflow_id","device","profile"],
                   "Read-only Android preflight; bind explicit profile and validate initial state/target."),
        "run":({"binding_id":string,"run_id":string},["binding_id","run_id"],
               "Execute one deterministic workflow run. Use unique run_<32 lowercase hex>; same ID never replays."),
        "inspect":({"run_id":string},["run_id"],"Inspect durable run journal, frames and failure handoff."),
        "list":({"limit":{"type":"integer","minimum":1,"maximum":50},"after":string},[],"List runtime receipts.")}
    return [{"name":"vision_runtime_"+name,"description":desc,
             "inputSchema":{"type":"object","properties":props,"required":required,"additionalProperties":False}}
            for name,(props,required,desc) in specs.items()]
