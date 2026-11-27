"""Offline evidence-bound Workflow Builder; deliberately no runtime or device adapter."""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import tempfile
from pathlib import Path

import cv2
import numpy as np

from service.core.opencv.open_cv_service import OpenCvService
from vision_app.assets import RefRegistry
from vision_app.recorder import Recorder, _decode
from vision_app.store import FrameStore, _atomic_write_bytes, _atomic_write_json

ACTIONS = ("click", "swipe", "type", "key")
VERSION = 1


class WorkflowError(ValueError):
    """Invalid or insufficient workflow evidence."""


def require(test, message):
    if not test:
        raise WorkflowError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False,
                      separators=(",", ":")).encode("utf-8")


def fields(value, expected, where):
    require(isinstance(value, dict) and set(value) == set(expected), f"Invalid fields: {where}")


def label(value, where):
    require(isinstance(value, str) and 0 < len(value.strip()) <= 500, f"Invalid {where}")
    return value


def number(value, low, high, where):
    require(type(value) in (int, float) and math.isfinite(value) and low <= value <= high,
            f"Invalid {where}")
    return float(value)


def body(event):
    result = event["result"] or {}
    return result.get("result", result) if "command" in result else result


def source_frame(event):
    b = body(event)
    return b.get("frame", b).get("frame_id")


def encode(image):
    ok, data = cv2.imencode(".png", image)
    require(ok, "Cannot encode marker")
    return data.tobytes()


def decode(data):
    image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    require(image is not None, "Invalid template PNG")
    return image


class WorkflowBuilder:
    def __init__(self, store: FrameStore):
        self.store = store
        self.rec = Recorder(store)
        self.root = store.store_dir / "workflows"
        self.cv = OpenCvService()

    def candidates(self, session_id, limit=20, after=0):
        self.rec._page(limit, after)
        self.rec.status(session_id)
        with self.rec.db() as db:
            rows = db.execute("""SELECT * FROM events WHERE session_id=? AND sequence>?
                AND operation IN ('click','swipe','type','key') ORDER BY sequence LIMIT ?""",
                              (session_id, after, limit+1)).fetchall()
        items = []
        for row in rows[:limit]:
            e = _decode(row)
            b = body(e)
            supported = e["operation"] == "click" and b.get("source", {}).get("mode") == "ref"
            items.append({"event_id":e["event_id"], "sequence":e["sequence"], "operation":e["operation"],
                          "status":e["status"], "supported":supported, "target":b.get("source",{}).get("target"),
                          "frame_id":b.get("source",{}).get("frame_id"),
                          "review_required":True})
        return {"items":items,"next_cursor":items[-1]["sequence"] if len(rows)>limit else None}

    def _events(self, sid):
        with self.rec.db() as db:
            rows = db.execute("SELECT * FROM events WHERE session_id=? ORDER BY sequence LIMIT 1001",(sid,)).fetchall()
            anns = db.execute("SELECT * FROM annotations WHERE session_id=? ORDER BY rowid LIMIT 1001",(sid,)).fetchall()
        require(len(rows)<=1000 and len(anns)<=1000, "Source session exceeds v1 compilation limit")
        return {r["event_id"]:_decode(r) for r in rows}, {r["annotation_id"]:_decode(r) for r in anns}

    def _compile(self, sid, plan):
        fields(plan, ("name","goal","states","steps","excluded_actions"), "plan")
        label(plan["name"],"name")
        label(plan["goal"],"goal")
        require(isinstance(plan["states"],list) and 2<=len(plan["states"])<=20,"Need 2..20 states")
        require(isinstance(plan["steps"],list) and 1<=len(plan["steps"])<=20,"Need 1..20 steps")
        require(isinstance(plan["excluded_actions"],list) and len(plan["excluded_actions"])<=1000,"Invalid exclusions")
        require(len(canonical(plan))<=65536,"Plan too large")
        session = self.rec.status(sid)
        require(session["status"]=="stopped","Source session must be stopped")
        device = session["device_id"]
        events, anns = self._events(sid)
        action_events = {eid:e for eid,e in events.items() if e["operation"] in ACTIONS}
        excluded = {}
        for x in plan["excluded_actions"]:
            fields(x,("event_id","reason"),"excluded action")
            eid = x["event_id"]
            require(eid in action_events and eid not in excluded,"Unknown or duplicate excluded action")
            excluded[eid] = label(x["reason"],"exclusion reason")

        def event(eid, operation):
            require(isinstance(eid,str) and eid in events,"Unknown source event")
            e=events[eid]
            require(e["operation"]==operation and e["status"]=="success" and e["device_id"]==device
                    and (e["result"] or {}).get("ok") is True, f"Invalid {operation} evidence: {eid}")
            return e

        frames = {}
        frame_hashes = {}
        geometry = None
        def frame(e):
            nonlocal geometry
            fid = source_frame(e)
            require(isinstance(fid,str) and fid in e["evidence"]["frames"],"Snapshot lacks frame evidence")
            if fid not in frames:
                f=self.store.get_frame(fid,device_id=device)
                require(f.protected and f.parent_id is None and f.width==f.source_width and f.height==f.source_height
                        and f.transform.to_dict()=={"offset_x":0.0,"offset_y":0.0,"scale_x":1.0,"scale_y":1.0},
                        "Need protected original full-device snapshot")
                g=(f.width,f.height,f.rotation)
                if geometry is None: geometry=g
                require(g==geometry,"Source geometry changed")
                path=self.store.resolve_image_path(f.image_path)
                data=path.read_bytes()
                img=decode(data)
                require(img.shape[:2]==(f.height,f.width),"Frame dimensions mismatch")
                frames[fid]=img
                frame_hashes[fid]=digest(data)
            return fid,frames[fid]

        blobs={}
        def template(data):
            sha=digest(data)
            blobs[sha]=data
            return {"sha256":sha,"path":f"templates/{sha}.png"}

        states={}
        for s in plan["states"]:
            fields(s,("id","label","event_id","region","threshold"),"state")
            state_id=s["id"]
            require(isinstance(state_id,str) and re.fullmatch(r"[a-z][a-z0-9_-]{0,39}",state_id)
                    and state_id not in states,"Invalid or duplicate state ID")
            e=event(s["event_id"],"snapshot")
            fid,img=frame(e)
            region=s["region"]
            require(isinstance(region,list) and len(region)==4 and all(type(x)==int for x in region),"Invalid marker ROI")
            x1,y1,x2,y2=region
            h,w=img.shape[:2]
            require(0<=x1<x2<=w and 0<=y1<y2<=h and x2-x1>=8 and y2-y1>=8,"Invalid marker bounds")
            marker=img[y1:y2,x1:x2]
            require(float(np.std(cv2.cvtColor(marker,cv2.COLOR_BGR2GRAY)))>=3,"Marker has insufficient visual detail")
            asset=template(encode(marker))
            threshold=number(s["threshold"],0.8,1,"marker threshold")
            states[state_id]={"id":state_id,"label":label(s["label"],"state label"),
                              "guard":{"kind":"unique_template","template":asset,"threshold":threshold,"color_mode":"gray"},
                              "provenance":{"event_id":e["event_id"],"frame_id":fid,"region":region}}

        steps=[]
        selected=set()
        used_evidence={s["event_id"] for s in plan["states"]}
        used_annotations=set()
        wait_labels={}
        target_checks=[]
        ref_hashes={}
        previous=None
        for idx,s in enumerate(plan["steps"],1):
            fields(s,("from","to","pre_event_id","find_event_id","action_event_id","wait_event_id",
                      "post_event_id","annotation_id"),"step")
            a,z=s["from"],s["to"]
            require(a in states and z in states and a!=z,"Unknown or identical step states")
            pre=event(s["pre_event_id"],"snapshot")
            find=event(s["find_event_id"],"find")
            click=event(s["action_event_id"],"click")
            wait=event(s["wait_event_id"],"wait")
            post=event(s["post_event_id"],"snapshot")
            chain=[pre,find,click,wait,post]
            seq=[e["sequence"] for e in chain]
            require(seq==sorted(set(seq)),"Step evidence out of order")
            require(previous is None or (previous["to"]==a and previous["post_sequence"]<=seq[0]),
                    "Disconnected or overlapping workflow steps")
            require(click["event_id"] not in selected and click["event_id"] not in excluded,"Action reused or excluded")
            selected.add(click["event_id"])
            require(not any(seq[0]<=e["sequence"]<=seq[-1] and e["event_id"]!=click["event_id"]
                            for e in action_events.values()),"Unaccounted action inside transition")
            pre_id,pre_img=frame(pre)
            post_id,_=frame(post)
            require(pre_id!=post_id,"Postcondition must use a distinct actual snapshot")
            f,c,w=map(body,(find,click,wait))
            source=c.get("source",{})
            matches=f.get("matches",[])
            require(find["inputs"].get("frame_id",find["inputs"].get("frame"))==pre_id
                    and find["inputs"].get("target")==f.get("target")
                    and f.get("frame_id")==pre_id and f.get("found") is True and f.get("count")==1
                    and len(matches)==1 and (find["inputs"].get("all") is True or find["inputs"].get("find_all") is True),
                    "Find must establish unique reference on actual pre-frame")
            match=matches[0]
            rid=match.get("ref_id")
            require(isinstance(rid,str) and click["inputs"].get("ref")==rid
                    and source.get("mode")=="ref" and source.get("ref_id")==rid and source.get("frame_id")==pre_id
                    and source.get("target")==f.get("target") and c.get("status")=="executed"
                    and c.get("verified") is False and rid in find["evidence"]["references"]
                    and rid in click["evidence"]["references"],"Click is not linked to unique scoped find")
            ref=RefRegistry(self.store.store_dir).validate(rid,device_id=device,frame_store=self.store)
            require(ref.to_dict()==match and ref.frame_id==pre_id and ref.target==f["target"] and list(ref.bbox)==match.get("bbox")
                    and list(ref.device_bbox)==source.get("device_bbox")
                    and [c.get("target",{}).get("x"),c.get("target",{}).get("y")]==list(ref.device_center),
                    "Scoped reference/receipt mismatch")
            ref_hashes[rid]=digest(canonical(ref.to_dict()))
            max_age=click["inputs"].get("max_age_seconds",click["inputs"].get("max_age"))
            max_age=number(max_age,0.001,60,"reference max age")
            require(0<=c["executed_at"]-ref.created_at<=max_age,"Historical click reference expired")
            require(0<=c["executed_at"]-self.store.get_frame(pre_id).timestamp<=max_age,"Historical pre-frame too old")
            threshold=number(find["inputs"].get("threshold",0.8),0.8,1,"target threshold")
            mode=find["inputs"].get("color_mode","gray")
            require(mode in ("gray","bgr"),"Unsupported color mode")
            revisions=[x for x in find["evidence"]["assets"] if x.get("name")==f["target"]]
            require(len(revisions)==1,"Find lacks exact asset revision")
            revision=revisions[0]
            sha=revision["sha256"]
            require(isinstance(sha,str) and re.fullmatch(r"[a-f0-9]{64}",sha),"Invalid asset digest")
            path=(self.store.store_dir/revision["retained_path"]).resolve()
            require(path.parent==(self.store.store_dir/"recorded_assets").resolve() and path.name==sha+".png",
                    "Invalid retained asset path")
            data=path.read_bytes()
            require(digest(data)==sha,"Asset revision hash mismatch")
            t=decode(data)
            require(t.shape[:2]==(revision["height"],revision["width"]),"Asset dimensions mismatch")
            observed=self.cv.find_all(pre_img,t,threshold=threshold,max_results=2,color_mode=mode)
            require(len(observed)==1 and list(observed[0].bbox)==list(ref.bbox),"Offline target uniqueness/position failed")
            require(w.get("condition")=="changed" and w.get("verified") is True and
                    wait["inputs"].get("baseline_frame_id",wait["inputs"].get("baseline"))==pre_id
                    and pre_id in wait["evidence"]["frames"],"Missing changed-wait evidence")
            timeout=number(wait["inputs"].get("timeout"),0.001,60,"wait timeout")
            number(w.get("elapsed_seconds"),0,timeout,"recorded wait elapsed")
            wait_id=w.get("frame_id")
            require(isinstance(wait_id,str) and wait_id!=pre_id and wait_id in wait["evidence"]["frames"],
                    "Wait lacks actual result frame")
            wait_frame=self.store.get_frame(wait_id,device_id=device)
            require(wait_frame.protected and wait_frame.parent_id is None and wait_frame.width==wait_frame.source_width
                    and wait_frame.height==wait_frame.source_height and wait_frame.rotation==geometry[2],
                    "Wait evidence not protected full frame")
            require(c["executed_at"]<=wait_frame.timestamp<=self.store.get_frame(post_id).timestamp,
                    "Wait/post frame timestamps do not follow click")
            wait_data=self.store.resolve_image_path(wait_frame.image_path).read_bytes()
            wait_image=decode(wait_data)
            require(wait_image.shape[:2]==pre_img.shape[:2],"Wait evidence geometry mismatch")
            require(wait_id not in wait_labels or wait_labels[wait_id]==z,"Conflicting wait state labels")
            wait_labels[wait_id]=z
            frames[wait_id]=wait_image
            frame_hashes[wait_id]=digest(wait_data)
            ann=anns.get(s["annotation_id"])
            require(ann is not None and ann["event_id"]==post["event_id"]
                    and ann["timestamp"]>=post["timestamp"]
                    and ann["annotation"].get("verification")=="PASS"
                    and bool(ann["annotation"].get("state")) and bool(ann["annotation"].get("observation")),
                    "Explicit PASS annotation on post-snapshot required")
            # Later explicit FAIL/UNKNOWN cannot be ignored by selecting an older PASS.
            require(not any(x["event_id"]==post["event_id"] and x["timestamp"]>ann["timestamp"]
                            and x["annotation"].get("verification") in ("FAIL","UNKNOWN") for x in anns.values()),
                    "Later annotation disputes semantic verification")
            provenance={"pre_event_id":pre["event_id"],"find_event_id":find["event_id"],
                        "action_event_id":click["event_id"],"wait_event_id":wait["event_id"],
                        "post_event_id":post["event_id"],"annotation_id":ann["annotation_id"],
                        "source_frames":[pre_id,wait_id,post_id],"source_ref_id":rid,
                        "historical_match_bbox":list(ref.bbox),"source_asset_name":f["target"]}
            steps.append({"id":f"step_{idx}","from":a,"to":z,
                          "action":{"kind":"click_unique_template","template":template(data),
                                    "threshold":threshold,"color_mode":mode,"max_ref_age_seconds":max_age},
                          "postcondition":{"kind":"state_guard","state_id":z,"timeout_seconds":timeout},
                          "on_failure":"stop_and_return_to_agent","max_attempts":1,"provenance":provenance})
            target_checks.append({"step_id":f"step_{idx}","score":round(observed[0].score,7),"match_count":1})
            used_evidence.update(e["event_id"] for e in chain)
            used_annotations.add(ann["annotation_id"])
            previous={"to":z,"post_sequence":seq[-1]}

        require(selected|set(excluded)==set(action_events),"Every action must be selected or explicitly excluded")
        first=events[plan["steps"][0]["pre_event_id"]]["sequence"]
        last=events[plan["steps"][-1]["post_event_id"]]["sequence"]
        require(not any(first<=action_events[eid]["sequence"]<=last for eid in excluded),
                "Excluded action inside selected path")
        require(set(states)=={s[k] for s in steps for k in ("from","to")},"Unused states")
        # Marker evidence must come from a real path observation, not an arbitrary unrelated screenshot.
        path_frames={source_frame(events[s[k]]) for s in plan["steps"] for k in ("pre_event_id","post_event_id")}
        path_labels={}
        for s in plan["steps"]:
            for k,side in (("pre_event_id","from"),("post_event_id","to")):
                fid=source_frame(events[s[k]])
                require(fid not in path_labels or path_labels[fid]==s[side],"Conflicting frame state labels")
                path_labels[fid]=s[side]
        require(all(path_labels.get(s["provenance"]["frame_id"])==sid_ for sid_,s in states.items()),
                "State marker source must be a path snapshot of that state")
        for fid,state_id in wait_labels.items():
            require(fid not in path_labels or path_labels[fid]==state_id,"Conflicting wait state labels")
            path_labels[fid]=state_id
            path_frames.add(fid)
        checks=[]
        for state_id,state in states.items():
            guard=state["guard"]
            marker=decode(blobs[guard["template"]["sha256"]])
            for fid in sorted(path_frames):
                expected=path_labels[fid]==state_id
                matches=self.cv.find_all(frames[fid],marker,threshold=guard["threshold"],max_results=2,color_mode="gray")
                count=len(matches)
                require(count==(1 if expected else 0),f"State guard {state_id} failed on {fid}: expected {int(expected)}, got {count}")
                checks.append({"state_id":state_id,"frame_id":fid,"expected":expected,"match_count":count,
                               "score":round(matches[0].score,7) if matches else None})
        ignored=[{"event_id":e["event_id"],"sequence":e["sequence"],"operation":e["operation"],"status":e["status"]}
                 for e in events.values() if e["operation"] not in ACTIONS and e["status"]!="success"]
        definition={"schema_version":VERSION,"name":plan["name"],"goal":plan["goal"],
                    "source":{"session_id":sid,"device_id":device,"event_ids":sorted(used_evidence),
                              "frame_sha256":frame_hashes,"event_sha256":{eid:digest(canonical(events[eid])) for eid in sorted(used_evidence|set(excluded))},
                              "annotation_sha256":{aid:digest(canonical(anns[aid])) for aid in sorted(used_annotations)},
                              "ref_sha256":ref_hashes,
                              "excluded_actions":plan["excluded_actions"],
                              "non_success_observations":ignored},
                    "geometry":{"width":geometry[0],"height":geometry[1],"rotation":geometry[2]},
                    "initial_state":steps[0]["from"],"final_state":steps[-1]["to"],
                    "execution_contract":{"fresh_snapshot_per_step":True,"state_policy":"exactly_one_expected_guard",
                                          "target_policy":"unique_match_on_fresh_frame","unknown_state":"stop_and_return_to_agent",
                                          "application_identity":None,"application_binding_required":True},
                    "states":list(states.values()),"steps":steps,
                    "validation":{"status":"offline_pass","state_checks":checks,"target_checks":target_checks,
                                  "live_runtime_qualified":False},
                    "limitations":["Single recorded path; not a live runtime qualification.",
                                   "Device geometry, app/theme/locale and UI state must be rechecked before future execution.",
                                   "Application identity and rotation (when unknown) require live runtime qualification.",
                                   "No replay of historical coordinates or references."]}
        return definition,blobs

    def build(self, session_id, plan):
        return self._build_locked(session_id, plan)

    def _build_locked(self, session_id, plan):
        from vision_app.validation_context import evidence_snapshot
        with evidence_snapshot(self, session_id, plan) as snapshot:
            seals = snapshot.seals()
            try:
                definition, blobs = self._compile(session_id, plan)
            except Exception:
                with snapshot.commit(seals):
                    raise
            return self._publish_locked(definition, blobs, plan, snapshot, seals)

    def _publish_locked(self, definition, blobs, plan, snapshot, seals, finalize=None, *, additional=()):
        workflow_id="wf_"+digest(canonical({"definition":definition,"plan":plan}))
        target=self.root/workflow_id
        self.root.mkdir(parents=True,exist_ok=True)
        if target.exists():
            self._validate(workflow_id)
            with snapshot.commit(seals, additional=additional):
                return finalize() if finalize else self.inspect(workflow_id)
        staging=Path(tempfile.mkdtemp(prefix=".building_",dir=self.root))
        try:
            for sha,data in blobs.items():
                _atomic_write_bytes(staging/"templates"/(sha+".png"),data)
            _atomic_write_json(staging/"plan.json",plan)
            _atomic_write_json(staging/"definition.json",{"workflow_id":workflow_id,**definition})
            _atomic_write_json(staging/"source-seal.json", {"source_seal": seals[0]})
            with snapshot.commit(seals, additional=additional):
                os.replace(staging,target)
                if finalize:
                    return finalize()
        finally:
            if staging.exists(): shutil.rmtree(staging)
        return self.inspect(workflow_id)


    def _directory(self,wid):
        require(isinstance(wid,str) and re.fullmatch(r"wf_[a-f0-9]{64}",wid),"Invalid workflow ID")
        directory=self.root/wid
        require(directory.is_dir() and directory.resolve().parent==self.root.resolve(),"Workflow not found")
        return directory

    def inspect(self, workflow_id):
        directory=self._directory(workflow_id)
        definition=json.loads((directory/"definition.json").read_text(encoding="utf-8"))
        return {"workflow_id":workflow_id,"definition":definition,"bundle_path":str(directory)}

    def _validate(self,wid):
        from vision_app.validation_context import validate_cached
        return validate_cached(self,wid,self._validate_uncached)

    def _validate_uncached(self,wid):
        item=self.inspect(wid)
        directory=self._directory(wid)
        saved=item["definition"]
        plan=json.loads((directory/"plan.json").read_text(encoding="utf-8"))
        definition,blobs=self._compile(saved["source"]["session_id"],plan)
        expected="wf_"+digest(canonical({"definition":definition,"plan":plan}))
        require(wid==expected and saved=={"workflow_id":wid,**definition},"Workflow definition or source evidence changed")
        templates=directory/"templates"
        require(templates.resolve().parent==directory.resolve() and
                {p.name for p in templates.iterdir()}=={sha+".png" for sha in blobs},"Unexpected workflow template files")
        for sha,data in blobs.items():
            path=templates/(sha+".png")
            require(not path.is_symlink() and path.is_file() and path.read_bytes()==data,"Workflow template tampered")
        return {"workflow_id":wid,"status":"offline_pass","state_checks":len(definition["validation"]["state_checks"]),
                "target_checks":len(definition["validation"]["target_checks"]),"templates":len(blobs),
                "live_runtime_qualified":False}

    def validate(self,workflow_id):
        return self._validate(workflow_id)

    def list(self,limit=20,after=None):
        require(type(limit)==int and 1<=limit<=50,"Invalid limit")
        require(after is None or isinstance(after,str) and re.fullmatch(r"wf_[a-f0-9]{64}",after),"Invalid cursor")
        paths=sorted(p.name for p in self.root.glob("wf_*") if re.fullmatch(r"wf_[a-f0-9]{64}",p.name) and p.is_dir()
                     and (after is None or p.name>after))
        items=[]
        for wid in paths[:limit]:
            d=self.inspect(wid)["definition"]
            items.append({"workflow_id":wid,"name":d["name"],"session_id":d["source"]["session_id"],
                          "steps":len(d["steps"]),"validation":d["validation"]["status"]})
        return {"items":items,"next_cursor":items[-1]["workflow_id"] if len(paths)>limit else None}

    def query(self,action,**args):
        require(action in ("candidates","build","inspect","validate","list"),"Unknown workflow action")
        return getattr(self,action)(**args)


def workflow_tool_definitions():
    string={"type":"string"}
    limit={"type":"integer","minimum":1,"maximum":50}
    specs={
        "candidates":({"session_id":string,"limit":limit,"after":{"type":"integer","minimum":0}},["session_id"],
                      "List actual action receipts for review, including failed/unsupported actions."),
        "build":({"session_id":string,"plan":{"type":"object"}},["session_id","plan"],
                 "Compile an explicitly reviewed click/state plan from a stopped Recorder session; offline only."),
        "inspect":({"workflow_id":string},["workflow_id"],"Inspect immutable workflow definition and bundle path."),
        "validate":({"workflow_id":string},["workflow_id"],"Revalidate source evidence and template integrity offline."),
        "list":({"limit":limit,"after":string},[],"List workflow definitions with bounded cursor pagination.")}
    return [{"name":"vision_workflow_"+name,"description":desc,
             "inputSchema":{"type":"object","properties":props,"required":required,"additionalProperties":False}}
            for name,(props,required,desc) in specs.items()]
