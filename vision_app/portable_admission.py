"""Atomic admission and pinned single-device portable task execution."""
from contextlib import contextmanager, ExitStack
import time

from vision_app.coordinator import Claim, ClaimError, task_run_id
from vision_app.definition_core import ExecutionContext
from vision_app.portable_service import new_receipt, interrupted
from vision_app.qualification import reject, fault

_RUN_FIELDS=("status","action_outcome","completed_steps","last_frame_id","last_confirmed_state",
             "observation_phase","reason","finished_at","steps","action_receipt")

def not_attempted(receipt):
    return {**receipt,"status":"not_attempted","finished_at":time.time(),
            "reason":fault("INTERRUPTED","Admission closed before execution")}

def task_from_run(task,run,*,live=False):
    view={**task,**{k:run[k] for k in _RUN_FIELDS}}
    if live:
        view["status"]="in_progress"
        view["finished_at"]=None
        view["reason"]=None
    return view


class PortableAdmission:
    def __init__(self,service):
        self.svc=service
        self.ledger=service.ledger
        self.families=service.families

    @contextmanager
    def prepare(self,family,expected,devices,task_ids):
        """Validate all requested devices and proof snapshots outside metadata; return CAS."""
        pin=self.families.active(family,expected)
        online={row["device_id"] for row in self.svc.rt.obs.android_devices()["devices"]}
        if any(device not in online for device in devices):
            reject("DEVICE_UNAVAILABLE","An explicitly requested Android device is unavailable")
        with ExitStack() as stack:
            resolved,record,source_recheck=stack.enter_context(self.svc.definitions.pinned(pin["portable_id"]))
            plans=[]
            checks=[]
            for device,tid in zip(devices,task_ids):
                slot,q,recheck=stack.enter_context(self.svc.slots.pinned_active(resolved,record,device))
                rid=task_run_id(tid,device)
                context=ExecutionContext.create(resolved,"portable_run",device,record["profile"],rid,
                                                qualification_id=q["qualification_id"])
                req={"family_id":family,"expected_generation":expected,"device":device,"task_id":tid}
                task=new_receipt("portable_task",tid,device,req,run_id=rid,**pin,
                                 qualification_id=q["qualification_id"],slot_generation=slot["generation"],
                                 context=context.to_dict())
                run=new_receipt("portable_run",rid,device,{"task_id":tid,"device":device},
                                context=context.to_dict())
                plans.append((context,task,run))
                checks.append(recheck)
            def recheck(db):
                self.families.recheck(db,pin)
                source_recheck()
                for check in checks:
                    check(db)
            yield pin,resolved,plans,recheck

    @staticmethod
    def claims(plan):
        context,task,run=plan
        return (Claim(task["id"],"portable_task",task["request"],task,device=task["device"]),
                Claim(run["id"],"portable_run",run["request"],run,device=run["device"],owner_id=task["id"]))

    def run_task_owned(self,resolved,plan,owner,*,nested_started=False):
        context,task,run=plan
        if not nested_started and not self.ledger.start_nested(owner,run["id"]):
            raise RuntimeError("Reserved portable run was not available")
        finished=self.svc._run_owned(resolved,context,run,owner)
        result=task_from_run(task,finished)
        self.ledger.record(owner,task["id"],result,terminal=True)
        return result

    def execute(self,family_id,expected_generation,device,task_id,return_image=False):
        req={"family_id":family_id,"expected_generation":expected_generation,"device":device,"task_id":task_id}
        duplicate=self.ledger.duplicate(task_id,"portable_task",req)
        if duplicate is not None:
            return {**self.task_inspect(task_id),"duplicate_request":True}
        with self.ledger.request_owner(task_id,timeout=2) as owner:
            if owner is None:
                duplicate=self.ledger.duplicate(task_id,"portable_task",req)
                if duplicate is not None:
                    return {**self.task_inspect(task_id),"duplicate_request":True}
                reject("DEVICE_BUSY","Task request is busy")
            duplicate=self.ledger.duplicate(task_id,"portable_task",req)
            if duplicate is not None:
                return {**self.task_inspect(task_id),"duplicate_request":True}
            with self.prepare(family_id,expected_generation,[device],[task_id]) as (_,resolved,plans,recheck):
                task,run=self.claims(plans[0])
                result=self.ledger.admit(owner,task,reservations=[run],recheck=recheck)
                if result is not None:
                    return result
            return self.run_task_owned(resolved,plans[0],owner)

    def _reconcile_task(self,owner,task):
        rid=task["run_id"]
        with self.ledger.transaction() as db:
            row=self.ledger._row(db,rid)
            if row is None:
                raise RuntimeError("Missing reserved run")
            if row["owner_id"]!=task["id"]:
                raise RuntimeError("Run owner mismatch")
            if row["state"]=="reserved":
                receipt=not_attempted(self.ledger._receipt(row))
                self.ledger._write(db,rid,"terminal",receipt)
                return interrupted(task_from_run(task,receipt))
        run=self.ledger.inspect(rid,lambda _,receipt:interrupted(receipt),owner=owner)
        return task_from_run(task,run)

    def _task_view(self,db,row):
        task=self.ledger._receipt(row)
        if row["state"]!="running":
            return task
        run=self.ledger._row(db,task["run_id"])
        if run is None or run["owner_id"]!=task["id"]:
            raise RuntimeError("Missing task run")
        return task_from_run(task,self.ledger._receipt(run),live=True)

    def task_inspect(self,task_id,return_image=False):
        with self.ledger.transaction() as db:
            row=self.ledger._row(db,task_id)
            if row is None or row["kind"]!="portable_task":
                reject("NOT_FOUND","Portable task not found")
        self.ledger.inspect(task_id,self._reconcile_task)
        with self.ledger.transaction() as db:
            return self._task_view(db,self.ledger._row(db,task_id))

    def run_inspect(self,run_id,return_image=False):
        with self.ledger.transaction() as db:
            row=self.ledger._row(db,run_id)
            if row is None or row["kind"] not in ("trial","portable_run"):
                reject("NOT_FOUND","Portable run not found")
            task_id=row["owner_id"] if row["kind"]=="portable_run" else None
        if task_id:
            self.task_inspect(task_id)
            return self.ledger.inspect(run_id)
        return self.svc.trial_inspect(run_id)

    def task_list(self,limit=20,after=0,device=None):
        with self.ledger.transaction() as db:
            rows=db.execute("SELECT rowid AS seq,* FROM request_claim WHERE kind='portable_task' AND rowid>? "+
                            ("AND device=? " if device is not None else "")+"ORDER BY rowid LIMIT ?",
                            (after,device,limit+1) if device is not None else (after,limit+1)).fetchall()
            items=[]
            for row in rows[:limit]:
                receipt=self._task_view(db,row)
                items.append({k:v for k,v in receipt.items() if k!="steps"})
            return {"items":items,"next_cursor":rows[limit-1]["seq"] if len(rows)>limit else None}
