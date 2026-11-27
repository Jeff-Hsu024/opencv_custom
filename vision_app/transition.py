"""Recorded one-click transition: one lock, ordinary primitive receipts, no semantic inference."""
from __future__ import annotations

import json
import hashlib
import math
import re
from contextlib import ExitStack
from pathlib import Path
import time

from vision_app.actions import ActionService
from vision_app.assets import AssetRegistry, MatchingService, recorded_asset_snapshots
from vision_app.asset_revisions import AssetRevisionStore, _DEVICE, _SESSION
from vision_app.coordinator import Claim, ClaimError
from vision_app.discovery import DiscoveryService
from vision_app.epochs import ActionIntent, DeviceEpochs
from vision_app.metadata import metadata_transaction
from vision_app.primitives import _failure, _reason, _string
from vision_app.observation import ObservationService, OperationError, _artifact_for_record
from vision_app.recorder import Recorder, RecorderError
from vision_app.store import _atomic_write_json, StoreError
from vision_app.waits import WaitService, WaitFailure


_REVISION = _string(r"^ar_[0-9a-f]{64}$(?![\s\S])")
_DURATION = {"type": "number", "exclusiveMinimum": 0, "maximum": 60}
_THRESHOLD = {"type": "number", "minimum": 0.8, "maximum": 1, "default": 0.98}
_WAIT = {
    "timeout": _DURATION,
    "region": {
        "anyOf": [{"type": "array", "items": {"type": "integer", "minimum": 0},
                   "minItems": 4, "maxItems": 4}, {"type": "null"}],
        "default": None,
    },
    "settle_seconds": {"type": "number", "minimum": 0, "maximum": 2, "default": 0},
}
SCOPED_TRANSITION_SCHEMA = {
    "type": "object",
    "properties": {
        "device": _string(_DEVICE),
        "session_id": _string(_SESSION),
        "transition_id": _string(r"^strans_[0-9a-f]{32}$(?![\s\S])"),
        "target_asset_revision_id": _REVISION,
        "pre_state_asset_revision_id": {"anyOf": [_REVISION, {"type": "null"}], "default": None},
        "postcondition": {"oneOf": [
            {"type": "object", "additionalProperties": False, "required": ["mode", "timeout"],
             "properties": {"mode": {"const": "changed"}, **_WAIT,
                            "min_changed_ratio": {"type": "number", "minimum": 0, "maximum": 1, "default": 0.01}}},
            {"type": "object", "additionalProperties": False, "required": ["mode", "timeout", "asset_revision_id"],
             "properties": {"mode": {"const": "image"}, **_WAIT, "asset_revision_id": _REVISION,
                            "threshold": _THRESHOLD}},
        ]},
        "threshold": _THRESHOLD,
        "max_ref_age_seconds": {**_DURATION, "default": 15},
        "return_image": {"type": "boolean", "default": False},
    },
    "required": ["device", "session_id", "transition_id", "target_asset_revision_id", "postcondition"],
    "additionalProperties": False,
}


def _normalize(rule, value):
    if "const" in rule and value != rule["const"]:
        raise ValueError()
    choices = rule.get("anyOf", rule.get("oneOf"))
    if choices:
        for choice in choices:
            try:
                return _normalize(choice, value)
            except ValueError:
                continue
        raise ValueError()
    kind = rule.get("type")
    if kind == "object":
        props = rule["properties"]
        if type(value) is not dict or set(value) - props.keys() or set(rule["required"]) - value.keys():
            raise ValueError()
        return {key: _normalize(field, value.get(key, field.get("default"))) for key, field in props.items()}
    if kind == "array":
        if type(value) is not list or len(value) != rule["minItems"]:
            raise ValueError()
        return [_normalize(rule["items"], item) for item in value]
    if kind in ("integer", "number"):
        if type(value) not in (int, float) or value > rule.get("maximum", math.inf):
            raise ValueError()
        if not math.isfinite(value) or value < rule.get("minimum", -math.inf):
            raise ValueError()
        if value <= rule.get("exclusiveMinimum", -math.inf):
            raise ValueError()
        if kind == "integer" and int(value) != value:
            raise ValueError()
        return int(value) if kind == "integer" else value
    if kind == "string" and (type(value) is not str or not re.fullmatch(rule["pattern"], value)):
        raise ValueError()
    if kind == "boolean" and type(value) is not bool:
        raise ValueError()
    if kind == "null" and value is not None:
        raise ValueError()
    return value


def _scoped_request(request):
    try:
        req = _normalize(SCOPED_TRANSITION_SCHEMA, request)
        region = req["postcondition"]["region"]
        if region and (region[0] >= region[2] or region[1] >= region[3]):
            raise ValueError()
        return req
    except (ValueError, OverflowError):
        raise OperationError("INVALID_ARGUMENT", "Invalid scoped transition request", exit_code=2) from None


def _scoped_reason(reason, outcome):
    code = reason["code"]
    if outcome == "unknown":
        code = "ACTION_UNCERTAIN"
    elif code in ("WAIT_TIMEOUT", "WAIT_UNVERIFIED"):
        code = "PRECONDITION_FAILED"
    elif "TIMEOUT" in code:
        code = "CAPTURE_TIMEOUT"
    elif code == "INVALID_TRANSITION":
        code = "PRECONDITION_FAILED"
    elif code not in {"CAPTURE_TIMEOUT", "PRECONDITION_FAILED", "TARGET_NOT_FOUND", "TARGET_AMBIGUOUS",
                       "FRAME_STALE", "REF_UNVERSIONED", "STALE_REF_EPOCH", "SCOPE_MISMATCH",
                       "DEVICE_UNAVAILABLE", "STORE_ERROR", "NOT_FOUND", "EVIDENCE_CHANGED", "INTERNAL_ERROR"}:
        code = "INTERNAL_ERROR"
    result = _reason(code, reason["message"] if code != "INTERNAL_ERROR" else "Internal transition error")
    if "match_count" in reason:
        result["details"]["match_count"] = reason["match_count"]
    return result


def check(ok,message):
    if not ok: raise RecorderError(message,code="INVALID_TRANSITION")


def bounded(value,lo,hi):
    return type(value) in (float,int) and math.isfinite(value) and lo<=value<=hi


class TransitionService:
    def __init__(self,store,*,observation=None,matcher=None,actions=None,waits=None):
        self.store=store
        self.rec=Recorder(store)
        self.obs=observation or ObservationService(store)
        self.assets=AssetRegistry(store.store_dir)
        self.matcher=matcher or MatchingService(store=store,assets=self.assets)
        self.actions=actions or ActionService(store,platform_factory=self.obs._platform_factory)
        self.waits=waits or WaitService(store,asset_registry=self.assets,platform_factory=self.obs._platform_factory)
        self.epochs = DeviceEpochs(store)
        self.root=store.store_dir/"transitions"

    def _path(self,tid):
        check(isinstance(tid,str) and re.fullmatch(r"trans_[a-f0-9]{32}",tid),"Invalid transition ID")
        return self.root/(tid+".json")

    def _save(self,t):
        t["updated_at"]=time.time()
        with metadata_transaction(self.store):
            _atomic_write_json(self._path(t["transition_id"]), t)

    def _finish(self,t,status,reason=None):
        t["status"]=status;t["reason"]=reason;t["finished_at"]=time.time()
        self._save(t)
        return t

    @staticmethod
    def _clear_observation(t,phase):
        t.update(last_frame_id=None,last_observed_frame_id=None,artifact=None,
                 last_capture_timestamp=None,observation_phase=phase)

    def _observe(self,t,role,payload):
        """Only real snapshot or wait observations can advance the frame pointer."""
        if role=="action":
            self._clear_observation(t,"post_action_unknown")
            return
        if role not in ("pre","wait","post") or not isinstance(payload,dict):
            return
        data=payload if payload.get("ok") else payload.get("operation_result")
        if role=="wait":
            data=data if isinstance(data,dict) else {}
            t["wait"]={k:data.get(k) for k in ("condition","verified","frame_id","elapsed_seconds",
                       "captures","last_capture_timestamp","capture_role","retention_error")}
            t["wait"]["verified"]=data.get("verified") is True and payload.get("ok") is True
            t["wait"]["status"]=data.get("status") or ("verified" if t["wait"]["verified"] else
                "timeout" if "TIMEOUT" in str((payload.get("error") or {}).get("code","")) else "failed")
        if not isinstance(data,dict):
            return
        # Snapshot on failure is not a trustworthy observation; WaitFailure is explicitly typed upstream.
        if role!="wait" and not payload.get("ok"):
            return
        fid=data.get("frame",{}).get("frame_id") or data.get("frame_id")
        if not fid:
            return
        try:
            frame=self.store.get_frame(fid,device_id=t["request"]["device"])
            artifact=_artifact_for_record(self.store,frame)
            if not frame.protected or frame.parent_id is not None or not Path(artifact["path"]).is_file():
                return
        except (StoreError,ValueError,OSError):
            return
        t.update(last_frame_id=fid,last_observed_frame_id=fid,artifact=artifact,
                 last_capture_timestamp=frame.timestamp,
                 observation_phase="pre_action" if role=="pre" else "post_action")
        if role=="pre":t["pre_frame_id"]=fid
        if role=="post":t["post_frame_id"]=fid

    def _restore_observations(self,t, *, pending=None):
        # Rebuild from durable events only. Do not trust the old pre-click pointer.
        prior_action=t.get("action_outcome")
        t.update(pre_frame_id=None,post_frame_id=None,wait=None)
        self._clear_observation(t,"none")
        with self.rec.db() as db:
            rows=db.execute("""SELECT event_id,operation,status,result FROM events
                         WHERE session_id=? AND json_extract(inputs,'$.transition_id')=?
                         ORDER BY sequence""",(t["request"]["session_id"],t["transition_id"])).fetchall()
        t["events"]={}
        for r in rows:
            payload=json.loads(r["result"]) if r["result"] else None
            role="post" if r["operation"]=="snapshot" and "pre" in t["events"] else {"snapshot":"pre","find":"find","click":"action","wait":"wait"}[r["operation"]]
            t["events"][role]=r["event_id"]
            if role=="action":
                if r["status"] == "success":
                    t["action_outcome"] = "executed_unverified"
                    if t.get("step"):
                        t["step"]["action_receipt"] = self._raw_action(payload)
                elif pending is not False:
                    t["action_outcome"] = "unknown"
                if t["action_outcome"] != "not_attempted":
                    self._clear_observation(t,"post_action_unknown")
            else:
                self._observe(t,role,payload)
        # A crash after writing action intent but before inserting the click event is uncertain.
        if "action" not in t["events"] and prior_action in ("unknown","executed_unverified"):
            t["action_outcome"]=prior_action
            self._clear_observation(t,"post_action_unknown")
        return t

    def _reconcile(self, t):
        transition_id = t["transition_id"]

        def finish(pending=None):
            nonlocal t
            t = self.inspect(transition_id)
            if t["status"] != "running":
                return t
            if pending is not None:
                t["action_outcome"] = pending
            self._restore_observations(t, pending=t["action_outcome"] != "not_attempted")
            return self._finish(t, "interrupted", {
                "code": "TRANSITION_INTERRUPTED",
                "message": "Previous writer ended; inspect receipts and fresh state. Do not replay.",
            })

        def abandoned(owner, claim):
            finish(pending=claim["action_outcome"])
            return {"action_outcome": t["action_outcome"]}

        try:
            self.epochs.inspect(transition_id, abandoned)
        except ClaimError as exc:
            if exc.code != "NOT_FOUND":
                raise
            with self.epochs.request_owner(transition_id, legacy=True) as owner:
                if owner is not None:
                    return finish()
        return self.inspect(transition_id)

    def inspect(self,transition_id):
        p=self._path(transition_id)
        check(p.is_file() and not p.is_symlink(),"Transition not found")
        t=json.loads(p.read_text(encoding="utf-8"))
        # Adapt legacy receipts in memory, never rewrite historical journals.
        if "observation_phase" not in t:
            t["legacy_receipt"]=True
            self._restore_observations(t)
        elif t["status"] == "running":
            try:
                claim = self.epochs.inspect(transition_id)
            except ClaimError as exc:
                if exc.code != "NOT_FOUND":
                    raise
            else:
                t["action_outcome"] = claim["action_outcome"]
                self._restore_observations(t, pending=claim["action_outcome"] != "not_attempted")
        return t

    def execute(self,device,session_id,transition_id,target,postcondition,threshold=.98,max_ref_age_seconds=15,return_image=True,pre_state=None):
        check(isinstance(device,str) and device not in ("","adb","desktop"),"Explicit Android device required")
        check(isinstance(session_id,str) and bool(session_id),"Explicit session required")
        check(isinstance(target,str) and bool(target),"Target asset required")
        check(bounded(threshold,.8,1),"threshold must be 0.8..1")
        check(bounded(max_ref_age_seconds,.001,60),"max_ref_age_seconds must be >0 and <=60")
        check(type(return_image) is bool,"return_image must be boolean")
        check(isinstance(postcondition,dict) and set(postcondition)<={"mode","timeout","region","target","threshold","settle_seconds","min_changed_ratio"},"Invalid postcondition fields")
        mode=postcondition.get("mode");timeout=postcondition.get("timeout")
        check(mode in ("changed","image") and bounded(timeout,.001,60),"Postcondition mode/timeout invalid")
        check((mode=="changed" and "target" not in postcondition and "threshold" not in postcondition) or
              (mode=="image" and isinstance(postcondition.get("target"),str) and bool(postcondition["target"]) and bounded(postcondition.get("threshold",.98),0,1)),"Postcondition target/threshold invalid")
        settle=postcondition.get("settle_seconds",0)
        check(bounded(settle,0,2) and settle<timeout,"settle_seconds must be 0..2 and below timeout")
        ratio=postcondition.get("min_changed_ratio",.01)
        check(bounded(ratio,0,1) and (mode=="changed" or "min_changed_ratio" not in postcondition),"Invalid min_changed_ratio")
        region=postcondition.get("region")
        if region is not None:check(isinstance(region,list) and len(region)==4 and all(type(i) is int for i in region) and 0<=region[0]<region[2] and 0<=region[1]<region[3],"Invalid postcondition region")
        if pre_state is not None:check(isinstance(pre_state,str) and bool(pre_state),"Invalid pre_state asset")
        path=self._path(transition_id)
        request={"device":device,"session_id":session_id,"target":target,"postcondition":postcondition,"threshold":threshold,
                 "max_ref_age_seconds":max_ref_age_seconds,"return_image":return_image,"pre_state":pre_state}
        if not path.exists() or self.inspect(transition_id)["status"] == "running":
            with self.epochs.request_owner(transition_id, legacy=True, timeout=120) as request_owner:
                if not path.exists():
                    if request_owner is None:
                        raise RecorderError("Transition request is busy", code="DEVICE_BUSY")
                    with self.epochs.device_owner(device, legacy=True) as owner, recorded_asset_snapshots(self.store):
                        if owner is None:
                            raise RecorderError("Transition device is busy", code="DEVICE_BUSY")
                        return self._legacy(request, transition_id, request_owner, owner)
        t=self.inspect(transition_id)
        check(t["request"]==request,"Transition ID already bound to different request")
        if t["status"] == "running":
            t = self._reconcile(t)
        return {**t,"duplicate_request":True}

    def _legacy(self, request, transition_id, request_owner, owner):
        device, session_id = request["device"], request["session_id"]
        target, pre_state, postcondition = request["target"], request["pre_state"], request["postcondition"]
        session=self.rec.status(session_id)
        if session["status"]!="active":
            raise RecorderError("Session is not active",code="SESSION_INACTIVE")
        if session["device_id"]!=device:
            raise RecorderError("Operation device differs from session",code="SESSION_SCOPE_MISMATCH")
        for name in (target,pre_state,postcondition.get("target")):
            if name:
                a,data,_=self.assets.snapshot(name)
                check(a.device_id in (None,device),"Asset device mismatch")
                self.assets.decode(data,name)
        t={"transition_id":transition_id,"request":request,"status":"running","action_outcome":"not_attempted",
           "events":{},"last_frame_id":None,"last_observed_frame_id":None,"pre_frame_id":None,
           "post_frame_id":None,"observation_phase":"none","last_capture_timestamp":None,
           "match_count":None,"target_score":None,"wait":None,
           "artifact":None,"semantic_verification":"UNKNOWN","started_at":time.time(),"finished_at":None,"reason":None}
        self._save(t)
        self.epochs.admit(request_owner, Claim(
            transition_id, "legacy_transition", request, {"action_outcome": "not_attempted"}, device=device,
        ))

        def finish(status, reason=None):
            receipt = self._finish(t, status, reason)
            self.epochs.record(request_owner, transition_id,
                               {"action_outcome": receipt["action_outcome"]}, terminal=True)
            return receipt

        return self._run(
            t, owner, {}, lambda: self._save(t), finish,
            ActionIntent(request_owner, transition_id, "click", lambda receipt, epoch: receipt),
        )

    def invoke_scoped(self, request):
        try:
            req = _scoped_request(request)
            result = self._execute_scoped(req)
            return {"ok": True, "result": result}, 0 if result["status"] in ("completed", "in_progress") else 3
        except Exception as exc:
            reason, code = _failure(exc)
            return {"ok": False, "error": reason}, code

    def _execute_scoped(self, req):
        kind = "scoped_transition"
        tid, device, sid = req["transition_id"], req["device"], req["session_id"]
        duplicate = self.epochs.duplicate(tid, kind, req)
        if duplicate is not None:
            return dict(self.epochs.inspect(tid, self._reconcile_scoped), duplicate_request=True)
        with self.epochs.request_owner(tid) as request_owner:
            if request_owner is None:
                duplicate = self.epochs.duplicate(tid, kind, req)
                if duplicate is not None:
                    return duplicate
                raise OperationError("DEVICE_BUSY", "Transition request is being admitted", retryable=True)
            with self.epochs.device_owner(device) as owner, ExitStack() as stack:
                if owner is None:
                    raise OperationError("DEVICE_BUSY", "Device is busy", retryable=True)
                DiscoveryService(self.obs).require_online(device)
                session = self.rec.status(sid)
                if session["device_id"] != device:
                    raise OperationError("SCOPE_MISMATCH", "Session belongs to another device")
                if session["status"] != "active":
                    raise OperationError("PRECONDITION_FAILED", "Session is not active")
                target = req["target_asset_revision_id"]
                pre_state = req["pre_state_asset_revision_id"]
                postcondition = dict(req["postcondition"])
                post_asset = postcondition.pop("asset_revision_id", None)
                if post_asset:
                    postcondition["target"] = post_asset
                revisions = AssetRevisionStore(self.store.store_dir, frame_store=self.store)
                pins = {
                    key: stack.enter_context(revisions.pin(key, device=device, session_id=sid))
                    for key in dict.fromkeys((target, pre_state, post_asset)) if key is not None
                }
                request = {key: value for key, value in req.items() if key != "return_image"}
                initial = {
                    "kind": kind, "id": tid, "device": device, "request": request,
                    "status": "in_progress", "action_outcome": "not_attempted",
                    "completed_steps": 0, "last_frame_id": None, "last_confirmed_state": None,
                    "observation_phase": "none", "reason": None, "created_at": time.time(),
                    "finished_at": None, "duplicate_request": False, "steps": [], "action_receipt": None,
                }
                duplicate = self.epochs.admit(request_owner, Claim(tid, kind, req, initial, device=device))
                if duplicate is not None:
                    return duplicate
                local_request = dict(req, target=target, pre_state=pre_state, postcondition=postcondition)
                t = {"transition_id": tid, "request": local_request, "events": {}, "action_outcome": "not_attempted",
                     "last_frame_id": None, "observation_phase": "none", "semantic_verification": "UNKNOWN"}

                def save():
                    current = self.epochs.inspect(tid)
                    self.epochs.record(request_owner, tid, self._project_scoped(current, t))

                def finish(status, reason=None):
                    current = self.epochs.inspect(tid)
                    if reason:
                        reason = _scoped_reason(reason, t["action_outcome"])
                    receipt = self._project_scoped(current, t, "completed" if status == "observed" else status, reason)
                    self.epochs.record(request_owner, tid, receipt, terminal=True)
                    return receipt

                def mark_pending(receipt, epoch):
                    step = dict(receipt["steps"][0], status="action_pending", action_epoch=epoch)
                    return dict(receipt, steps=[step])

                return self._run(t, owner, pins, save, finish,
                                 ActionIntent(request_owner, tid, "click", mark_pending))

    @staticmethod
    def _raw_action(payload):
        return {k: v for k, v in payload.items() if k not in ("ok", "event_id", "session_id", "sequence")}

    def _step(self, t, match, revision_id, digest):
        rid = match["ref_id"]
        device, sid = t["request"]["device"], t["request"]["session_id"]
        ref = self.actions.ref_registry.validate(rid, device_id=device, frame_store=self.store)
        if ref.frame_id != t["pre_frame_id"] or self.epochs.ref_revision(rid) != revision_id:
            raise OperationError("EVIDENCE_CHANGED", "Reference differs from the selected frame or revision")
        stamp = self.epochs.ref_epoch(rid)
        if stamp is None:
            raise OperationError("REF_UNVERSIONED", "Transition match lacks an epoch")
        if (stamp.device, stamp.session_id) != (device, sid):
            raise OperationError("SCOPE_MISMATCH", "Reference belongs to another recording scope")
        return {
            "target": {"ref_id": rid, "device_bbox": list(ref.device_bbox), "score": ref.score,
                       "frame_id": ref.frame_id, "epoch": stamp.epoch,
                       "template_sha256": digest},
            "asset_revision_id": revision_id,
            "captured_at": t["last_capture_timestamp"], "matched_at": ref.created_at,
        }

    @staticmethod
    def _project_scoped(receipt, t, status="in_progress", reason=None):
        step = dict(t.get("step", {}))
        previous_step = receipt["steps"][0] if receipt["steps"] else {}
        if "action_epoch" in previous_step:
            step["action_epoch"] = previous_step["action_epoch"]
        wait = t.get("wait")
        outcome = t["action_outcome"]
        action = step.get("action_receipt")
        verified = bool(wait and wait["verified"] and t.get("post_frame_id"))
        step_status = {"not_attempted": "observing", "unknown": "action_pending",
                       "executed_unverified": "verifying"}[outcome]
        observations = []
        if wait and wait["frame_id"] and t["observation_phase"] == "post_action":
            observations.append({"frame_id": wait["frame_id"], "state": None,
                                 "ambiguous": False, "guards": {"wait": wait}})
        step.update(step_id="click", status="verified" if verified else step_status,
                    **{"from": "pre_action", "to": "post_action"},
                    pre_frame_id=t.get("pre_frame_id"), target=step.get("target"),
                    post_frame_id=t.get("post_frame_id"), post_observations=observations,
                    action_receipt=action, verified=verified,
                    events=t["events"], semantic_verification="UNKNOWN", wait=wait,
                    pre_state_guard=t.get("pre_state_guard"))
        return dict(receipt, steps=[step], action_outcome=outcome, status=status,
                    completed_steps=int(status == "completed"), reason=reason,
                    observation_phase=t["observation_phase"], last_frame_id=t["last_frame_id"],
                    finished_at=None if status == "in_progress" else time.time(), action_receipt=action)

    def _reconcile_scoped(self, owner, receipt):
        step = receipt["steps"][0] if receipt["steps"] else {}
        t = {"request": receipt["request"], "transition_id": receipt["id"],
             "action_outcome": receipt["action_outcome"], "step": dict(step)}
        self._restore_observations(t, pending="action_epoch" in step)
        reason = _reason("ACTION_UNCERTAIN" if t["action_outcome"] == "unknown" else "INTERRUPTED",
                         "Previous transition owner ended")
        return self._project_scoped(receipt, t, "interrupted", reason)

    def _run(self, t, owner, pins, save, finish, intent):
        request = t["request"]
        transition_id = t["transition_id"]
        device, session_id = request["device"], request["session_id"]
        target, pre_state, postcondition = request["target"], request["pre_state"], request["postcondition"]
        threshold, max_ref_age_seconds = request["threshold"], request["max_ref_age_seconds"]
        mode, timeout = postcondition["mode"], postcondition["timeout"]
        region, settle = postcondition.get("region"), postcondition.get("settle_seconds", 0)
        ratio = postcondition.get("min_changed_ratio", .01)

        def name(key):
            return pins[key].revision["name"] if pins else key

        def image(key):
            if pins:
                return self.assets.decode(pins[key].png_bytes, key)
            return self.assets.load_image(key)

        def digest(key):
            if pins:
                return pins[key].revision["png_sha256"]
            return hashlib.sha256(self.assets.snapshot(key)[1]).hexdigest()

        def op(role,operation,inputs,invoke,pinned=None):
            r=self.rec._execute_locked(session_id,operation,{**inputs,"transition_id":transition_id},invoke,pinned_asset=pinned)
            t["events"][role]=r["event_id"]
            if role == "action" and r.get("ok"):
                t["action_outcome"] = "executed_unverified"
                if t.get("step"):
                    t["step"]["action_receipt"] = self._raw_action(r)
            if role != "action" or t["action_outcome"] != "not_attempted":
                self._observe(t, role, r)
            save()
            if not r.get("ok"):
                err=r.get("error") or {}
                raise RecorderError(err.get("message","Primitive failed"),code=err.get("code","TRANSITION_PRIMITIVE_FAILED"))
            return r
        def snap():return {"ok":True,"device":device,**self.obs.snapshot(device, device_owner=owner)}
        try:
            pre=op("pre","snapshot",{"device":device},snap)
            frame=pre["frame"];fid=frame["frame_id"]
            if region:check(region[2]<=frame["width"] and region[3]<=frame["height"],"Postcondition region outside frame")
            if pre_state:
                # Read-only guard match; not an extra action or replacement for recorded find.
                guard=self.matcher.opencv.find_all(self.store.load_image(fid),image(pre_state),
                                                   threshold=threshold,max_results=2,color_mode="gray")
                t["pre_state_guard"]={"asset":pre_state,"asset_sha256":digest(pre_state),
                                      "frame_id":fid,"count":len(guard),"score":guard[0].score if guard else None}
                save()
                if len(guard)!=1:return finish("needs_agent",{"code":"PRECONDITION_FAILED","message":"Pre-state marker not unique"})
            def find_target():
                if not pins:
                    return {"ok": True, **self.matcher.find(
                        fid, target, find_all=True, threshold=threshold, max_results=2, session_id=session_id)}
                with self.store.pin_frames([fid], device_id=device) as (record,):
                    return {"ok": True, **self.matcher.match_frame(
                        record, name(target), image(target), threshold=threshold, max_results=2,
                        session_id=session_id, revision_id=target)}

            find = op("find", "find", {"frame_id": fid, "target": name(target), "all": True,
                      "threshold": threshold, "max_results": 2, "color_mode": "gray"},
                      find_target, pins.get(target))
            t["match_count"]=find["count"]
            if find["count"]!=1:
                return finish("needs_agent",{"code":"TARGET_NOT_FOUND" if find["count"]==0 else "TARGET_AMBIGUOUS",
                      "message":"No matching target" if find["count"]==0 else "Multiple matching targets",
                      "match_count":find["count"]})
            match=find["matches"][0];t["target_score"]=match["score"]
            if not 0<=time.time()-frame["timestamp"]<=max_ref_age_seconds:
                return finish("needs_agent",{"code":"FRAME_STALE","message":"Pre-frame expired"})
            rid=match["ref_id"]
            step = self._step(t, match, target, digest(target)) if pins else None
            if step is not None:
                t["step"] = step
                save()

            def click():
                try:
                    return {"ok": True, **self.actions.click(
                        device, ref_id=rid, max_age_seconds=max_ref_age_seconds, device_owner=owner,
                        session_id=session_id, intent=intent,
                    )}
                finally:
                    current = self.epochs.inspect(transition_id)
                    if current["action_outcome"] == "unknown":
                        t["action_outcome"] = "unknown"
                        self._clear_observation(t, "post_action_unknown")

            op("action", "click", {"device": device, "ref": rid, "max_age_seconds": max_ref_age_seconds},
               click, pins.get(target))
            wi={"device":device,"mode":mode,"timeout":timeout,"region":region,"settle_seconds":settle}
            if mode=="changed":
                wi.update(baseline_frame_id=fid,min_changed_ratio=ratio)
            else:
                wi.update(target=name(postcondition["target"]),threshold=postcondition.get("threshold",.98))
            def invoke():
                started=time.monotonic()
                if settle:time.sleep(settle)
                remaining=timeout-(time.monotonic()-started)
                if remaining<=0:
                    raise WaitFailure(OperationError("WAIT_TIMEOUT","Wait budget exhausted during settle",retryable=True,exit_code=4),
                         {"condition":mode,"verified":False,"device_id":device,"status":"timeout",
                          "captures":0,"frame_id":None,"artifact":None,"last_capture_timestamp":None,
                          "elapsed_seconds":time.monotonic()-started})
                try:
                    if mode=="changed":
                        r=self.waits.wait_changed(device,baseline_frame_id=fid,region=tuple(region) if region else None,
                                                  timeout=remaining,interval=.2,min_changed_ratio=ratio, device_owner=owner)
                    else:
                        r=self.waits.wait_image(device,target_name=wi["target"],region=tuple(region) if region else None,
                                               timeout=remaining,interval=.2,threshold=wi["threshold"], device_owner=owner,
                                               template_image=image(postcondition["target"]) if pins else None)
                except WaitFailure as exc:
                    exc.observation["elapsed_seconds"]=time.monotonic()-started
                    raise
                return {"ok":True,**r,"elapsed_seconds":time.monotonic()-started}
            wait=op("wait","wait",wi,invoke,pins.get(postcondition.get("target")))
            if not wait.get("verified"):return finish("needs_agent",{"code":"WAIT_UNVERIFIED","message":"Wait did not verify"})
            op("post","snapshot",{"device":device},snap)
            return finish("observed")
        except Exception as exc:
            return finish("needs_agent",{"code":getattr(exc,"code","TRANSITION_ERROR"),"message":str(exc)})


def transition_tool_definitions():
    s={"type":"string"};n={"type":"number"}
    post={"type":"object","properties":{"mode":{"enum":["changed","image"],"type":"string"},"timeout":{"type":"number","exclusiveMinimum":0,"maximum":60},"region":{"type":"array","items":{"type":"integer"},"minItems":4,"maxItems":4},"target":s,"threshold":{"type":"number","minimum":0,"maximum":1},"settle_seconds":{"type":"number","minimum":0,"maximum":2,"default":0},"min_changed_ratio":{"type":"number","minimum":0,"maximum":1,"default":.01}},"required":["mode","timeout"],"additionalProperties":False}
    props={"device":s,"session_id":s,"transition_id":s,"target":s,"postcondition":post,"threshold":{"type":"number","minimum":.8,"maximum":1,"default":.98},"max_ref_age_seconds":{"type":"number","exclusiveMinimum":0,"maximum":60,"default":15},"return_image":{"type":"boolean","default":True},"pre_state":s}
    return [{"name":"vision_transition","description":"Record one fresh unique click and observed post-frame; annotate semantic result separately.","inputSchema":{"type":"object","properties":props,"required":["device","session_id","transition_id","target","postcondition"],"additionalProperties":False}},
            {"name":"vision_transition_inspect","description":"Read persisted transition receipt without action.","inputSchema":{"type":"object","properties":{"transition_id":s},"required":["transition_id"],"additionalProperties":False}}]
