"""FA-01: confirmed captured drift cannot be hidden by transient focus ambiguity.

All devices are injected fixtures. The snapshot is actually persisted before
the second profile probe can fail; no synthetic receipt is used.
"""
import pytest

from test_portable_admission import admitted_devices
from test_portable_qualification import devices, validate_response
from test_portable_core import published
from test_runtime import prepared, PROFILE, RID
from test_workflow import recorded
from vision_app.runtime import RuntimeFault


def inject_capture(monkeypatch, rt, target, device, *, drift, focus, post):
    original = target.snapshot
    probe = rt.probe
    save = rt.store.save_frame
    flags = {"captured": False, "pending": False, "raised": 0, "frame_id": None}

    def snapshot():
        im = original()
        if not flags["captured"] and (not post or target.state == 1):
            flags["captured"] = True
            flags["pending"] = bool(focus)
            if drift == "width":
                return im[:, :-8, :]
            if drift == "height":
                return im[:-10, :, :]
        return im

    def save_frame(image, serial, **kwargs):
        first = serial == device and flags["captured"] and flags["frame_id"] is None
        if first and drift == "rotation":
            kwargs["rotation"] = 2
        frame = save(image, serial, **kwargs)
        if first:
            flags["frame_id"] = frame.frame_id
        return frame

    def profile(serial, package):
        if serial == device and flags["pending"]:
            flags["pending"] = False
            flags["raised"] += 1
            raise RuntimeFault("PROFILE_UNKNOWN", f"Cannot establish unique {focus} package")
        return probe(serial, package)

    monkeypatch.setattr(target, "snapshot", snapshot)
    monkeypatch.setattr(rt.store, "save_frame", save_frame)
    monkeypatch.setattr(rt, "probe", profile)
    return flags


@pytest.mark.parametrize("drift,focus", [
    ("width", None), ("width", "resumed"),
    ("height", "focused"), ("rotation", "resumed"),
])
def test_admitted_drift_precedes_second_probe(admitted_devices, monkeypatch, drift, focus):
    svc, record, source, target, *_ = admitted_devices
    pid = record["portable_id"]
    flags = inject_capture(monkeypatch, svc.rt, target, "device-B",
                           drift=drift, focus=focus, post=True)
    before = len(target.actions)
    a_before = svc.slots.inspect(pid, "dev")
    epoch = svc.ledger.current("device-B")
    tid = "ptask_" + "e"*32
    result = svc.admission.execute("test", 2, "device-B", tid)
    assert result["status"] == "needs_agent"
    assert result["reason"]["code"] == "GEOMETRY_MISMATCH"
    assert result["action_outcome"] == "executed_unverified"
    assert result["completed_steps"] == 0
    assert result["last_frame_id"] == flags["frame_id"] == result["reason"]["details"]["frame_id"]
    frame = svc.store.get_frame(flags["frame_id"], device_id="device-B")
    assert frame.protected and flags["raised"] == 0
    if drift == "width":
        assert frame.width == 132
    elif drift == "height":
        assert frame.height == 90
    else:
        assert frame.rotation == 2
    slot = svc.slots.inspect(pid, "device-B")
    assert (slot["status"], slot["slot_generation"]) == ("invalidated", 2)
    assert slot["reason"]["code"] == "GEOMETRY_MISMATCH"
    assert svc.slots.inspect(pid, "dev") == a_before
    assert svc.admission.execute("test", 2, "device-B", tid) == {**result, "duplicate_request": True}
    assert svc.slots.inspect(pid, "device-B") == slot
    assert len(target.actions) == before + 1 and svc.ledger.current("device-B") == epoch + 1
    validate_response("portable_execute", result)


@pytest.mark.parametrize("focus", ["focused", "resumed"])
def test_valid_post_capture_second_probe_can_recover(admitted_devices, monkeypatch, focus):
    svc, record, source, target, *_ = admitted_devices
    pid = record["portable_id"]
    flags = inject_capture(monkeypatch, svc.rt, target, "device-B",
                           drift=None, focus=focus, post=True)
    before = len(target.actions)
    slot = svc.slots.inspect(pid, "device-B")
    tid = "ptask_" + "d"*32
    result = svc.admission.execute("test", 2, "device-B", tid)
    assert flags["raised"] == 1 and flags["frame_id"] != result["last_frame_id"]
    assert svc.store.get_frame(flags["frame_id"], device_id="device-B").protected
    assert result["status"] == "completed" and result["completed_steps"] == 1
    assert svc.slots.inspect(pid, "device-B") == slot
    assert svc.admission.execute("test", 2, "device-B", tid) == {**result, "duplicate_request": True}
    assert len(target.actions) == before + 1


@pytest.mark.parametrize("drift", ["width", "rotation", None])
def test_preflight_drift_or_unknown_is_read_only(admitted_devices, monkeypatch, drift):
    svc, record, source, target, *_ = admitted_devices
    pid = record["portable_id"]
    flags = inject_capture(monkeypatch, svc.rt, target, "device-B",
                           drift=drift, focus="focused", post=False)
    before = len(target.actions)
    epoch = svc.ledger.current("device-B")
    a_before = svc.slots.inspect(pid, "dev")
    receipt = svc.preflight(pid, "device-B")
    assert receipt["status"] == "fail"
    assert receipt["frame_id"] == flags["frame_id"]
    assert svc.store.get_frame(flags["frame_id"], device_id="device-B").protected
    slot = svc.slots.inspect(pid, "device-B")
    if drift:
        assert receipt["reason"]["code"] == "GEOMETRY_MISMATCH"
        assert (slot["status"], slot["slot_generation"]) == ("invalidated", 2)
        assert flags["raised"] == 0
    else:
        assert receipt["reason"]["code"] == "DEVICE_UNAVAILABLE"
        assert (slot["status"], slot["slot_generation"]) == ("active", 1)
        assert flags["raised"] == 1
    assert svc.slots.inspect(pid, "dev") == a_before
    assert svc.preflight_inspect(receipt["preflight_id"]) == receipt
    assert len(target.actions) == before and svc.ledger.current("device-B") == epoch
    validate_response("portable_preflight", receipt)


def test_legacy_post_capture_geometry_precedes_focus(prepared, monkeypatch):
    rt, binding, server, target, *_ = prepared
    flags = inject_capture(monkeypatch, rt, target, "dev",
                           drift="height", focus="resumed", post=True)
    before = len(target.actions)
    receipt = rt.run(binding["binding_id"], RID)
    assert receipt["status"] == "needs_agent"
    assert receipt["reason"]["code"] == "GEOMETRY_MISMATCH"
    assert receipt["action_outcome"] == "executed_unverified"
    assert receipt["last_frame_id"] == flags["frame_id"]
    assert server.store.get_frame(flags["frame_id"], device_id="dev").protected
    assert flags["raised"] == 0
    assert rt.run(binding["binding_id"], RID)["duplicate_request"]
    assert len(target.actions) == before + 1
