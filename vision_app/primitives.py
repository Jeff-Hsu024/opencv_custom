"""Scoped matching and durable, single-dispatch reference clicks."""

import math
import re
import sqlite3
import time
from contextlib import nullcontext

from vision_app.actions import ActionService
from vision_app.asset_revisions import AssetRevisionStore, _DEVICE, _FRAME, _SESSION
from vision_app.assets import MatchingService, RefNotFoundError, StaleRefError
from vision_app.coordinator import Claim, ClaimError
from vision_app.discovery import DiscoveryService
from vision_app.epochs import ActionIntent, DeviceEpochs
from vision_app.observation import OperationError
from vision_app.recorder import Recorder, RecorderError, workspace_lock
from vision_app.store import DeviceMismatchError, FrameNotFoundError, StoreError


def _string(pattern):
    return {"type": "string", "pattern": pattern}


_SCOPE = {
    "device": _string(_DEVICE),
    "session_id": {"anyOf": [_string(_SESSION), {"type": "null"}], "default": None},
}
SCHEMAS = {
    "scoped_find": {
        "type": "object", "additionalProperties": False,
        "required": ["device", "frame_id", "asset_revision_id"],
        "properties": {
            **_SCOPE, "frame_id": _string(_FRAME),
            "asset_revision_id": _string(r"^ar_[0-9a-f]{64}$(?![\s\S])"),
            "threshold": {"type": "number", "minimum": 0.8, "maximum": 1, "default": 0.98},
            "max_results": {"type": "integer", "minimum": 1, "maximum": 100, "default": 10},
        },
    },
    "guarded_click": {
        "type": "object", "additionalProperties": False,
        "required": ["device", "action_id", "ref_id"],
        "properties": {
            **_SCOPE, "action_id": _string(r"^act_[0-9a-f]{32}$(?![\s\S])"),
            "ref_id": _string(r"^ref_[A-Za-z0-9_-]{1,64}$(?![\s\S])"),
            "max_ref_age_seconds": {
                "type": "number", "exclusiveMinimum": 0, "maximum": 60, "default": 15,
            },
        },
    },
}


def _validate(operation, request):
    schema = SCHEMAS[operation]
    props = schema["properties"]
    if (type(request) is not dict or set(request) - props.keys()
            or set(schema["required"]) - request.keys()):
        raise OperationError("INVALID_ARGUMENT", "Invalid request fields", exit_code=2)
    normalized = {}
    for key, rule in props.items():
        value = request.get(key, rule.get("default"))
        if key == "session_id" and value is None:
            normalized[key] = None
            continue
        if key == "session_id":
            rule = rule["anyOf"][0]
        if rule["type"] == "string":
            valid = isinstance(value, str) and re.fullmatch(rule["pattern"], value)
        else:
            valid = (type(value) in (float, int) and value <= rule["maximum"]
                     and value >= rule.get("minimum", 0) and math.isfinite(value))
            if "exclusiveMinimum" in rule:
                valid = valid and value > rule["exclusiveMinimum"]
            if rule["type"] == "integer" and valid:
                valid = int(value) == value
                value = int(value)
        if not valid:
            raise OperationError("INVALID_ARGUMENT", f"Invalid {key}", exit_code=2)
        normalized[key] = value
    return normalized


def _reason(code, message, retryable=False):
    return {"code": code, "message": message, "details": {}, "retryable": retryable}


def _failure(exc):
    if isinstance(exc, OperationError):
        if exc.code == "PLATFORM_INIT_FAILED":
            return _reason("INTERNAL_ERROR", "Device platform initialization failed"), 3
        return _reason(exc.code, exc.message, exc.retryable), exc.exit_code
    if isinstance(exc, ClaimError):
        return _reason(exc.code, str(exc)), 3
    if isinstance(exc, RecorderError):
        code = {"SESSION_NOT_FOUND": "NOT_FOUND", "SESSION_INACTIVE": "PRECONDITION_FAILED",
                "SESSION_SCOPE_MISMATCH": "SCOPE_MISMATCH"}.get(exc.code, "STORE_ERROR")
        return _reason(code, str(exc)), 3
    if isinstance(exc, DeviceMismatchError):
        return _reason("SCOPE_MISMATCH", str(exc)), 3
    if isinstance(exc, (FrameNotFoundError, RefNotFoundError)):
        return _reason("NOT_FOUND", str(exc)), 3
    if isinstance(exc, StaleRefError):
        return _reason("FRAME_STALE", str(exc)), 3
    if isinstance(exc, (StoreError, sqlite3.Error, OSError)):
        return _reason("STORE_ERROR", "Primitive evidence store unavailable"), 3
    return _reason("INTERNAL_ERROR", "Internal primitive operation error"), 3


class PrimitiveService:
    def __init__(self, observation, *, matcher=None, actions=None):
        self.store = observation.store
        self.discovery = DiscoveryService(observation)
        self.matcher = matcher or MatchingService(store=self.store)
        self.actions = actions or ActionService(self.store, platform_factory=observation._platform_factory)
        self.epochs = DeviceEpochs(self.store)

    def invoke(self, operation, request):
        try:
            req = _validate(operation, request)
            with workspace_lock(self.store):
                result = self.scoped_find(req) if operation == "scoped_find" else self.guarded_click(req)
            return {"ok": True, "result": result}, (
                0 if result.get("status") in (None, "completed", "in_progress") else 3
            )
        except Exception as exc:
            reason, exit_code = _failure(exc)
            return {"ok": False, "error": reason}, exit_code

    def _record(self, req, operation, inputs, pinned_asset, invoke):
        sid = req["session_id"]
        if sid is None:
            return invoke()
        def normalized():
            try:
                return invoke()
            except Exception as exc:
                error, _ = _failure(exc)
                return {"ok": False, "error": error}

        result = Recorder(self.store)._execute_locked(
            sid, operation, inputs, normalized, pinned_asset=pinned_asset,
        )
        if not result["ok"]:
            error = result["error"]
            if error["code"].startswith("SESSION_"):
                raise RecorderError(error["message"], code=error["code"])
            raise OperationError(error["code"], error["message"])
        return result

    def scoped_find(self, req):
        device, fid, revision_id = req["device"], req["frame_id"], req["asset_revision_id"]
        revisions = AssetRevisionStore(self.store.store_dir, frame_store=self.store)
        with self.store.pin_frames([fid], device_id=device) as (frame,):
            epoch = self.epochs.frame_epoch(fid, device)
            if epoch is None:
                raise OperationError("REF_UNVERSIONED", "Scoped find requires a versioned frame")
            with revisions.pin(revision_id, device=device, session_id=req["session_id"]) as pinned:
                template = self.matcher.assets.decode(pinned.png_bytes, revision_id)
                name = pinned.revision["name"]
                def find():
                    return {"ok": True, **self.matcher.match_frame(
                        frame, name, template, threshold=req["threshold"], max_results=req["max_results"],
                        session_id=req["session_id"], revision_id=revision_id,
                    )}
                result = self._record(req, "find", {**req, "target": name, "all": True}, pinned, find)
        return {"device": device, "frame_id": fid, "asset_revision_id": revision_id,
                "match_count": result["count"], "matches": [
                    {**{k: ref[k] for k in ("ref_id", "device_bbox", "score")}, "epoch": epoch}
                    for ref in result["matches"]
                ]}

    @staticmethod
    def _interrupted(owner, receipt):
        unknown = receipt["action_outcome"] == "unknown"
        reason = (_reason("ACTION_UNCERTAIN", "Click dispatch may have occurred") if unknown
                  else _reason("INTERRUPTED", "Click interrupted before dispatch"))
        return dict(receipt, status="interrupted", reason=reason, finished_at=time.time())

    def guarded_click(self, req):
        kind = "guarded_click"
        action_id, device = req["action_id"], req["device"]
        duplicate = self.epochs.duplicate(action_id, kind, req)
        if duplicate is not None:
            return dict(self.epochs.inspect(action_id, self._interrupted), duplicate_request=True)
        with self.epochs.request_owner(action_id) as request_owner:
            if request_owner is None:
                duplicate = self.epochs.duplicate(action_id, kind, req)
                if duplicate is not None:
                    return duplicate
                raise OperationError("DEVICE_BUSY", "Click request is being admitted", retryable=True)
            with self.epochs.device_owner(device) as owner:
                if owner is None:
                    raise OperationError("DEVICE_BUSY", "Device is busy", retryable=True)
                self.discovery.require_online(device)
                initial = {
                    "kind": kind, "id": action_id, "device": device, "request": req,
                    "status": "in_progress", "action_outcome": "not_attempted",
                    "completed_steps": 0, "last_frame_id": None, "last_confirmed_state": None,
                    "observation_phase": "none", "reason": None, "created_at": time.time(),
                    "finished_at": None, "duplicate_request": False, "steps": [], "action_receipt": None,
                }
                duplicate = self.epochs.admit(request_owner, Claim(action_id, kind, req, initial, device=device))
                if duplicate is not None:
                    return duplicate
                return self._dispatch(req, request_owner, owner, initial)

    def _dispatch(self, req, request_owner, owner, initial):
        device, rid, action_id = req["device"], req["ref_id"], req["action_id"]
        age = req["max_ref_age_seconds"]

        try:
            ref = self.actions.ref_registry.validate(rid, device_id=device, frame_store=self.store)
            epoch = self.epochs.guard_ref(owner, rid, device, session_id=req["session_id"])
            revision_id = self.epochs.ref_revision(rid)
            frame = self.store.get_frame(ref.frame_id, device_id=device)
            initial = dict(initial, last_frame_id=frame.frame_id, observation_phase="pre_action")
            self.epochs.record(request_owner, action_id, initial)
            if not 0 <= time.time() - frame.timestamp <= age:
                raise OperationError("FRAME_STALE", "Reference source frame is too old")
            pin = (AssetRevisionStore(self.store.store_dir, frame_store=self.store).pin(
                revision_id, device=device, session_id=req["session_id"])
                   if revision_id else nullcontext())
            with pin as pinned:
                step = {
                    "step_id": "click", "from": None, "to": None, "status": "action_pending",
                    "pre_frame_id": frame.frame_id, "post_frame_id": None, "post_observations": [],
                    "target": {"ref_id": rid, "device_bbox": list(ref.device_bbox), "epoch": epoch,
                               "asset_revision_id": revision_id, "score": ref.score,
                               "template_sha256": pinned.revision["png_sha256"] if pinned else None},
                    "captured_at": frame.timestamp, "matched_at": ref.created_at,
                    "verified": False, "action_receipt": None,
                }

                def pending(receipt, action_epoch):
                    return dict(receipt, steps=[dict(step, action_epoch=action_epoch)])

                def click():
                    return {"ok": True, **self.actions.click(
                        device, ref_id=rid, max_age_seconds=age, session_id=req["session_id"],
                        device_owner=owner, intent=ActionIntent(request_owner, action_id, "click", pending),
                    )}

                result = self._record(req, "click", {**req, "ref": rid, "max_age_seconds": age}, pinned, click)
            raw = {k: v for k, v in result.items() if k not in ("ok", "event_id", "session_id", "sequence")}
            receipt = self.epochs.inspect(action_id)
            completed_step = dict(receipt["steps"][0], status="executed_unverified", action_receipt=raw)
            final = dict(receipt, status="completed", action_outcome="executed_unverified",
                         completed_steps=1, action_receipt=raw, steps=[completed_step])
        except Exception as exc:
            receipt = self.epochs.inspect(action_id)
            unknown = receipt["action_outcome"] == "unknown"
            reason, _ = _failure(exc)
            if unknown:
                reason = _reason("ACTION_UNCERTAIN", "Click dispatch outcome is unknown")
            final = dict(receipt, status="needs_agent" if unknown else "rejected",
                         reason=dict(reason, retryable=False))
        final["finished_at"] = time.time()
        self.epochs.record(request_owner, action_id, final, terminal=True)
        return final
