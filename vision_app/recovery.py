"""Evidence-bound recovery handoff and child workflow lineage. Never executes actions."""
from __future__ import annotations

import json
import time
from contextlib import ExitStack, nullcontext

from vision_app.metadata import metadata_transaction
from vision_app.recorder import Recorder
from vision_app.runtime import WorkflowRuntime, check
from vision_app.workflow import WorkflowBuilder, canonical, digest, require, fields, label, source_frame, decode

KINDS = ("recovery_route", "replacement")
OUTCOMES = ("not_attempted", "effect_observed", "effect_not_observed", "unknown")


def seal(obj):
    return digest(canonical(obj))


class RecoveryService:
    def __init__(self, store):
        self.store = store
        self.rec = Recorder(store)
        self.builder = WorkflowBuilder(store)
        self.runtime = WorkflowRuntime(store)
        with metadata_transaction(self.store), self.rec.db() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS recovery_cases(
                case_id TEXT PRIMARY KEY, run_id TEXT UNIQUE NOT NULL,
                session_id TEXT UNIQUE NOT NULL REFERENCES sessions,
                created_at REAL NOT NULL, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS recovery_proposals(
                proposal_id TEXT PRIMARY KEY, case_id TEXT NOT NULL REFERENCES recovery_cases,
                created_at REAL NOT NULL, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS recovery_qualifications(
                qualification_id TEXT PRIMARY KEY, proposal_id TEXT NOT NULL REFERENCES recovery_proposals,
                run_id TEXT NOT NULL, created_at REAL NOT NULL, payload TEXT NOT NULL,
                UNIQUE(proposal_id,run_id));
            """)

    @staticmethod
    def _row(db, table, key, value):
        # Table/column identifiers are internal constants, never supplied by a caller.
        row = db.execute(f"SELECT * FROM {table} WHERE {key}=?", (value,)).fetchone()
        require(row is not None, "Recovery record not found")
        return {**dict(row), "payload":json.loads(row["payload"])}

    def _case(self, case_id):
        with self.rec.db() as db:
            return self._row(db,"recovery_cases","case_id",case_id)

    def _proposal(self, proposal_id):
        with self.rec.db() as db:
            return self._row(db,"recovery_proposals","proposal_id",proposal_id)

    def _run(self, case):
        run = self.runtime._load("runs",case["run_id"])
        p=case["payload"]
        require(seal(run)==p["failed_run_sha256"],"Failed run journal changed")
        require(case["case_id"]=="rc_"+seal({"run_id":case["run_id"]})
                and run["run_id"]==case["run_id"] and run["workflow_id"]==p["parent_workflow_id"]
                and run["binding_id"]==p["binding_id"] and run["device"]==p["device"]
                and run["profile"]==p["profile"] and run["action_outcome"]==p["action_outcome"],
                "Recovery case lineage mismatch")
        require(self.rec.status(case["session_id"])["device_id"]==run["device"],"Recovery session device mismatch")
        return run

    def _frame(self, fid, device):
        rec=self.store.get_frame(fid,device_id=device)
        require(rec.protected and rec.parent_id is None and rec.width==rec.source_width
                and rec.height==rec.source_height,"Need protected original full-device frame")
        data=self.store.resolve_image_path(rec.image_path).read_bytes()
        image=self.store.load_image(fid,device_id=device)
        require(image.shape[:2]==(rec.height,rec.width),"Frame dimensions differ")
        return rec,image,digest(data)

    def open(self, run_id):
        """Atomically link one new exploration session to a failed or interrupted run."""
        observed=self.runtime._observe_run(run_id)
        check(observed["status"]!="running","DEVICE_BUSY","Runtime request is still active")
        run=self.runtime._load("runs",run_id)
        require(run["status"] in ("needs_agent","interrupted"),"Completed run is not recoverable")
        binding=self.runtime._binding(run["binding_id"])
        require(binding["workflow_id"]==run["workflow_id"] and binding["device"]==run["device"]
                and binding["profile"]==run["profile"],"Runtime binding mismatch")
        case_id="rc_"+seal({"run_id":run_id})
        with self.rec.db() as db:
            existing=db.execute("SELECT 1 FROM recovery_cases WHERE case_id=?", (case_id,)).fetchone()
        if existing:
            return self.inspect(case_id)
        parent=self.builder.inspect(run["workflow_id"])["definition"]
        require(parent["source"]["device_id"]==run["device"],"Parent source device mismatch")
        verified=[{"step_id":s["step_id"],"from":s["from"],"to":s["to"],
                   "post_frame_id":s["post_frame_id"]} for s in run["steps"] if s["status"]=="verified"]
        last_frame=run.get("last_frame_id")
        evidence=None
        if last_frame:
            f,_,sha=self._frame(last_frame,run["device"])
            evidence={"frame_id":last_frame,"sha256":sha,"timestamp":f.timestamp}
        payload={"failed_run_sha256":seal(run),"parent_workflow_id":run["workflow_id"],
                 "binding_id":run["binding_id"],"device":run["device"],"profile":run["profile"],
                 "goal":parent["goal"],"reason":run["reason"],"current_step":run["current_step"],
                 "action_outcome":run["action_outcome"],"last_confirmed_state":run["last_confirmed_state"],
                 "last_frame":evidence,"verified_prefix":verified,
                 "known_states":[{"id":s["id"],"label":s["label"]} for s in parent["states"]],
                 "remaining_steps":[{"id":s["id"],"from":s["from"],"to":s["to"]}
                                    for s in parent["steps"][run["completed_steps"]:]],
                 "initial_state":parent["initial_state"],"final_state":parent["final_state"]}
        with metadata_transaction(self.store), self.rec.db() as db:
            existing=db.execute("SELECT 1 FROM recovery_cases WHERE case_id=?", (case_id,)).fetchone()
            if not existing:
                session=self.rec._create_session(db,"Recovery "+run_id,
                    "Observe current state, reconcile original action outcome, and record a safe recovery path.",run["device"])
                db.execute("INSERT INTO recovery_cases VALUES (?,?,?,?,?)",
                           (case_id,run_id,session["session_id"],time.time(),canonical(payload).decode()))
        return self.inspect(case_id)

    def inspect(self, case_id, limit=10, after=0):
        self.rec._page(limit,after)
        case=self._case(case_id)
        self._run(case)
        with self.rec.db() as db:
            rows=db.execute("""SELECT rowid AS cursor,* FROM recovery_proposals WHERE case_id=? AND rowid>?
                             ORDER BY rowid LIMIT ?""",(case_id,after,limit+1)).fetchall()
            items=[]
            for r in rows[:limit]:
                p=json.loads(r["payload"])
                quals=db.execute("SELECT count(*) FROM recovery_qualifications WHERE proposal_id=?",(r["proposal_id"],)).fetchone()[0]
                items.append({"proposal_id":r["proposal_id"],"child_workflow_id":p["child_workflow_id"],
                              "kind":p["kind"],"destination_state":p["destination_state"],
                              "live_qualification_count":quals,"cursor":r["cursor"]})
        return {"case_id":case_id,"run_id":case["run_id"],"session_id":case["session_id"],
                "created_at":case["created_at"],"handoff":case["payload"],
                "session":self.rec.summary(case["session_id"]),
                "proposals":{"items":items,"next_cursor":items[-1]["cursor"] if len(rows)>limit else None},
                "next_action":"Check actual app/profile; take a fresh bound snapshot and annotate observed state before any recovery action.",
                "policy":"Original action outcome is not rewritten. Do not retry uncertain actions or resume automatically."}

    def _parent(self, case):
        run=self._run(case)
        p=case["payload"]
        if p["last_frame"]:
            _,_,sha=self._frame(p["last_frame"]["frame_id"],p["device"])
            require(sha==p["last_frame"]["sha256"],"Failed run frame changed")
        d,t=self.runtime._definition(p["parent_workflow_id"],p["device"],p["profile"])
        return run,d,t

    def _classify(self, fid, case, d, templates):
        f,image,sha=self._frame(fid,case["payload"]["device"])
        g=d["geometry"]
        require((f.width,f.height)==(g["width"],g["height"]),"Recovery geometry differs from parent")
        return f,self.runtime._classify(image,d,templates),sha

    def propose(self, case_id, kind, destination_state, reconciliation, plan):
        """Compile an explicit child proposal without changing parent, failed run or device."""
        from vision_app.validation_context import evidence_snapshot
        require(kind in KINDS,"Invalid proposal kind")
        fields(reconciliation,("anchor_event_id","annotation_id","outcome","note"),"reconciliation")
        require(reconciliation["outcome"] in OUTCOMES,"Invalid reconciliation outcome")
        label(reconciliation["note"],"reconciliation note")
        with ExitStack() as pins:
            case=self._case(case_id)
            parent_snapshot = pins.enter_context(evidence_snapshot(
                self.builder, None, None, wid=case["payload"]["parent_workflow_id"]))
            parent_seals = parent_snapshot.seals()
            run,parent,templates=self._parent(case)
            sid=case["session_id"]
            snapshot = pins.enter_context(evidence_snapshot(self.builder, sid, plan))
            seals = snapshot.seals()
            anchor_snapshot = pins.enter_context(evidence_snapshot(
                self.builder, sid, {}, extra_events=(reconciliation["anchor_event_id"],)))
            anchor_seals = anchor_snapshot.seals()
            require(self.rec.status(sid)["status"]=="stopped","Stop recovery session before proposal")
            events,anns=self.builder._events(sid)
            anchor=events.get(reconciliation["anchor_event_id"])
            require(anchor is not None and anchor["sequence"]==1 and anchor["operation"]=="snapshot"
                    and anchor["status"]=="success","First recovery event must be successful fresh snapshot")
            fid=source_frame(anchor)
            require(fid in anchor["evidence"]["frames"],"Anchor lacks actual frame")
            f,observed,anchor_sha=self._classify(fid,case,parent,templates)
            require(anchor["timestamp"]>=case["created_at"] and f.timestamp>=case["created_at"]
                    and f.timestamp>=run["finished_at"],"Recovery anchor predates failure")
            require(not observed["ambiguous"],"Ambiguous anchor state")
            ann=anns.get(reconciliation["annotation_id"])
            require(ann is not None and ann["event_id"]==anchor["event_id"] and ann["timestamp"]>=anchor["timestamp"]
                    and ann["annotation"].get("verification")=="PASS" and bool(ann["annotation"].get("state"))
                    and bool(ann["annotation"].get("observation")),"Explicit observed-state PASS annotation required")
            require(not any(a["event_id"]==anchor["event_id"] and a["timestamp"]>ann["timestamp"]
                            and a["annotation"].get("verification") in ("FAIL","UNKNOWN") for a in anns.values()),
                    "Later annotation disputes anchor")
            action_events=[e for e in events.values() if e["operation"] in ("click","swipe","type","key")]
            require(all(ann["timestamp"]<=e["timestamp"] for e in action_events),"Anchor must be annotated before recovery actions")
            original=run["action_outcome"]
            require((original=="not_attempted" and reconciliation["outcome"]=="not_attempted") or
                    (original!="not_attempted" and reconciliation["outcome"]!="not_attempted"),
                    "Reconciliation contradicts original action receipt")
            require(isinstance(plan,dict) and not plan.get("excluded_actions"),"Recovery plan cannot exclude actions")
            require(isinstance(plan.get("steps"),list) and plan["steps"],"Recovery plan requires steps")
            definition,blobs=self.builder._compile(sid,plan)
            first_event=events[plan["steps"][0]["pre_event_id"]]
            require(first_event["sequence"]>=anchor["sequence"] and
                    all(e["sequence"]>=first_event["sequence"] for e in action_events),
                    "No action may precede the fresh execution frame")
            first_fid=source_frame(first_event)
            _,first_state,_=self._classify(first_fid,case,parent,templates)
            require(not first_state["ambiguous"] and first_state["state"]==observed["state"],
                    "Parent classification changed between anchor and execution frame")
            child_templates={sha:decode(data) for sha,data in blobs.items()}
            anchor_child=self.runtime._classify(self.store.load_image(fid),definition,child_templates)
            require(not anchor_child["ambiguous"] and anchor_child["state"]==definition["initial_state"],
                    "Fresh execution state does not agree with observed anchor")
            final_event=events[plan["steps"][-1]["post_event_id"]]
            final_fid=source_frame(final_event)
            _,end,end_sha=self._classify(final_fid,case,parent,templates)
            require(destination_state in {s["id"] for s in parent["states"]}
                    and end["state"]==destination_state and not end["ambiguous"],
                    "Recovery endpoint must uniquely match declared parent state")
            if kind=="replacement":
                require(observed["state"]==parent["initial_state"] and destination_state==parent["final_state"],
                        "Full replacement must preserve parent initial and final state")
            child_id="wf_"+seal({"definition":definition,"plan":plan})
            payload={"case_id":case_id,"failed_run_id":run["run_id"],
                     "failed_run_sha256":case["payload"]["failed_run_sha256"],"parent_workflow_id":parent["workflow_id"],
                     "child_workflow_id":child_id,"recovery_session_id":sid,"kind":kind,
                     "destination_state":destination_state,"profile":run["profile"],"device":run["device"],
                     "reconciliation":reconciliation,"original_action_outcome":original,
                     "anchor":{"event_id":anchor["event_id"],"event_sha256":seal(anchor),"frame_id":fid,
                               "frame_sha256":anchor_sha,"annotation_sha256":seal(ann),"parent_classification":observed,
                               "execution_pre_event_id":first_event["event_id"],"child_classification":anchor_child},
                     "endpoint":{"event_id":final_event["event_id"],"frame_id":final_fid,
                                 "frame_sha256":end_sha,"parent_classification":end},
                     "status":"offline_pass","automatic_resume":False,"automatic_promotion":False}
            pid="rp_"+seal(payload)
            def publish_proposal():
                with self.rec.db() as db:
                    db.execute("INSERT OR IGNORE INTO recovery_proposals VALUES (?,?,?,?)",
                               (pid,case_id,time.time(),canonical(payload).decode()))
                    return self._row(db,"recovery_proposals","proposal_id",pid)

            return self.builder._publish_locked(
                definition, blobs, plan, snapshot, seals, publish_proposal,
                additional=((anchor_snapshot, anchor_seals), (parent_snapshot, parent_seals)),
            )

    def proposal(self, proposal_id, limit=10, after=0):
        self.rec._page(limit,after)
        p=self._proposal(proposal_id)
        require("rp_"+seal(p["payload"])==proposal_id,"Proposal integrity mismatch")
        with self.rec.db() as db:
            rows=db.execute("""SELECT rowid AS cursor,* FROM recovery_qualifications WHERE proposal_id=? AND rowid>?
                             ORDER BY rowid LIMIT ?""",(proposal_id,after,limit+1)).fetchall()
        items=[{**dict(r),"payload":json.loads(r["payload"])} for r in rows[:limit]]
        return {**p,"qualifications":{"items":items,"next_cursor":items[-1]["cursor"] if len(rows)>limit else None}}

    def verify(self, proposal_id, run_id):
        """Link a later completed child run; never run or promote anything."""
        return self._verify_locked(proposal_id, run_id)

    def _verify_locked(self, proposal_id, run_id, *, persist=True):
        p=self._proposal(proposal_id)
        payload=p["payload"]
        require("rp_"+seal(payload)==proposal_id,"Proposal integrity mismatch")
        case=self._case(p["case_id"])
        require(payload["case_id"]==case["case_id"] and payload["recovery_session_id"]==case["session_id"]
                and payload["failed_run_id"]==case["run_id"]
                and payload["failed_run_sha256"]==case["payload"]["failed_run_sha256"]
                and payload["parent_workflow_id"]==case["payload"]["parent_workflow_id"],
                "Proposal lineage mismatch")
        _,parent,templates=self._parent(case)
        self.builder._validate(payload["child_workflow_id"])
        # Anchor evidence and annotation must still agree, including later semantic disputes.
        events,anns=self.builder._events(case["session_id"])
        anchor=payload["anchor"]
        require(seal(events[anchor["event_id"]])==anchor["event_sha256"],"Anchor event changed")
        aid=payload["reconciliation"]["annotation_id"]
        ann=anns[aid]
        require(seal(ann)==anchor["annotation_sha256"],"Anchor annotation changed")
        require(not any(a["event_id"]==anchor["event_id"] and a["timestamp"]>ann["timestamp"]
                        and a["annotation"].get("verification") in ("FAIL","UNKNOWN") for a in anns.values()),
                "Later annotation disputes anchor")
        _,_,sha=self._frame(anchor["frame_id"],payload["device"])
        require(sha==anchor["frame_sha256"],"Anchor frame changed")
        run=self.runtime._load("runs",run_id)
        require(run["status"]=="completed" and run["workflow_id"]==payload["child_workflow_id"]
                and run["device"]==payload["device"] and run["profile"]==payload["profile"]
                and run["started_at"]>=p["created_at"],"Need later completed child run on original profile")
        binding=self.runtime._binding(run["binding_id"])
        require(binding["workflow_id"]==run["workflow_id"] and binding["profile"]==run["profile"]
                and binding["device"]==run["device"],"Child binding mismatch")
        child=self.builder.inspect(run["workflow_id"])["definition"]
        require(run["completed_steps"]==len(child["steps"])==len(run["steps"])
                and run["last_confirmed_state"]==child["final_state"]
                and all(s["status"]=="verified" for s in run["steps"]),"Incomplete child run")
        first=run["steps"][0]["pre_frame_id"]
        _,start,start_sha=self._classify(first,case,parent,templates)
        require(not start["ambiguous"] and start["state"]==anchor["parent_classification"]["state"],
                "Live recovery starting state differs from anchor")
        _,end,end_sha=self._classify(run["last_frame_id"],case,parent,templates)
        require(end["state"]==payload["destination_state"] and not end["ambiguous"],
                "Live recovery endpoint differs from parent state")
        qualification={"proposal_id":proposal_id,"run_id":run_id,"run_sha256":seal(run),
                       "child_workflow_id":run["workflow_id"],"parent_workflow_id":parent["workflow_id"],
                       "first_frame_id":first,"first_frame_sha256":start_sha,
                       "final_frame_id":run["last_frame_id"],"final_frame_sha256":end_sha,
                       "parent_state":end["state"],"status":"live_pass",
                       "automatic_resume":False,"automatic_promotion":False}
        qid="rq_"+seal(qualification)
        with (metadata_transaction(self.store) if persist else nullcontext()), self.rec.db() as db:
            existing=db.execute("SELECT qualification_id FROM recovery_qualifications WHERE proposal_id=? AND run_id=?",
                                (proposal_id,run_id)).fetchone()
            require(not existing or existing["qualification_id"]==qid,"Existing live qualification changed")
            if persist:
                db.execute("INSERT OR IGNORE INTO recovery_qualifications VALUES (?,?,?,?,?)",
                           (qid,proposal_id,run_id,time.time(),canonical(qualification).decode()))
            else:
                require(existing is not None,"Live qualification is not registered")
            return self._row(db,"recovery_qualifications","qualification_id",qid)


    def list(self, limit=20, after=0):
        self.rec._page(limit,after)
        with self.rec.db() as db:
            rows=db.execute("SELECT rowid AS cursor,* FROM recovery_cases WHERE rowid>? ORDER BY rowid LIMIT ?",
                            (after,limit+1)).fetchall()
        items=[{"case_id":r["case_id"],"run_id":r["run_id"],"session_id":r["session_id"],
                "created_at":r["created_at"],"cursor":r["cursor"]} for r in rows[:limit]]
        return {"items":items,"next_cursor":items[-1]["cursor"] if len(rows)>limit else None}

    def query(self, action, **args):
        require(action in ("open","inspect","propose","proposal","verify","list"),"Unknown recovery action")
        return getattr(self,action)(**args)


def recovery_tool_definitions():
    string={"type":"string"}
    page={"limit":{"type":"integer","minimum":1,"maximum":50},"after":{"type":"integer","minimum":0}}
    specs={
        "open":({"run_id":string},["run_id"],"Open an idempotent recovery case and linked exploration session from failed run."),
        "inspect":({"case_id":string,**page},["case_id"],"Bounded failure handoff and proposal list."),
        "propose":({"case_id":string,"kind":{"type":"string","enum":list(KINDS)},"destination_state":string,
                    "reconciliation":{"type":"object","properties":{"anchor_event_id":string,"annotation_id":string,
                    "outcome":{"type":"string","enum":list(OUTCOMES)},"note":string},
                    "required":["anchor_event_id","annotation_id","outcome","note"],"additionalProperties":False},
                    "plan":{"type":"object"}},["case_id","kind","destination_state","reconciliation","plan"],
                   "Compile explicit recovery route or full replacement; offline only, no auto retry or promotion."),
        "proposal":({"proposal_id":string,**page},["proposal_id"],"Inspect immutable lineage and live qualifications."),
        "verify":({"proposal_id":string,"run_id":string},["proposal_id","run_id"],"Link later completed child runtime result."),
        "list":(page,[],"List recovery cases with cursor pagination.")}
    return [{"name":"vision_recovery_"+name,"description":desc,
             "inputSchema":{"type":"object","properties":props,"required":required,"additionalProperties":False}}
            for name,(props,required,desc) in specs.items()]
