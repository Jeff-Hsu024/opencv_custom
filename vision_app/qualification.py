"""Device qualification state, immutable proofs and generation-CAS mutations."""
from contextlib import contextmanager, ExitStack
import json
import time

from vision_app.coordinator import canonical_json
from vision_app.definition_core import ExecutionContext, proof_snapshot, verify_proof
from vision_app.observation import OperationError
from vision_app.portable import _hash
from vision_app.validation_context import EvidenceChanged
from vision_app.workflow import WorkflowError, require

def fault(code,message,details=None,retryable=False):
    return {"code":code,"message":message,"details":details or {},"retryable":retryable}

def reject(code,message):
    raise OperationError(code,message)

class QualificationSlots:
    def __init__(self,definitions):
        self.definitions=definitions
        self.rt=definitions.rt
        self.ledger=definitions.ledger

    @staticmethod
    def tables(db):
        db.execute("""CREATE TABLE IF NOT EXISTS qualification_slot(
            seq INTEGER PRIMARY KEY AUTOINCREMENT, portable_id TEXT NOT NULL, device TEXT NOT NULL,
            generation INTEGER NOT NULL, status TEXT NOT NULL, qualification_id TEXT NOT NULL,
            reason TEXT, changed_at REAL NOT NULL, UNIQUE(portable_id,device))""")
        db.execute("""CREATE TABLE IF NOT EXISTS qualification_record(
            qualification_id TEXT PRIMARY KEY, portable_id TEXT NOT NULL, device TEXT NOT NULL,
            immutable_json TEXT NOT NULL)""")
        db.execute("""CREATE TABLE IF NOT EXISTS qualification_mutation(
            op_hash TEXT PRIMARY KEY, receipt_json TEXT NOT NULL)""")

    @staticmethod
    def _slot(db,pid,device):
        return db.execute("SELECT * FROM qualification_slot WHERE portable_id=? AND device=?",(pid,device)).fetchone()

    def _view(self,db,pid,device):
        row=self._slot(db,pid,device)
        count=db.execute("SELECT count(*) FROM qualification_record WHERE portable_id=? AND device=?",(pid,device)).fetchone()[0]
        return {"portable_id":pid,"device":device,"slot_generation":row["generation"] if row else 0,
                "status":row["status"] if row else "absent","qualification_id":row["qualification_id"] if row else None,
                "reason":json.loads(row["reason"]) if row and row["reason"] is not None else None,
                "history_count":count}

    def inspect(self,portable_id,device):
        self.definitions.inspect(portable_id)
        with self.ledger.transaction() as db:
            self.tables(db)
            return self._view(db,portable_id,device)

    def list(self,portable_id,limit=20,after=0):
        self.definitions.inspect(portable_id)
        with self.ledger.transaction() as db:
            self.tables(db)
            rows=db.execute("SELECT seq,device FROM qualification_slot WHERE portable_id=? AND seq>? ORDER BY seq LIMIT ?",
                            (portable_id,after,limit+1)).fetchall()
            return {"items":[self._view(db,portable_id,row["device"]) for row in rows[:limit]],
                    "next_cursor":rows[limit-1]["seq"] if len(rows)>limit else None}

    def _record(self,db,qid):
        row=db.execute("SELECT immutable_json FROM qualification_record WHERE qualification_id=?",(qid,)).fetchone()
        if row is None:
            reject("NOT_FOUND","Qualification record not found")
        obj=json.loads(row["immutable_json"])
        r=obj["record"]
        require(qid==r["qualification_id"]=="qlf_"+_hash(self._identity(r,obj["profile"],obj["geometry"])),
                "Qualification identity changed")
        return obj

    def record(self,qualification_id):
        with self.ledger.transaction() as db:
            self.tables(db)
            return self._record(db,qualification_id)["record"]

    @staticmethod
    def _identity(record,profile,geometry):
        return {k:record[k] for k in ("portable_id","device","proof_seal","semantic_pass")} | {
            "profile":profile,"geometry":geometry}

    @staticmethod
    def _mutation(db,key):
        row=db.execute("SELECT receipt_json FROM qualification_mutation WHERE op_hash=?",(key,)).fetchone()
        return {**json.loads(row["receipt_json"]),"duplicate_request":True} if row else None

    @staticmethod
    def _save_mutation(db,key,receipt):
        db.execute("INSERT INTO qualification_mutation VALUES (?,?)",(key,canonical_json(receipt)))

    @staticmethod
    def _cas(slot,generation):
        if generation!=(slot["generation"] if slot is not None else 0):
            reject("STALE_GENERATION","Qualification generation changed")

    @contextmanager
    def proof(self,resolved,record,device,proof_kind,proof_id):
        """Validate source or actual completed target trial with a live evidence pin."""
        if proof_kind=="source":
            if (device,proof_id)!=(record["source_device"],record["source_run_id"]):
                reject("PROOF_INVALID","Source proof scope mismatch")
            yield record["source_seal"],None,lambda db:None
            return
        try:
            run=self.ledger.inspect(proof_id)
        except Exception as exc:
            raise OperationError("PROOF_INVALID","Trial proof not found") from exc
        if run.get("portable_id")!=record["portable_id"] or run.get("source_seal")!=record["source_seal"]:
            reject("PROOF_INVALID","Trial definition mismatch")
        with ExitStack() as stack:
            try:
                context=ExecutionContext.create(resolved,"trial",device,record["profile"],proof_id)
                snapshot=stack.enter_context(proof_snapshot(self.rt,run))
                before=snapshot.seals()
                verified=verify_proof(self.rt,resolved,context,run)
                seal=_hash({"verified":verified,"files":before})
                if snapshot.seals()!=before:
                    raise EvidenceChanged("Trial proof changed")
            except EvidenceChanged:
                raise
            except (WorkflowError,KeyError,TypeError,ValueError,OSError) as exc:
                raise OperationError("PROOF_INVALID","Trial proof invalid") from exc
            def recheck(db):
                snapshot.compare()
                row=self.ledger._row(db,proof_id)
                if row is None or row["kind"]!="trial" or row["state"]!="terminal" or self.ledger._receipt(row)!=run:
                    raise EvidenceChanged("Trial receipt changed")
            yield seal,run["finished_at"],recheck

    def commit(self,portable_id,device,expected_slot_generation,proof_kind,proof_id,semantic_pass):
        req={"portable_id":portable_id,"device":device,"expected_slot_generation":expected_slot_generation,
             "proof_kind":proof_kind,"proof_id":proof_id,"semantic_pass":semantic_pass}
        key=_hash({"operation":"commit","request":req})
        with self.ledger.transaction() as db:
            self.tables(db)
            duplicate=self._mutation(db,key)
            if duplicate is not None:
                return duplicate
        if not semantic_pass["observation"].strip() or not semantic_pass["reviewer"].strip():
            reject("INVALID_ARGUMENT","Semantic assertion requires observation and reviewer")
        with self.definitions.pinned(portable_id) as (resolved,record,source_recheck):
            with self.proof(resolved,record,device,proof_kind,proof_id) as (proof_seal,finished,proof_recheck):
                with self.ledger.transaction() as db:
                    self.tables(db)
                    duplicate=self._mutation(db,key)
                    if duplicate is not None:
                        return duplicate
                    slot=self._slot(db,portable_id,device)
                    self._cas(slot,expected_slot_generation)
                    if proof_kind=="source" and slot is not None:
                        reject("PROOF_INVALID","Source proof is only for first enrollment")
                    if slot is not None and (finished is None or finished<=slot["changed_at"]):
                        reject("PROOF_INVALID","A fresh trial after the slot transition is required")
                    source_recheck()
                    proof_recheck(db)
                    now=time.time()
                    receipt={"portable_id":portable_id,"device":device,"slot_generation":expected_slot_generation+1,
                             "status":"active","proof_kind":proof_kind,"proof_id":proof_id,"proof_seal":proof_seal,
                             "semantic_pass":semantic_pass,"created_at":now,"duplicate_request":False}
                    qid="qlf_"+_hash(self._identity(receipt,record["profile"],record["geometry"]))
                    receipt["qualification_id"]=qid
                    obj={"record":receipt,"profile":record["profile"],"geometry":record["geometry"]}
                    if db.execute("SELECT 1 FROM qualification_record WHERE qualification_id=?",(qid,)).fetchone():
                        reject("PROOF_INVALID","Qualification proof has already been enrolled")
                    db.execute("INSERT INTO qualification_record VALUES (?,?,?,?)",(qid,portable_id,device,canonical_json(obj)))
                    db.execute("""INSERT INTO qualification_slot(portable_id,device,generation,status,qualification_id,reason,changed_at)
                                  VALUES (?,?,?,'active',?,NULL,?) ON CONFLICT(portable_id,device) DO UPDATE SET
                                  generation=excluded.generation,status='active',qualification_id=excluded.qualification_id,
                                  reason=NULL,changed_at=excluded.changed_at""",(portable_id,device,receipt["slot_generation"],qid,now))
                    self._save_mutation(db,key,receipt)
                    return receipt

    def revoke(self,portable_id,device,expected_slot_generation,reason):
        req={"portable_id":portable_id,"device":device,"expected_slot_generation":expected_slot_generation,"reason":reason}
        key=_hash({"operation":"revoke","request":req})
        with self.ledger.transaction() as db:
            self.tables(db)
            duplicate=self._mutation(db,key)
            if duplicate is not None:
                return duplicate
            if not reason.strip():
                reject("INVALID_ARGUMENT","Revocation reason is required")
            slot=self._slot(db,portable_id,device)
            if slot is None:
                reject("NOT_FOUND","Qualification slot not found")
            self._cas(slot,expected_slot_generation)
            if slot["status"]!="active":
                reject("QUALIFICATION_INACTIVE","Qualification slot is not active")
            detail=fault("QUALIFICATION_INACTIVE",reason)
            generation=slot["generation"]+1
            receipt={"portable_id":portable_id,"device":device,"slot_generation":generation,"status":"revoked",
                     "qualification_id":slot["qualification_id"],"reason":detail,"duplicate_request":False}
            db.execute("UPDATE qualification_slot SET generation=?,status='revoked',reason=?,changed_at=? WHERE seq=?",
                       (generation,canonical_json(detail),time.time(),slot["seq"]))
            self._save_mutation(db,key,receipt)
            return receipt

    def observe(self,pid,device):
        with self.ledger.transaction() as db:
            self.tables(db)
            row=self._slot(db,pid,device)
            return dict(row) if row and row["status"]=="active" else None

    def invalidate(self,observed,reason):
        if observed is None or reason["code"] not in ("PROFILE_MISMATCH","GEOMETRY_MISMATCH"):
            return False
        with self.ledger.transaction() as db:
            self.tables(db)
            cur=self._slot(db,observed["portable_id"],observed["device"])
            if cur is None or (cur["generation"],cur["qualification_id"],cur["status"])!=(
                    observed["generation"],observed["qualification_id"],"active"):
                return False
            db.execute("UPDATE qualification_slot SET generation=generation+1,status='invalidated',reason=?,changed_at=? WHERE seq=?",
                       (canonical_json(reason),time.time(),cur["seq"]))
            return True

    @contextmanager
    def pinned_active(self,resolved,record,device):
        """Pin an active qualification and its immutable proof for admission."""
        with self.ledger.transaction() as db:
            self.tables(db)
            row=self._slot(db,record["portable_id"],device)
            if row is None:
                reject("QUALIFICATION_REQUIRED","Device qualification required")
            if row["status"]!="active":
                reject("QUALIFICATION_INACTIVE","Device qualification is inactive")
            slot=dict(row)
            obj=self._record(db,slot["qualification_id"])
        q=obj["record"]
        if (obj["profile"],obj["geometry"])!=(record["profile"],record["geometry"]):
            reject("PROOF_INVALID","Qualification profile or geometry changed")
        with self.proof(resolved,record,device,q["proof_kind"],q["proof_id"]) as (seal,_,proof_recheck):
            if seal!=q["proof_seal"]:
                reject("PROOF_INVALID","Qualification proof seal changed")
            def recheck(db):
                cur=self._slot(db,record["portable_id"],device)
                if cur is None or (cur["generation"],cur["qualification_id"],cur["status"])!=(
                        slot["generation"],slot["qualification_id"],"active"):
                    reject("STALE_GENERATION","Qualification changed before admission")
                proof_recheck(db)
            yield slot,q,recheck
