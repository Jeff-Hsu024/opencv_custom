"""Explicit lifecycle registry and read-only recovery routing."""
from __future__ import annotations

import json
import re
import time

from vision_app.recorder import Recorder, workspace_lock
from vision_app.recovery import RecoveryService, seal
from vision_app.runtime import WorkflowRuntime, RuntimeFault
from vision_app.workflow import require, label

MAX_ROUTES = 20


class LifecycleService:
    def __init__(self, store, *, runtime=None):
        self.store=store
        self.rec=Recorder(store)
        self.rt=runtime or WorkflowRuntime(store)
        self.recovery=RecoveryService(store)
        with self.rec.db() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS workflow_families(
                family_id TEXT PRIMARY KEY, device TEXT NOT NULL, profile TEXT NOT NULL,
                generation INTEGER NOT NULL, active_version INTEGER);
            CREATE TABLE IF NOT EXISTS workflow_versions(
                family_id TEXT NOT NULL REFERENCES workflow_families,
                version INTEGER NOT NULL, workflow_id TEXT UNIQUE NOT NULL,
                parent_version INTEGER, proof TEXT NOT NULL,
                created_at REAL NOT NULL, PRIMARY KEY(family_id,version));
            CREATE TABLE IF NOT EXISTS workflow_routes(
                route_id TEXT PRIMARY KEY, family_id TEXT NOT NULL REFERENCES workflow_families,
                parent_version INTEGER NOT NULL, child_workflow_id TEXT UNIQUE NOT NULL,
                proposal_id TEXT NOT NULL, qualification_id TEXT NOT NULL,
                run_id TEXT NOT NULL, enabled INTEGER NOT NULL,
                created_at REAL NOT NULL,
                FOREIGN KEY(family_id,parent_version) REFERENCES workflow_versions(family_id,version));
            CREATE TABLE IF NOT EXISTS workflow_lifecycle_log(
                seq INTEGER PRIMARY KEY AUTOINCREMENT, family_id TEXT NOT NULL REFERENCES workflow_families,
                generation INTEGER NOT NULL, operation TEXT NOT NULL, payload TEXT NOT NULL,
                created_at REAL NOT NULL, UNIQUE(family_id,generation));
            """)

    @staticmethod
    def _dict(row, key=None):
        require(row is not None,"Registry record not found")
        result=dict(row)
        if key:result[key]=json.loads(result[key])
        return result

    @staticmethod
    def _slug(family):
        require(isinstance(family,str) and re.fullmatch(r"[a-z][a-z0-9_-]{0,63}",family),"Invalid family ID")

    def _family(self,db,family):
        self._slug(family)
        return self._dict(db.execute("SELECT * FROM workflow_families WHERE family_id=?",(family,)).fetchone(),"profile")

    def _version(self,db,family,version):
        require(type(version) is int and version>0,"Invalid version number")
        return self._dict(db.execute("SELECT * FROM workflow_versions WHERE family_id=? AND version=?",
                                     (family,version)).fetchone(),"proof")

    def _cas(self,f,expected):
        require(type(expected) is int and expected==f["generation"],"Stale registry generation")

    def _log(self,db,f,op,reason,detail):
        label(reason,"reason")
        generation=f["generation"]+1
        db.execute("UPDATE workflow_families SET generation=? WHERE family_id=?",(generation,f["family_id"]))
        db.execute("INSERT INTO workflow_lifecycle_log(family_id,generation,operation,payload,created_at) VALUES(?,?,?,?,?)",
                   (f["family_id"],generation,op,json.dumps({"reason":reason,**detail},ensure_ascii=True),time.time()))

    def _frame(self,fid,device,geometry):
        f,img,sha=self.recovery._frame(fid,device)
        require((f.width,f.height)==(geometry["width"],geometry["height"]),"Proof frame geometry mismatch")
        return img,sha

    def _proof(self,wid,run_id):
        run=self.rt._load("runs",run_id)
        require(run["status"]=="completed" and run["workflow_id"]==wid,"Need completed matching runtime run")
        binding=self.rt._binding(run["binding_id"])
        require(all(binding[k]==run[k] for k in ("workflow_id","device","profile")),"Proof binding mismatch")
        d,t=self.rt._definition(wid,run["device"],run["profile"])
        require(run["completed_steps"]==len(d["steps"])==len(run["steps"]) and
                run["last_confirmed_state"]==d["final_state"] and run["action_outcome"]=="verified",
                "Incomplete proof run")
        hashes={}
        refs=set()
        historical_refs={step["provenance"]["source_ref_id"] for step in d["steps"]}
        for s,step in zip(run["steps"],d["steps"]):
            require(s["step_id"]==step["id"] and s["status"]=="verified","Invalid verified step")
            pre,ph=self._frame(s["pre_frame_id"],run["device"],d["geometry"])
            post,qh=self._frame(s["post_frame_id"],run["device"],d["geometry"])
            for image,expected in ((pre,step["from"]),(post,step["to"])):
                state=self.rt._classify(image,d,t)
                require(not state["ambiguous"] and state["state"]==expected,"Proof state guard mismatch")
            m=self.rt._matches(pre,step["action"],t)
            target=s["target"];receipt=s["action_receipt"]
            require(len(m)==1 and list(m[0].bbox)==target["device_bbox"] and
                    target["frame_id"]==s["pre_frame_id"] and target["ref_id"] not in refs and target["ref_id"] not in historical_refs and
                    target["template_sha256"]==step["action"]["template"]["sha256"],"Proof target mismatch")
            ref=self.rt.refs.get(target["ref_id"])
            require(ref.frame_id==s["pre_frame_id"] and ref.device_id==run["device"] and
                    list(ref.device_bbox)==target["device_bbox"] and
                    receipt["source"]["ref_id"]==ref.ref_id and receipt["source"]["frame_id"]==ref.frame_id and
                    receipt["status"]=="executed" and receipt["verified"] is False and receipt["device_id"]==run["device"] and
                    [receipt["target"]["x"],receipt["target"]["y"]]==list(ref.device_center),"Proof receipt mismatch")
            before=self.store.get_frame(s["pre_frame_id"])
            after=self.store.get_frame(s["post_frame_id"])
            require(before.timestamp<=ref.created_at<=receipt["executed_at"]<=after.timestamp
                    and receipt["executed_at"]-before.timestamp<=step["action"]["max_ref_age_seconds"],"Proof action chronology mismatch")
            refs.add(ref.ref_id)
            hashes[s["pre_frame_id"]]=ph;hashes[s["post_frame_id"]]=qh
            hashes[ref.ref_id]=seal(ref.to_dict())
        require(run["last_frame_id"]==run["steps"][-1]["post_frame_id"],"Proof endpoint mismatch")
        return {"run_id":run_id,"run_sha256":seal(run),"evidence_sha256":hashes,
                "device":run["device"],"profile":run["profile"]},run,d

    def _check_version(self,v):
        proof,run,d=self._proof(v["workflow_id"],v["proof"]["run_id"])
        require(proof==v["proof"],"Registered proof changed")
        return run,d

    def register(self,family_id,workflow_id,run_id,expected_generation,reason,parent_version=None):
        self._slug(family_id);label(reason,"reason")
        with workspace_lock(self.store):
            proof,run,d=self._proof(workflow_id,run_id)
            with self.rec.db() as db:
                existing=db.execute("SELECT * FROM workflow_families WHERE family_id=?",(family_id,)).fetchone()
                require(not db.execute("SELECT 1 FROM workflow_versions WHERE workflow_id=?",(workflow_id,)).fetchone()
                        and not db.execute("SELECT 1 FROM workflow_routes WHERE child_workflow_id=?",(workflow_id,)).fetchone(),
                        "Workflow already managed")
                if existing is None:
                    require(expected_generation==0 and type(expected_generation) is int and parent_version is None,
                            "New family requires generation 0 and no parent version")
                    db.execute("INSERT INTO workflow_families VALUES(?,?,?,?,NULL)",
                               (family_id,run["device"],json.dumps(run["profile"],ensure_ascii=True),0))
                    version=1
                else:
                    f=self._family(db,family_id);self._cas(f,expected_generation)
                    require(f["device"]==run["device"] and f["profile"]==run["profile"],"Family device/profile mismatch")
                    require(parent_version is not None,"Explicit parent version required")
                    parent=self._version(db,family_id,parent_version)
                    self._check_version(parent)
                    pd,pt=self.rt._definition(parent["workflow_id"],run["device"],run["profile"])
                    require(d["goal"]==pd["goal"],"Version goal differs from parent")
                    for fid,expected in ((run["steps"][0]["pre_frame_id"],pd["initial_state"]),
                                         (run["last_frame_id"],pd["final_state"])):
                        img,_=self._frame(fid,run["device"],pd["geometry"])
                        state=self.rt._classify(img,pd,pt)
                        require(state["state"]==expected and not state["ambiguous"],"Version endpoint differs from parent")
                    version=db.execute("SELECT max(version)+1 FROM workflow_versions WHERE family_id=?",(family_id,)).fetchone()[0]
                f=self._family(db,family_id)
                self._cas(f,expected_generation)
                db.execute("INSERT INTO workflow_versions VALUES(?,?,?,?,?,?)",
                           (family_id,version,workflow_id,parent_version,json.dumps(proof,ensure_ascii=True),time.time()))
                self._log(db,f,"register",reason,{"version":version,"workflow_id":workflow_id,"parent_version":parent_version})
        return self.inspect(family_id)

    def _switch(self,family_id,version,expected_generation,reason,op):
        label(reason,"reason")
        with workspace_lock(self.store),self.rec.db() as db:
            f=self._family(db,family_id);self._cas(f,expected_generation)
            old=f["active_version"]
            if op=="disable":
                require(old is not None,"Family already disabled")
                version=None
            else:
                require(version!=old,"Version already active")
                v=self._version(db,family_id,version)
                self._check_version(v)
                if op=="rollback":
                    logs=db.execute("SELECT payload FROM workflow_lifecycle_log WHERE family_id=? AND operation IN ('activate','rollback')",
                                    (family_id,)).fetchall()
                    require(any(json.loads(r["payload"])["to_version"]==version for r in logs),"Rollback requires previously active version")
            db.execute("UPDATE workflow_families SET active_version=? WHERE family_id=?",(version,family_id))
            self._log(db,f,op,reason,{"from_version":old,"to_version":version})
        return self.inspect(family_id)

    def activate(self,family_id,version,expected_generation,reason):
        return self._switch(family_id,version,expected_generation,reason,"activate")

    def rollback(self,family_id,version,expected_generation,reason):
        return self._switch(family_id,version,expected_generation,reason,"rollback")

    def disable(self,family_id,expected_generation,reason):
        return self._switch(family_id,None,expected_generation,reason,"disable")

    def _qualified_route(self,route):
        q=self.recovery._verify_locked(route["proposal_id"],route["run_id"],persist=False)
        require(q["qualification_id"]==route["qualification_id"],"Route qualification changed")
        p=self.recovery._proposal(route["proposal_id"])["payload"]
        self._proof(route["child_workflow_id"],route["run_id"])
        require(p["kind"]=="recovery_route" and p["child_workflow_id"]==route["child_workflow_id"],"Route lineage mismatch")
        return p,q

    def link(self,family_id,parent_version,proposal_id,qualification_id,expected_generation,reason):
        label(reason,"reason")
        with workspace_lock(self.store):
            with self.rec.db() as db:
                f=self._family(db,family_id);self._cas(f,expected_generation)
                v=self._version(db,family_id,parent_version)
                q=self.recovery._row(db,"recovery_qualifications","qualification_id",qualification_id)
            route={"proposal_id":proposal_id,"qualification_id":qualification_id,
                   "run_id":q["run_id"],"child_workflow_id":q["payload"]["child_workflow_id"]}
            p,_=self._qualified_route(route)
            require(p["parent_workflow_id"]==v["workflow_id"] and p["device"]==f["device"]
                    and p["profile"]==f["profile"],"Route parent/profile mismatch")
            rid="route_"+seal({"family_id":family_id,"parent_version":parent_version,**route})
            self._check_version(v)
            with self.rec.db() as db:
                require(not db.execute("SELECT 1 FROM workflow_versions WHERE workflow_id=?",(route["child_workflow_id"],)).fetchone(),
                        "Recovery child already managed as primary")
                require(db.execute("SELECT count(*) FROM workflow_routes WHERE family_id=? AND parent_version=?",
                                   (family_id,parent_version)).fetchone()[0]<MAX_ROUTES,"Route limit reached")
                require(not db.execute("SELECT 1 FROM workflow_routes WHERE child_workflow_id=?",(route["child_workflow_id"],)).fetchone(),
                        "Recovery child already linked")
                db.execute("INSERT INTO workflow_routes VALUES(?,?,?,?,?,?,?,?,?)",
                           (rid,family_id,parent_version,route["child_workflow_id"],proposal_id,qualification_id,q["run_id"],1,time.time()))
                self._log(db,f,"link",reason,{"route_id":rid,"parent_version":parent_version,"child_workflow_id":route["child_workflow_id"]})
        return self.inspect(family_id)

    def route_status(self,family_id,route_id,enabled,expected_generation,reason):
        require(type(enabled) is bool,"enabled must be boolean");label(reason,"reason")
        with workspace_lock(self.store):
            with self.rec.db() as db:
                f=self._family(db,family_id);self._cas(f,expected_generation)
                route=self._dict(db.execute("SELECT * FROM workflow_routes WHERE family_id=? AND route_id=?",(family_id,route_id)).fetchone())
            require(bool(route["enabled"])!=enabled,"Route already in requested state")
            if enabled:self._qualified_route(route)
            with self.rec.db() as db:
                db.execute("UPDATE workflow_routes SET enabled=? WHERE route_id=?",(int(enabled),route_id))
                self._log(db,f,"route_status",reason,{"route_id":route_id,"enabled":enabled})
        return self.inspect(family_id)

    def guard_run(self,wid,device,profile):
        """Check registry admission while Runtime holds the device owner."""
        with self.rec.db() as db:
            v=db.execute("SELECT * FROM workflow_versions WHERE workflow_id=?",(wid,)).fetchone()
            r=db.execute("SELECT * FROM workflow_routes WHERE child_workflow_id=?",(wid,)).fetchone()
            if not v and not r:return
            row=dict(v or r);f=self._family(db,row["family_id"])
            enabled=(f["active_version"]==row["version"]) if v else (bool(row["enabled"]) and f["active_version"]==row["parent_version"])
        if not enabled:raise RuntimeFault("WORKFLOW_INACTIVE","Managed workflow or route is inactive")
        if f["device"]!=device or f["profile"]!=profile:raise RuntimeFault("REGISTRY_PROFILE_MISMATCH","Managed workflow profile differs")
        if v:self._check_version(self._dict(v,"proof"))
        else:self._qualified_route(row)

    def select(self,family_id,run_id):
        """Read-only recommendation from a fresh frame. Never clicks or resumes."""
        with workspace_lock(self.store):
            with self.rec.db() as db:
                device=self._family(db,family_id)["device"]
            with self.rt.epochs.device_owner(device,legacy=True) as owner:
                if owner is None:
                    raise RuntimeFault("DEVICE_BUSY","Recovery selector device is busy")
                return self._select_locked(family_id,run_id,owner)

    def _select_locked(self,family_id,run_id,owner):
        with self.rec.db() as db:
            f=self._family(db,family_id)
            require(f["active_version"] is not None,"Family is disabled")
            v=self._version(db,family_id,f["active_version"])
            routes=[dict(r) for r in db.execute("SELECT * FROM workflow_routes WHERE family_id=? AND parent_version=? AND enabled=1 ORDER BY route_id",
                                                (family_id,v["version"]))]
        failed=self.rt._load("runs",run_id)
        binding=self.rt._binding(failed["binding_id"])
        require(all(binding[k]==failed[k] for k in ("workflow_id","device","profile")),"Failure binding mismatch")
        require(failed["status"]=="needs_agent" and failed["workflow_id"]==v["workflow_id"]
                and failed["device"]==f["device"] and failed["profile"]==f["profile"],"Run is not failed active version")
        if failed["action_outcome"]!="not_attempted" or (failed.get("reason") or {}).get("code")!="PRECONDITION_FAILED":
            return {"status":"manual_review","reason":"Uncertain action outcome or unsupported failure type","run_id":run_id,"selected":None}
        self._check_version(v)
        d,t=self.rt._definition(v["workflow_id"],f["device"],f["profile"])
        frame,img=self.rt._capture(f["device"],f["profile"],d,lambda _:None,owner)
        parent=self.rt._classify(img,d,t)
        base={"run_id":run_id,"family_id":family_id,"generation":f["generation"],"frame_id":frame.frame_id,
              "parent_state":parent,"selected":None,"automatic_execution":False}
        if parent["ambiguous"]:return {**base,"status":"manual_review","reason":"Ambiguous parent state"}
        candidates=[]
        for r in routes:
            p,q=self._qualified_route(r)
            require(p["parent_workflow_id"]==v["workflow_id"],"Route parent changed")
            child,ct=self.rt._definition(r["child_workflow_id"],f["device"],f["profile"])
            if child["geometry"]!=d["geometry"]:continue
            state=self.rt._classify(img,child,ct)
            if not state["ambiguous"] and state["state"]==child["initial_state"] and parent["state"]==p["anchor"]["parent_classification"]["state"]:
                m=self.rt._matches(img,child["steps"][0]["action"],ct)
                if len(m)==1:
                    candidates.append({"route_id":r["route_id"],"workflow_id":r["child_workflow_id"],
                                       "qualification_id":q["qualification_id"],"destination_state":p["destination_state"],
                                       "target_score":m[0].score})
        if len(candidates)==1:return {**base,"status":"selected","selected":candidates[0],"candidates":candidates}
        return {**base,"status":"no_match" if not candidates else "ambiguous","candidates":candidates}


    def inspect(self,family_id,limit=20,after=0,parent_version=None):
        self.rec._page(limit,after)
        with self.rec.db() as db:
            f=self._family(db,family_id)
            rows=db.execute("SELECT * FROM workflow_versions WHERE family_id=? AND version>? ORDER BY version LIMIT ?",
                            (family_id,after,limit+1)).fetchall()
            versions=[self._dict(r,"proof") for r in rows[:limit]]
            route_version=parent_version if parent_version is not None else f["active_version"]
            if route_version is not None:self._version(db,family_id,route_version)
            routes=[dict(r) for r in db.execute("SELECT * FROM workflow_routes WHERE family_id=? AND parent_version=? ORDER BY route_id",
                                                (family_id,route_version))]
        return {"family":f,"versions":{"items":versions,"next_cursor":versions[-1]["version"] if len(rows)>limit else None},
                "route_version":route_version,"active_version_routes":routes}

    def list(self,limit=20,after=0):
        self.rec._page(limit,after)
        with self.rec.db() as db:
            rows=db.execute("SELECT rowid AS cursor,* FROM workflow_families WHERE rowid>? ORDER BY rowid LIMIT ?",(after,limit+1)).fetchall()
        items=[self._dict(r,"profile") for r in rows[:limit]]
        return {"items":items,"next_cursor":items[-1]["cursor"] if len(rows)>limit else None}

    def history(self,family_id,limit=20,after=0):
        self.rec._page(limit,after)
        with self.rec.db() as db:
            self._family(db,family_id)
            rows=db.execute("SELECT * FROM workflow_lifecycle_log WHERE family_id=? AND generation>? ORDER BY generation LIMIT ?",
                            (family_id,after,limit+1)).fetchall()
        items=[self._dict(r,"payload") for r in rows[:limit]]
        return {"items":items,"next_cursor":items[-1]["generation"] if len(rows)>limit else None}

    def query(self,action,**args):
        require(action in ("register","activate","disable","rollback","inspect","list","history","link","route_status","select"),"Unknown lifecycle action")
        return getattr(self,action)(**args)


def lifecycle_tool_definitions():
    s={"type":"string"}; i={"type":"integer","minimum":0}; b={"type":"boolean"}
    page={"limit":{"type":"integer","minimum":1,"maximum":50},"after":i}
    family={"family_id":s};mut={**family,"expected_generation":i,"reason":s}
    specs={
        "register":({**mut,"workflow_id":s,"run_id":s,"parent_version":i},[*mut,"workflow_id","run_id"]),
        "activate":({**mut,"version":i},[*mut,"version"]),
        "disable":(mut,list(mut)),
        "rollback":({**mut,"version":i},[*mut,"version"]),
        "link":({**mut,"parent_version":i,"proposal_id":s,"qualification_id":s},[*mut,"parent_version","proposal_id","qualification_id"]),
        "route_status":({**mut,"route_id":s,"enabled":b},[*mut,"route_id","enabled"]),
        "inspect":({**family,**page,"parent_version":i},["family_id"]),
        "history":({**family,**page},["family_id"]),
        "list":(page,[]),
        "select":({**family,"run_id":s},["family_id","run_id"])}
    return [{"name":"vision_lifecycle_"+k,"description":("Select a qualified recovery route using fresh pixels; no execution." if k=="select" else "Workflow registry "+k),
             "inputSchema":{"type":"object","properties":p,"required":r,"additionalProperties":False}}
            for k,(p,r) in specs.items()]
