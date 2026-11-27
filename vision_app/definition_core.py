"""Shared immutable definitions, target contexts and proof verification."""
from contextlib import contextmanager, ExitStack
from dataclasses import dataclass
import json
import re
from pathlib import Path

from vision_app.metadata import metadata_transaction
from vision_app.validation_context import EvidenceChanged, _identity
from vision_app.workflow import canonical, decode, digest, require


@dataclass(frozen=True)
class ResolvedDefinition:
    kind: str
    definition_id: str
    source_workflow_id: str
    source_device: str
    source_seal: str
    definition_json: bytes
    template_bytes: tuple[tuple[str, bytes], ...]
    profile_json: bytes | None = None

    @property
    def definition(self):
        return json.loads(self.definition_json)

    def templates(self):
        return {sha: decode(data) for sha, data in self.template_bytes}

    @property
    def geometry(self):
        return self.definition["geometry"]


@dataclass(frozen=True)
class ExecutionContext:
    kind: str
    definition_id: str
    source_workflow_id: str
    source_seal: str
    device: str
    profile_json: bytes
    geometry_json: bytes
    admission_id: str
    binding_id: str | None
    qualification_id: str | None

    @property
    def profile(self):
        return json.loads(self.profile_json)

    @property
    def geometry(self):
        return json.loads(self.geometry_json)

    def to_dict(self):
        return {key: getattr(self,key) for key in (
            "kind","definition_id","source_workflow_id","source_seal","device",
            "admission_id","binding_id","qualification_id")} | {
                "profile":self.profile,"geometry":self.geometry}

    @classmethod
    def create(cls,resolved,kind,device,profile,admission_id,*,binding_id=None,qualification_id=None):
        geometry=resolved.geometry
        if geometry["rotation"] is None:
            geometry["rotation"]=profile["rotation"]
        context=cls(kind,resolved.definition_id,resolved.source_workflow_id,resolved.source_seal,
                    device,canonical(profile),canonical(geometry),admission_id,binding_id,qualification_id)
        context.verify(resolved)
        return context

    def verify(self,resolved):
        from vision_app.runtime import profile_shape
        from vision_app.discovery import validate_serial
        profile_shape(self.profile)
        if self.kind!="legacy":
            validate_serial(self.device)
        require((self.definition_id,self.source_workflow_id,self.source_seal)==
                (resolved.definition_id,resolved.source_workflow_id,resolved.source_seal),
                "Definition context identity mismatch")
        expected=resolved.geometry
        if expected["rotation"] is None:
            expected["rotation"]=self.profile["rotation"]
        require(self.geometry==expected and expected["rotation"]==self.profile["rotation"],
                "Definition context geometry mismatch")
        if self.kind=="legacy":
            require(resolved.kind=="legacy" and self.device==resolved.source_device and
                    isinstance(self.binding_id,str) and re.fullmatch(r"bind_[a-f0-9]{64}",self.binding_id)
                    and self.qualification_id is None and re.fullmatch(r"run_[a-f0-9]{32}",self.admission_id),
                    "Legacy context mismatch")
        else:
            require(resolved.kind=="portable" and self.profile_json==resolved.profile_json and self.kind in ("trial","portable_run")
                    and self.binding_id is None and re.fullmatch(r"prun_[a-f0-9]{32}",self.admission_id)
                    and (self.qualification_id is None if self.kind=="trial" else
                         isinstance(self.qualification_id,str) and re.fullmatch(r"qlf_[a-f0-9]{64}",self.qualification_id)),
                    "Portable context mismatch")


def resolve_legacy(runtime,wid,device,profile):
    from vision_app.runtime import profile_shape
    profile_shape(profile)
    require(isinstance(device,str) and device not in ("adb","desktop") and re.fullmatch(r"[A-Za-z0-9_.:-]+",device),
            "Explicit Android serial required")
    runtime.builder._validate(wid)
    item=runtime.builder.inspect(wid)
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
        templates[sha]=data
    return ResolvedDefinition("legacy",wid,wid,device,digest(canonical(d)),
                              canonical(d),tuple(sorted(templates.items())))


def verify_proof(runtime,resolved,context,run):
    """Verify actual guard, matching, reference and action evidence, not reported PASS."""
    context.verify(resolved)
    strict=context.kind!="legacy"
    require(run["status"]=="completed" and run["device"]==context.device and
            (run.get("context")==context.to_dict() and run.get("kind")==context.kind
             and run.get("id")==context.admission_id if strict else
             run.get("run_id")==context.admission_id and run.get("workflow_id")==context.source_workflow_id
             and run.get("binding_id")==context.binding_id and run.get("profile")==context.profile),
            "Need completed matching runtime run")
    d,t=resolved.definition,resolved.templates()

    def frame(fid,device,geometry):
        f=runtime.store.get_frame(fid,device_id=device)
        require(f.protected and f.parent_id is None and f.width==f.source_width and
                f.height==f.source_height,"Need protected original full-device frame")
        require((f.width,f.height)==(geometry["width"],geometry["height"]),"Proof frame geometry mismatch")
        if strict:
            require(f.rotation is None or f.rotation==context.geometry["rotation"],"Proof frame rotation mismatch")
        data=runtime.store.resolve_image_path(f.image_path).read_bytes()
        img=decode(data)
        require(img.shape[:2]==(f.height,f.width),"Frame dimensions differ")
        return img,digest(data)
    require(run["completed_steps"]==len(d["steps"])==len(run["steps"]) and
            run["last_confirmed_state"]==d["final_state"] and run["action_outcome"]=="verified",
            "Incomplete proof run")
    hashes={}
    source_frames=set(d["source"]["frame_sha256"])
    used_frames=set()
    previous=None
    refs=set()
    historical_refs={step["provenance"]["source_ref_id"] for step in d["steps"]}
    for s,step in zip(run["steps"],d["steps"]):
        require(s["step_id"]==step["id"] and s["status"]=="verified"
                and s["from"]==step["from"] and s["to"]==step["to"],"Invalid verified step")
        pre,ph=frame(s["pre_frame_id"],run["device"],d["geometry"])
        post,qh=frame(s["post_frame_id"],run["device"],d["geometry"])
        for image,expected in ((pre,step["from"]),(post,step["to"])):
            state=runtime._classify(image,d,t)
            require(not state["ambiguous"] and state["state"]==expected,"Proof state guard mismatch")
        m=runtime._matches(pre,step["action"],t)
        target=s["target"];receipt=s["action_receipt"]
        require(len(m)==1 and list(m[0].bbox)==target["device_bbox"] and
                target["frame_id"]==s["pre_frame_id"] and target["ref_id"] not in refs and target["ref_id"] not in historical_refs and
                target["template_sha256"]==step["action"]["template"]["sha256"],"Proof target mismatch")
        ref=runtime.refs.get(target["ref_id"])
        require(ref.frame_id==s["pre_frame_id"] and ref.device_id==run["device"] and
                list(ref.device_bbox)==target["device_bbox"] and
                receipt["source"]["ref_id"]==ref.ref_id and receipt["source"]["frame_id"]==ref.frame_id and
                receipt["status"]=="executed" and receipt["verified"] is False and receipt["device_id"]==run["device"] and
                [receipt["target"]["x"],receipt["target"]["y"]]==list(ref.device_center),"Proof receipt mismatch")
        before=runtime.store.get_frame(s["pre_frame_id"])
        # Match geometry and center must be derived from the verified pixels,
        # not from a pair of mutually consistent but substituted ref/receipt fields.
        expected_center=before.transform.map_point(*(int(round(v)) for v in m[0].center))
        require(list(ref.bbox)==list(m[0].bbox) and list(ref.device_center)==list(expected_center)
                and ref.source_width==before.source_width and ref.source_height==before.source_height
                and ref.rotation==before.rotation and receipt.get("action")=="click"
                and receipt["source"].get("mode")=="ref","Proof reference geometry mismatch")
        after=runtime.store.get_frame(s["post_frame_id"])
        require(before.timestamp<=ref.created_at<=receipt["executed_at"]<=after.timestamp
                and receipt["executed_at"]-before.timestamp<=step["action"]["max_ref_age_seconds"],"Proof action chronology mismatch")
        if strict:
            stamp=runtime.epochs.ref_epoch(ref.ref_id)
            before_epoch=runtime.epochs.frame_epoch(before.frame_id,context.device)
            after_epoch=runtime.epochs.frame_epoch(after.frame_id,context.device)
            require(stamp is not None and stamp.device==context.device and stamp.session_id is None
                    and before_epoch is not None and stamp.epoch==before_epoch==target["epoch"]
                    and after_epoch==before_epoch+1==s["action_epoch"],"Proof epoch mismatch")
            require(before.frame_id not in source_frames and after.frame_id not in source_frames
                    and before.frame_id not in used_frames and after.frame_id not in used_frames
                    and before.frame_id!=after.frame_id,"Proof frame reuse")
            require(previous is None or previous<=before.timestamp,"Proof step chronology mismatch")
            with runtime.epochs.transaction() as db:
                intent=db.execute("SELECT epoch FROM action_intent WHERE request_id=? AND step_id=?",
                                  (context.admission_id,step["id"])).fetchone()
            require(intent is not None and intent["epoch"]==after_epoch,"Proof durable intent mismatch")
            last=receipt["executed_at"]
            post_ids=set()
            require(s["post_observations"] and s["post_observations"][-1]["frame_id"]==after.frame_id,
                    "Proof lacks final post observation")
            for observation in s["post_observations"]:
                fid=observation["frame_id"]
                image,sha=frame(fid,context.device,d["geometry"])
                observed=runtime.store.get_frame(fid,device_id=context.device)
                require(fid not in used_frames|source_frames|post_ids and fid!=before.frame_id and
                        last<=observed.timestamp and runtime.epochs.frame_epoch(fid,context.device)==after_epoch,
                        "Proof post observation chronology mismatch")
                actual=runtime._classify(image,d,t)
                require(actual=={k:observation[k] for k in ("state","ambiguous","guards")} and
                        not actual["ambiguous"] and actual["state"] in (None,step["from"],step["to"]),
                        "Proof post observation guard mismatch")
                last=observed.timestamp
                post_ids.add(fid)
                hashes[fid]=sha
            used_frames.update({before.frame_id}|post_ids)
            previous=after.timestamp
        refs.add(ref.ref_id)
        hashes[s["pre_frame_id"]]=ph;hashes[s["post_frame_id"]]=qh
        hashes[ref.ref_id]=digest(canonical(ref.to_dict()))
    require(run["last_frame_id"]==run["steps"][-1]["post_frame_id"],"Proof endpoint mismatch")

    if strict:
        require(run.get("finished_at") is not None and run.get("observation_phase")=="post_action",
                "Proof incomplete terminal observation")
        return {"context":context.to_dict(),"run_sha256":digest(canonical(run)),
                "evidence_sha256":hashes,"template_sha256":[sha for sha,_ in resolved.template_bytes]}
    return {"run_id":context.admission_id,"run_sha256":digest(canonical(run)),
            "evidence_sha256":hashes,"device":run["device"],"profile":run["profile"]}


def legacy_proof(runtime,wid,run_id):
    run=runtime._load("runs",run_id)
    require(run["status"]=="completed" and run["workflow_id"]==wid,"Need completed matching runtime run")
    binding=runtime._binding(run["binding_id"])
    require(all(binding[k]==run[k] for k in ("workflow_id","device","profile")),"Proof binding mismatch")
    resolved=runtime._resolve(wid,run["device"],run["profile"])
    context=ExecutionContext.create(resolved,"legacy",run["device"],run["profile"],run_id,
                                    binding_id=run["binding_id"])
    return verify_proof(runtime,resolved,context,run),run,resolved.definition


class ProofSnapshot:
    """Pin proof frames and capture cooperative file/index identities for publication CAS."""
    def __init__(self,runtime,run,pins,*,paths=()):
        self.rt=runtime
        ids=sorted(set(run.get("frames",[]))|{fid for step in run["steps"] for fid in
                    (step.get("pre_frame_id"),step.get("post_frame_id"),
                     *(o["frame_id"] for o in step.get("post_observations",[]))) if fid})
        self.frames={f.frame_id:f for f in pins.enter_context(runtime.store.pin_frames(ids,device_id=run["device"]))}
        _,revisions=runtime.store._indexed_evidence()
        self.revisions={fid:revisions.get(fid,0) for fid in self.frames}
        refs={step["target"]["ref_id"] for step in run["steps"] if step.get("target")}
        self.paths=tuple(sorted(set(paths)|{runtime.store.resolve_image_path(f.image_path) for f in self.frames.values()}
                                |{runtime.refs._ref_path(rid) for rid in refs},key=str))
        self.identities=tuple(_identity(path) for path in self.paths)
        require(all(self.identities),"Proof evidence missing")

    def seals(self):
        return {"files":{path.relative_to(self.rt.store.store_dir).as_posix():digest(path.read_bytes()) for path in self.paths},
                "frames":{fid:f.to_dict() for fid,f in self.frames.items()},
                "frame_revisions":self.revisions}

    def compare(self):
        index,revs=self.rt.store._indexed_evidence()
        if (any(index.get(fid)!=f or revs.get(fid,0)!=self.revisions[fid] for fid,f in self.frames.items())
                or tuple(_identity(path) for path in self.paths)!=self.identities):
            raise EvidenceChanged("Runtime proof evidence changed")


@contextmanager
def proof_snapshot(runtime,run,*,paths=()):
    with ExitStack() as pins:
        with metadata_transaction(runtime.store):
            snap=ProofSnapshot(runtime,run,pins,paths=paths)
        yield snap
