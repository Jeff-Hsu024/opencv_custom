"""Atomic batch admission, bounded child execution and owner-based reconciliation."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

from vision_app.coordinator import Claim, child_task_id
from vision_app.portable_admission import not_attempted
from vision_app.portable_contract import normalize
from vision_app.qualification import reject

_STATUSES=("completed","needs_agent","busy","rejected","interrupted","not_attempted","in_progress")

def summarize_child(task):
    return {"device":task["device"],"task_id":task["id"],"run_id":task["run_id"],
            "qualification_id":task["qualification_id"],"slot_generation":task["slot_generation"],
            "status":task["status"],"action_outcome":task["action_outcome"],"reason":task["reason"]}

def aggregate(children,*,abandoned=False,live_parent=False):
    counts={status:0 for status in _STATUSES}
    for child in children:
        counts[child["status"]]+=1
    if live_parent or counts["in_progress"]:
        status="in_progress"
    elif counts["completed"]==len(children):
        status="completed"
    elif abandoned and (counts["not_attempted"] or counts["interrupted"]):
        status="interrupted"
    elif counts["completed"]:
        status="partial"
    else:
        status="needs_agent"
    return status,counts


class PortableBatches:
    def __init__(self,service):
        self.svc=service
        self.admission=service.admission
        self.ledger=service.ledger

    def _admit(self,owner,req):
        bid=req["batch_id"]
        devices=req["devices"]
        ids=[child_task_id(bid,device) for device in devices]
        with self.admission.prepare(req["family_id"],req["expected_generation"],devices,ids) as (pin,resolved,plans,recheck):
            children=[summarize_child(plan[1]) for plan in plans]
            status,counts=aggregate(children,live_parent=True)
            receipt={"batch_id":bid,"request":req,"status":status,"phase":"open",**pin,
                     "children":children,"counts":counts,"duplicate_request":False,
                     "created_at":time.time(),"finished_at":None}
            reservations=[claim for plan in plans for claim in self.admission.claims(plan)]
            pins={**pin,"ordered_children":[{k:c[k] for k in
                    ("device","task_id","run_id","qualification_id","slot_generation")} for c in children]}
            duplicate=self.ledger.admit(owner,Claim(bid,"batch",req,receipt),
                                         reservations=reservations,batch_pins=pins,recheck=recheck)
            return duplicate,resolved,plans

    def _child(self,bid,resolved,plan):
        tid=plan[1]["id"]
        with self.ledger.request_owner(tid,timeout=2) as owner:
            if owner is None or not self.ledger.start_reserved(owner,bid):
                return
            return self.admission.run_task_owned(resolved,plan,owner,nested_started=True)

    def _row(self,db,bid):
        row=self.ledger._row(db,bid)
        if row is None or row["kind"]!="batch":
            reject("NOT_FOUND","Portable batch not found")
        return row

    def _view(self,db,row,*,final=False,abandoned=False):
        receipt=self.ledger._receipt(row)
        if row["state"]=="terminal":
            return receipt
        phase=db.execute("SELECT phase FROM batch_admission WHERE batch_id=?",(receipt["batch_id"],)).fetchone()["phase"]
        children=[]
        for child in receipt["children"]:
            task=self.ledger._row(db,child["task_id"])
            if task is None or task["parent_id"]!=receipt["batch_id"]:
                raise RuntimeError("Batch child claim missing")
            children.append(summarize_child(self.admission._task_view(db,task)))
        status,counts=aggregate(children,abandoned=abandoned,live_parent=not final)
        if status!="in_progress":
            phase="terminal"
        elif final:
            phase="reconciling"
        return {**receipt,"status":status,"phase":phase,"children":children,"counts":counts,
                "finished_at":time.time() if status!="in_progress" else None}

    def _reconcile_children(self,receipt):
        for child in receipt["children"]:
            self.admission.task_inspect(child["task_id"])

    def _close_and_project(self,owner,receipt,*,abandoned):
        self.ledger.close_admission(owner,not_attempted)
        self._reconcile_children(receipt)
        with self.ledger.transaction() as db:
            row=self._row(db,receipt["batch_id"])
            view=self._view(db,row,final=True,abandoned=abandoned)
            if view["status"]=="in_progress":
                db.execute("UPDATE batch_admission SET phase='reconciling' WHERE batch_id=?",(receipt["batch_id"],))
                # This owner is proven by the ledger OS lock. Recovery may
                # hold a fresh owner token; do not use the dead token.
                self.ledger._require_owner(owner,receipt["batch_id"],"parent")
                self.ledger._write(db,receipt["batch_id"],"running",view)
                return None
            return view

    def batch_inspect(self,batch_id):
        with self.ledger.transaction() as db:
            self._row(db,batch_id)
        self.ledger.inspect(batch_id,lambda owner,receipt:self._close_and_project(owner,receipt,abandoned=True))
        with self.ledger.transaction() as db:
            return self._view(db,self._row(db,batch_id))

    def batch_execute(self,batch_id,family_id,expected_generation,devices,max_concurrency=2):
        req=normalize("portable_batch_execute",{"batch_id":batch_id,"family_id":family_id,
                      "expected_generation":expected_generation,"devices":devices,"max_concurrency":max_concurrency})
        duplicate=self.ledger.duplicate(batch_id,"batch",req)
        if duplicate is not None:
            return {**self.batch_inspect(batch_id),"duplicate_request":True}
        with self.ledger.request_owner(batch_id,parent=True,timeout=2) as owner:
            if owner is None:
                duplicate=self.ledger.duplicate(batch_id,"batch",req)
                if duplicate is not None:
                    return {**self.batch_inspect(batch_id),"duplicate_request":True}
                reject("DEVICE_BUSY","Batch request is busy")
            duplicate=self.ledger.duplicate(batch_id,"batch",req)
            if duplicate is not None:
                return {**self.batch_inspect(batch_id),"duplicate_request":True}
            duplicate,resolved,plans=self._admit(owner,req)
            if duplicate is not None:
                return duplicate
            # Each child takes its own OS request and device owners. One
            # protected immutable definition is shared, with no mutable family
            # lookup inside any child interpreter.
            with ThreadPoolExecutor(max_workers=req["max_concurrency"]) as pool:
                futures=[pool.submit(self._child,batch_id,resolved,plan) for plan in plans]
                for future in as_completed(futures):
                    try:
                        future.result()
                    except BaseException:
                        # A finished child can have lost its receipt. The
                        # owner-based reconciliation below is authoritative;
                        # never replay or cancel other children.
                        pass
            receipt=self.ledger.inspect(batch_id)
            view=self._close_and_project(owner,receipt,abandoned=False)
            if view is None:
                with self.ledger.transaction() as db:
                    return self._view(db,self._row(db,batch_id))
            self.ledger.record(owner,batch_id,view,terminal=True)
            return view

    def batch_list(self,limit=20,after=0):
        with self.ledger.transaction() as db:
            rows=db.execute("SELECT rowid AS seq,* FROM request_claim WHERE kind='batch' AND rowid>? ORDER BY rowid LIMIT ?",
                            (after,limit+1)).fetchall()
            items=[]
            for row in rows[:limit]:
                view=self._view(db,row)
                children=view.pop("children")
                view["child_ids"]=[{k:c[k] for k in ("device","task_id","run_id")} for c in children]
                items.append(view)
            return {"items":items,"next_cursor":rows[limit-1]["seq"] if len(rows)>limit else None}
