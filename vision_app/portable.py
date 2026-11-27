"""Portable definition publication and immutable, source-verified resolution."""
from contextlib import contextmanager, ExitStack
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import time

from vision_app.coordinator import canonical_json
from vision_app.definition_core import ExecutionContext, ResolvedDefinition, proof_snapshot, verify_proof
from vision_app.metadata import metadata_transaction
from vision_app.observation import OperationError
from vision_app.runtime import WorkflowRuntime
from vision_app.store import _atomic_write_bytes
from vision_app.validation_context import EvidenceChanged, evidence_snapshot, _identity
from vision_app.workflow import WorkflowError, canonical, digest, require

def _string(prefix,length):
    return {"type":"string","pattern":rf"^{prefix}_[0-9a-f]{{{length}}}$(?![\s\S])"}

def _schema(properties,required):
    return {"type":"object","properties":properties,"required":required,"additionalProperties":False}

SCHEMAS={
    "portable_publish":_schema({"source_workflow_id":_string("wf",64),
                                "source_run_id":_string("run",32)},["source_workflow_id","source_run_id"]),
    "portable_inspect":_schema({"portable_id":_string("portable",64)},["portable_id"]),
    "portable_list":_schema({"limit":{"type":"integer","minimum":1,"maximum":50,"default":20},
                             "after":{"type":"integer","minimum":0,"default":0}},[]),
}

def normalize(operation,request):
    schema=SCHEMAS[operation]
    props=schema["properties"]
    if type(request) is not dict or set(request)-props.keys() or set(schema["required"])-request.keys():
        raise OperationError("INVALID_ARGUMENT","Invalid request fields",exit_code=2)
    result={}
    for key,rule in props.items():
        value=request.get(key,rule.get("default"))
        if rule["type"]=="string":
            ok=isinstance(value,str) and re.fullmatch(rule["pattern"],value)
        else:
            ok=type(value) is int and rule["minimum"]<=value<=rule.get("maximum",2**63-1)
        if not ok:
            raise OperationError("INVALID_ARGUMENT",f"Invalid {key}",exit_code=2)
        result[key]=value
    return result

def _hash(value):
    return digest(canonical_json(value).encode("utf-8"))

class PortableDefinitions:
    def __init__(self,store,*,runtime=None):
        self.store=store
        self.rt=runtime or WorkflowRuntime(store)
        self.ledger=self.rt.epochs
        self.root=store.store_dir/"portable"

    @staticmethod
    def _table(db):
        db.execute("CREATE TABLE IF NOT EXISTS portable_definition (seq INTEGER PRIMARY KEY AUTOINCREMENT, portable_id TEXT UNIQUE NOT NULL, immutable_json TEXT NOT NULL)")

    def _load(self,pid):
        if not isinstance(pid,str) or not re.fullmatch(r"portable_[a-f0-9]{64}",pid):
            raise OperationError("INVALID_ARGUMENT","Invalid portable identity",exit_code=2)
        with self.ledger.transaction() as db:
            self._table(db)
            row=db.execute("SELECT immutable_json FROM portable_definition WHERE portable_id=?",(pid,)).fetchone()
        if row is None:
            raise OperationError("NOT_FOUND","Portable definition not found")
        obj=json.loads(row["immutable_json"])
        body={k:v for k,v in obj["record"].items() if k not in ("portable_id","created_at")}
        require(pid==obj["record"]["portable_id"]=="portable_"+_hash({"record":body,"definition":obj["definition"],"proof":obj["proof"]}),
                "Portable definition identity mismatch")
        return obj

    @contextmanager
    def _source(self,wid,rid):
        with ExitStack() as stack:
            try:
                run=self.rt._load("runs",rid)
                binding=self.rt._binding(run["binding_id"])
                require(run["status"]=="completed" and run["workflow_id"]==wid and
                        all(binding[k]==run[k] for k in ("workflow_id","device","profile")),
                        "Need completed matching source proof")
                paths=(self.rt._path("runs",rid),self.rt._path("bindings",run["binding_id"]))
                source=stack.enter_context(evidence_snapshot(self.rt.builder,None,None,wid=wid))
                proof=stack.enter_context(proof_snapshot(self.rt,run,paths=paths))
                before=source.seals()
                proof_files=proof.seals()
                require(run==self.rt._load("runs",rid) and binding==self.rt._binding(run["binding_id"]),
                        "Source receipt changed")
                resolved=self.rt._resolve(wid,run["device"],run["profile"])
                context=ExecutionContext.create(resolved,"legacy",run["device"],run["profile"],rid,binding_id=run["binding_id"])
                verified=verify_proof(self.rt,resolved,context,run)
                geometry=context.geometry
                definition=resolved.definition
                definition["geometry"]=geometry
                seal=_hash({"workflow_seals":before,"proof":verified,"proof_files":proof_files})
                record={"source_workflow_id":wid,"source_run_id":rid,
                        "source_device":run["device"],"source_seal":seal,"profile":run["profile"],
                        "geometry":geometry,"step_count":len(definition["steps"]),
                        "template_sha256":[sha for sha,_ in resolved.template_bytes]}
                identity={"record":record,"definition":definition,"proof":verified}
                pid="portable_"+_hash(identity)
                obj={**identity,"record":{**record,"portable_id":pid,"created_at":time.time()}}
            except EvidenceChanged:
                raise
            except (WorkflowError,KeyError,ValueError,TypeError,OSError) as exc:
                raise OperationError("PROOF_INVALID","Source proof is invalid or incomplete") from exc
            yield obj,resolved.template_bytes,source,before,proof,proof_files

    def publish(self,source_workflow_id,source_run_id):
        with self._source(source_workflow_id,source_run_id) as (obj,templates,source,before,proof,proof_files):
            pid=obj["record"]["portable_id"]
            self.root.mkdir(parents=True,exist_ok=True)
            target=self.root/pid
            staging=Path(tempfile.mkdtemp(prefix=".portable_",dir=self.root))
            try:
                for sha,data in templates:
                    _atomic_write_bytes(staging/"templates"/(sha+".png"),data)
                # Check already published bytes outside the metadata lock. If
                # another publisher wins, validate its bytes after the CAS.
                orphan_identity=None
                if target.exists():
                    paths=(target,target/"templates",*(target/"templates"/(sha+".png") for sha,_ in templates))
                    orphan_identity=tuple(_identity(path) for path in paths)
                    if not self._same_files(target,templates):
                        raise OperationError("STORE_ERROR","Existing portable template bundle differs")
                if proof.seals()!=proof_files:
                    raise EvidenceChanged("Source proof changed")
                with source.commit(before):
                    proof.compare()
                    with self.ledger.transaction() as db:
                        self._table(db)
                        row=db.execute("SELECT immutable_json FROM portable_definition WHERE portable_id=?",(pid,)).fetchone()
                        if row is None:
                            if not target.exists():
                                os.replace(staging,target)
                            # An orphan after a crash cannot become authoritative
                            # until its exact immutable bytes have been verified.
                            elif orphan_identity is None or orphan_identity!=tuple(_identity(path) for path in paths):
                                raise EvidenceChanged("Portable orphan changed before publication")
                            db.execute("INSERT INTO portable_definition(portable_id,immutable_json) VALUES (?,?)",
                                       (pid,canonical_json(obj)))
                stored=self._load(pid)
                self._read_templates(stored)
                return stored["record"]
            finally:
                if staging.exists():
                    shutil.rmtree(staging)

    @staticmethod
    def _same_files(directory,templates):
        folder=directory/"templates"
        return (not directory.is_symlink() and not folder.is_symlink() and folder.is_dir()
                and {p.name for p in folder.iterdir()}=={sha+".png" for sha,_ in templates}
                and all(not (folder/(sha+".png")).is_symlink() and
                        (folder/(sha+".png")).read_bytes()==data for sha,data in templates))

    def _read_templates(self,obj):
        record=obj["record"]
        directory=self.root/record["portable_id"]
        folder=directory/"templates"
        require(not directory.is_symlink() and not folder.is_symlink() and folder.is_dir(),
                "Portable template bundle missing")
        expected=record["template_sha256"]
        require({p.name for p in folder.iterdir()}=={sha+".png" for sha in expected},"Portable template set differs")
        blobs=[]
        for sha in expected:
            require(re.fullmatch(r"[a-f0-9]{64}",sha),"Invalid template hash")
            path=folder/(sha+".png")
            require(not path.is_symlink(),"Portable template symlink")
            data=path.read_bytes()
            require(digest(data)==sha,"Portable template hash mismatch")
            blobs.append((sha,data))
        return tuple(blobs)

    @contextmanager
    def pinned(self,pid):
        obj=self._load(pid)
        record=obj["record"]
        with self._source(record["source_workflow_id"],record["source_run_id"]) as (current,templates,source,before,proof,proof_files):
            if (current["record"]["portable_id"]!=pid or current["definition"]!=obj["definition"]
                    or current["proof"]!=obj["proof"]):
                raise EvidenceChanged("Published portable source changed")
            directory=self.root/pid
            paths=(directory,directory/"templates",*(directory/"templates"/(sha+".png") for sha,_ in templates))
            identities=tuple(_identity(path) for path in paths)
            blobs=self._read_templates(obj)
            require(blobs==templates,"Portable template evidence differs")
            resolved=ResolvedDefinition("portable",pid,record["source_workflow_id"],record["source_device"],
                                        record["source_seal"],canonical(obj["definition"]),blobs,canonical(record["profile"]))
            def recheck():
                source.compare()
                proof.compare()
                if tuple(_identity(path) for path in paths)!=identities:
                    raise EvidenceChanged("Portable bundle changed before admission")
            if proof.seals()!=proof_files:
                raise EvidenceChanged("Source proof changed")
            with source.commit(before):
                proof.compare()
            yield resolved,record,recheck

    def resolve(self,pid):
        with self.pinned(pid) as (resolved,_,recheck):
            with metadata_transaction(self.store):
                recheck()
            return resolved

    def inspect(self,portable_id):
        return self._load(portable_id)["record"]

    def list(self,limit=20,after=0):
        with self.ledger.transaction() as db:
            self._table(db)
            rows=db.execute("SELECT seq,immutable_json FROM portable_definition WHERE seq>? ORDER BY seq LIMIT ?",(after,limit+1)).fetchall()
        return {"items":[json.loads(row["immutable_json"])["record"] for row in rows[:limit]],
                "next_cursor":rows[limit-1]["seq"] if len(rows)>limit else None}

    def invoke(self,operation,request):
        try:
            req=normalize(operation,request)
            result=getattr(self,operation.removeprefix("portable_"))(**req)
            return {"ok":True,"result":result},0
        except OperationError as exc:
            code,message,retryable,exit_code=exc.code,exc.message,exc.retryable,exc.exit_code
        except EvidenceChanged:
            code,message,retryable,exit_code="EVIDENCE_CHANGED","Portable source evidence changed",False,3
        except WorkflowError:
            code,message,retryable,exit_code="PROOF_INVALID","Portable proof or definition invalid",False,3
        except Exception:
            code,message,retryable,exit_code="INTERNAL_ERROR","Internal portable definition error",False,3
        return {"ok":False,"error":{"code":code,"message":message,"details":{},"retryable":retryable}},exit_code
