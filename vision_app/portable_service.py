"""Portable preflight, trial and qualification entrypoints shared by CLI/MCP."""
from contextlib import contextmanager
import json
import sqlite3
import time

from vision_app.coordinator import Claim, ClaimError, canonical_json
from vision_app.definition_core import ExecutionContext
from vision_app.discovery import DiscoveryService
from vision_app.metadata import metadata_transaction
from vision_app.observation import OperationError
from vision_app.portable import PortableDefinitions, _hash
from vision_app.portable_contract import CATALOG, normalize
from vision_app.qualification import QualificationSlots, fault, reject
from vision_app.runtime import WorkflowRuntime, RuntimeFault, profile_shape
from vision_app.store import StoreError, protect_new_frames
from vision_app.validation_context import EvidenceChanged
from vision_app.workflow import WorkflowError

_DEFINITION_OPS=("portable_publish","portable_inspect","portable_list")
_DEVICE_OPS=("portable_preflight","portable_preflight_inspect","portable_trial","portable_trial_inspect")
_QUALIFICATION_OPS={
    "portable_qualify_commit":"commit","portable_qualification_revoke":"revoke",
    "portable_qualification_inspect":"inspect","portable_qualification_list":"list",
    "portable_qualification_record":"record",
}
_FAMILY_OPS={
    "portable_family_publish":"publish","portable_family_activate":"activate",
    "portable_family_inspect":"inspect","portable_family_list":"list",
}
_ADMISSION_OPS=("portable_execute","portable_task_inspect","portable_run_inspect","portable_task_list")
_BATCH_OPS=("portable_batch_execute","portable_batch_inspect","portable_batch_list")
SCHEMAS={op:CATALOG[op] for op in (*_DEFINITION_OPS,*_DEVICE_OPS,*_QUALIFICATION_OPS,*_FAMILY_OPS,*_ADMISSION_OPS,*_BATCH_OPS)}
_RETRYABLE={"DEVICE_BUSY","DEVICE_UNAVAILABLE","DISCOVERY_FAILED","CAPTURE_TIMEOUT"}
_CODES={"INVALID_ARGUMENT","INVALID_DEVICE","DEVICE_UNAVAILABLE","DISCOVERY_FAILED","NOT_FOUND",
        "SCOPE_MISMATCH","DEVICE_BUSY","STALE_REF_EPOCH","REF_UNVERSIONED","FRAME_STALE","PROFILE_MISMATCH",
        "GEOMETRY_MISMATCH","INITIAL_STATE_MISMATCH","TARGET_NOT_FOUND","TARGET_AMBIGUOUS",
        "PRECONDITION_FAILED","EVIDENCE_CHANGED","PROOF_INVALID","QUALIFICATION_REQUIRED","QUALIFICATION_INACTIVE",
        "STALE_GENERATION","FAMILY_INACTIVE","REQUEST_ID_CONFLICT","ID_RESERVED","STORE_ERROR","INTERNAL_ERROR",
        "CAPTURE_TIMEOUT","INTERRUPTED","ACTION_UNCERTAIN"}

def error_reason(exc,*,admitted=False,unknown=False):
    if isinstance(exc,EvidenceChanged):
        return fault("EVIDENCE_CHANGED","Source evidence changed")
    if isinstance(exc,WorkflowError):
        return fault("PROOF_INVALID","Definition or proof invalid")
    if isinstance(exc,(StoreError,sqlite3.Error,OSError)):
        return fault("STORE_ERROR","Evidence store unavailable")
    if isinstance(exc,(OperationError,RuntimeFault,ClaimError)):
        code=exc.code
        details=getattr(exc,"details",{})
        if unknown:
            return fault("ACTION_UNCERTAIN","Input outcome is uncertain")
        if code=="TARGET_NOT_UNIQUE":
            code="TARGET_NOT_FOUND" if details.get("match_count")==0 else "TARGET_AMBIGUOUS"
        elif code=="APP_MISMATCH":
            code="PROFILE_MISMATCH"
        elif code in ("PROFILE_PROBE_FAILED","PROFILE_UNKNOWN"):
            code="CAPTURE_TIMEOUT" if details.get("timed_out") else "DEVICE_UNAVAILABLE"
        elif code in ("POST_STATE_AMBIGUOUS","UNEXPECTED_STATE","POSTCONDITION_TIMEOUT"):
            code="PRECONDITION_FAILED"
        if code not in _CODES:
            code="INTERNAL_ERROR"
        return fault(code,str(exc) if code!="INTERNAL_ERROR" else "Internal portable operation error",
                     details if code!="INTERNAL_ERROR" else {},not admitted and code in _RETRYABLE)
    return fault("ACTION_UNCERTAIN","Input outcome is uncertain") if unknown else fault("INTERNAL_ERROR","Internal portable operation error")

def new_receipt(kind,identifier,device,request,**extra):
    return {"kind":kind,"id":identifier,"device":device,"status":"in_progress",
            "request":{k:v for k,v in request.items() if k!="return_image"},
            "action_outcome":"not_attempted","completed_steps":0,"last_frame_id":None,
            "last_confirmed_state":None,"observation_phase":"none","reason":None,
            "created_at":time.time(),"finished_at":None,"duplicate_request":False,
            "steps":[],"action_receipt":None,**extra}

def interrupted(receipt):
    return {**receipt,"status":"interrupted","finished_at":time.time(),
            "reason":fault("INTERRUPTED","Previous owner ended without a terminal receipt; do not replay")}

class PortableService:
    def __init__(self,store,*,runtime=None,observation=None,actions=None):
        self.store=store
        self.rt=runtime or WorkflowRuntime(store,observation=observation,actions=actions)
        self.definitions=PortableDefinitions(store,runtime=self.rt)
        self.ledger=self.rt.epochs
        self.slots=QualificationSlots(self.definitions)
        self.discovery=DiscoveryService(self.rt.obs)
        from vision_app.portable_family import PortableFamilies
        from vision_app.portable_admission import PortableAdmission
        self.families=PortableFamilies(self.definitions)
        self.admission=PortableAdmission(self)
        from vision_app.portable_batch import PortableBatches
        self.batches=PortableBatches(self)

    @staticmethod
    def _preflight_table(db):
        db.execute("CREATE TABLE IF NOT EXISTS portable_preflight (preflight_id TEXT PRIMARY KEY, immutable_json TEXT NOT NULL)")

    def preflight_inspect(self,preflight_id,return_image=False):
        with self.ledger.transaction() as db:
            self._preflight_table(db)
            row=db.execute("SELECT immutable_json FROM portable_preflight WHERE preflight_id=?",(preflight_id,)).fetchone()
        if row is None:
            reject("NOT_FOUND","Preflight receipt not found")
        receipt=json.loads(row["immutable_json"])
        require_id="preflight_"+_hash({k:v for k,v in receipt.items() if k not in ("preflight_id","created_at")})
        if require_id!=preflight_id or receipt["preflight_id"]!=preflight_id:
            reject("PROOF_INVALID","Preflight receipt identity changed")
        return receipt

    def _save_preflight(self,receipt):
        pid="preflight_"+_hash(receipt)
        receipt={**receipt,"preflight_id":pid,"created_at":time.time()}
        with self.ledger.transaction() as db:
            self._preflight_table(db)
            db.execute("INSERT OR IGNORE INTO portable_preflight VALUES (?,?)",(pid,canonical_json(receipt)))
        return self.preflight_inspect(pid)

    def preflight(self,portable_id,device,return_image=False):
        self.definitions.inspect(portable_id)
        receipt={"portable_id":portable_id,"device":device,"status":"fail","profile":None,
                 "geometry":None,"frame_id":None,"epoch":None,"reason":None}
        try:
            with self.definitions.pinned(portable_id) as (resolved,record,recheck):
                self.discovery.require_online(device)
                with self.ledger.device_owner(device) as owner:
                    if owner is None:
                        reject("DEVICE_BUSY","Device is busy")
                    observed_slot=self.slots.observe(portable_id,device)
                    try:
                        observed=self.rt.probe(device,record["profile"]["package"])
                        try:
                            profile_shape(observed)
                        except WorkflowError as exc:
                            raise RuntimeFault("PROFILE_UNKNOWN","Cannot establish Android profile") from exc
                        receipt["profile"]=observed
                        if observed!=record["profile"]:
                            raise RuntimeFault("PROFILE_MISMATCH","Android profile differs",
                                               {"expected":record["profile"],"observed":observed})
                        token=protect_new_frames.set(True)
                        try:
                            frame=self.rt.obs.snapshot(device,device_owner=owner)["frame"]
                        finally:
                            protect_new_frames.reset(token)
                        fid=frame["frame_id"]
                        receipt["frame_id"]=fid
                        receipt["epoch"]=self.ledger.frame_epoch(fid,device)
                        geometry={"width":frame["width"],"height":frame["height"],
                                  "rotation":observed["rotation"] if frame["rotation"] is None else frame["rotation"]}
                        receipt["geometry"]=geometry
                        # Fail closed on the captured evidence before another
                        # profile probe can obscure a confirmed mismatch.
                        if frame["device_id"]!=device or geometry!=record["geometry"]:
                            raise RuntimeFault("GEOMETRY_MISMATCH","Live geometry differs",
                                               {"expected":record["geometry"],"observed":geometry,
                                                "frame_id":fid})
                        latest=self.rt.probe(device,record["profile"]["package"])
                        try:
                            profile_shape(latest)
                        except WorkflowError as exc:
                            raise RuntimeFault("PROFILE_UNKNOWN","Cannot establish Android profile") from exc
                        if latest!=record["profile"]:
                            raise RuntimeFault("PROFILE_MISMATCH","Android profile differs",{"expected":record["profile"],"observed":latest})
                        d,templates=resolved.definition,resolved.templates()
                        image=self.store.load_image(fid,device_id=device)
                        state=self.rt._classify(image,d,templates)
                        if state["ambiguous"] or state["state"]!=d["initial_state"]:
                            reject("INITIAL_STATE_MISMATCH","Initial state not uniquely recognized")
                        self.rt._target(image,d["steps"][0],templates)
                        with metadata_transaction(self.store):
                            recheck()
                        receipt["status"]="pass"
                    except Exception as exc:
                        # A malformed/unknown probe is not evidence of drift.
                        reason=error_reason(exc)
                        self.slots.invalidate(observed_slot,reason)
                        receipt["reason"]=reason
        except Exception as exc:
            receipt["reason"]=error_reason(exc)
        return self._save_preflight(receipt)

    @contextmanager
    def live_guard(self,pid,device):
        observed_slot=self.slots.observe(pid,device)
        try:
            yield
        except Exception as exc:
            self.slots.invalidate(observed_slot,error_reason(exc,admitted=True))
            raise

    def _inspect_run(self,run_id,kind=None):
        with self.ledger.transaction() as db:
            row=self.ledger._row(db,run_id)
            if row is None or (kind is not None and row["kind"]!=kind) or row["kind"] not in ("trial","portable_run"):
                reject("NOT_FOUND","Portable run receipt not found")
        return self.ledger.inspect(run_id,lambda owner,receipt:interrupted(receipt))

    def trial_inspect(self,run_id,return_image=False):
        return self._inspect_run(run_id,"trial")

    def _run_owned(self,resolved,context,receipt,request_owner):
        """Execute a previously admitted run; never consult active family during steps."""
        rid=context.admission_id
        device=context.device
        def persist(run):
            self.ledger.record(request_owner,rid,run)
        def observe(fid):
            receipt["last_frame_id"]=fid
            persist(receipt)
        try:
            self.discovery.require_online(device)
            with self.ledger.device_owner(device) as owner:
                if owner is None:
                    reject("DEVICE_BUSY","Device is busy")
                self.rt._interpret(resolved,context,request_owner,owner,receipt,persist,observe,
                                   guard=lambda:self.live_guard(resolved.definition_id,device))
            receipt["status"]="completed"
        except Exception as exc:
            reason=error_reason(exc,admitted=True,unknown=receipt["action_outcome"]=="unknown")
            receipt["reason"]=reason
            receipt["status"]="busy" if reason["code"]=="DEVICE_BUSY" else (
                "rejected" if not receipt["steps"] and receipt["action_outcome"]=="not_attempted" else "needs_agent")
        receipt["finished_at"]=time.time()
        self.ledger.record(request_owner,rid,receipt,terminal=True)
        return receipt

    def trial(self,preflight_id,device,run_id,return_image=False):
        req={"preflight_id":preflight_id,"device":device,"run_id":run_id}
        duplicate=self.ledger.duplicate(run_id,"trial",req)
        if duplicate is not None:
            return {**self.trial_inspect(run_id),"duplicate_request":True}
        with self.ledger.request_owner(run_id,timeout=2) as owner:
            if owner is None:
                duplicate=self.ledger.duplicate(run_id,"trial",req)
                if duplicate is not None:
                    return {**duplicate,"duplicate_request":True}
                reject("DEVICE_BUSY","Trial request is busy")
            duplicate=self.ledger.duplicate(run_id,"trial",req)
            if duplicate is not None:
                return {**self.trial_inspect(run_id),"duplicate_request":True}
            pf=self.preflight_inspect(preflight_id)
            if pf["device"]!=device:
                reject("SCOPE_MISMATCH","Preflight device differs")
            if pf["status"]!="pass":
                reject("PRECONDITION_FAILED","Successful preflight required")
            with self.definitions.pinned(pf["portable_id"]) as (resolved,record,recheck):
                context=ExecutionContext.create(resolved,"trial",device,record["profile"],run_id)
                if pf["profile"]!=context.profile or pf["geometry"]!=context.geometry:
                    reject("PROOF_INVALID","Preflight context differs")
                self.discovery.require_online(device)
                receipt=new_receipt("trial",run_id,device,req,preflight_id=preflight_id,
                                    portable_id=pf["portable_id"],context=context.to_dict(),source_seal=record["source_seal"])
                result=self.ledger.admit(owner,Claim(run_id,"trial",req,receipt,device=device),
                                         recheck=lambda db:recheck())
                if result is not None:
                    return result
            return self._run_owned(resolved,context,receipt,owner)

    def invoke(self,operation,request):
        try:
            req=normalize(operation,request)
            if operation in _DEFINITION_OPS:
                result=getattr(self.definitions,operation.removeprefix("portable_"))(**req)
            elif operation in _QUALIFICATION_OPS:
                result=getattr(self.slots,_QUALIFICATION_OPS[operation])(**req)
            elif operation in _FAMILY_OPS:
                result=getattr(self.families,_FAMILY_OPS[operation])(**req)
            elif operation in _ADMISSION_OPS:
                result=getattr(self.admission,operation.removeprefix("portable_"))(**req)
            elif operation in _BATCH_OPS:
                result=getattr(self.batches,operation.removeprefix("portable_"))(**req)
            else:
                result=getattr(self,operation.removeprefix("portable_"))(**req)
            status=result.get("status")
            code=0 if (operation.endswith(("_inspect","_record","_list")) or status not in
                        ("fail","needs_agent","busy","rejected","interrupted","not_attempted","partial")) else 3
            # Preflight performs no durable effect admission: capture/transport
            # timeout retains its observation receipt but uses K01 exit 4.
            if operation=="portable_preflight" and status=="fail" and (result.get("reason") or {}).get("code")=="CAPTURE_TIMEOUT":
                code=4
            return {"ok":True,"result":result},code
        except Exception as exc:
            reason=error_reason(exc)
            code=exc.exit_code if isinstance(exc,OperationError) and exc.exit_code in (2,4) else 3
            return {"ok":False,"error":reason},code
