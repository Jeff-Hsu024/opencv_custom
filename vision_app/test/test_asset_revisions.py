"""C03: immutable scoped asset revisions, real spawned processes, no devices.

Devices are opaque fixture serials in isolated temporary stores. No device
input, discovery, official Store, bundle or registration evidence is touched.
"""
import hashlib
import json
import multiprocessing as mp
import os
import sqlite3
import threading
from pathlib import Path

import cv2
import numpy as np
import pytest
from jsonschema import Draft202012Validator

from service.core.opencv.mat_utility import MatUtility
from vision_app import asset_revisions as module
from vision_app.asset_revisions import (
    ASSET_REVISION_REGISTER_SCHEMA,
    ASSET_REVISION_RESOLVE_SCHEMA,
    AssetRevisionStore,
    revision_id_for,
    validate_request,
)
from vision_app.assets import AssetRegistry
from vision_app.cli import run_cli
from vision_app.mcp_server import VisionMcpServer, _tool_definitions
from vision_app.metadata import metadata_transaction
from vision_app.observation import OperationError
from vision_app.recorder import Recorder, RecorderError
from vision_app.store import FrameStore, StoreError

CTX = mp.get_context("spawn")
PLAN = Path(__file__).resolve().parents[2] / "specs/agent-vision-phase9"
A, B = "devA", "devB"
REGION = [2, 3, 10, 9]


def image(seed):
    rng = np.random.default_rng(seed)
    return rng.integers(0, 255, (16, 20, 3), dtype=np.uint8)


def frames(root):
    store = FrameStore(root, max_frames=1000)
    for fid, dev, seed in (("frm_a1", A, 1), ("frm_a2", A, 2), ("frm_b1", B, 3), ("frm_b2", B, 4)):
        store.save_frame(image(seed), dev, frame_id=fid, protected=True)
    return store


def crop_png(seed, region=REGION):
    x1, y1, x2, y2 = region
    return MatUtility.encode_png(image(seed)[y1:y2, x1:x2].copy())


def sha(data):
    return hashlib.sha256(data).hexdigest()


def code_of(fn):
    with pytest.raises(OperationError) as exc:
        fn()
    return exc.value.code


def response_validator(op):
    schemas = json.loads((PLAN / "c00/RESPONSE_SCHEMAS.json").read_text(encoding="utf-8"))
    return Draft202012Validator(schemas.get("operations", schemas)[op])


def rows(root, table):
    with sqlite3.connect(Path(root) / "asset_revisions.sqlite") as db:
        return db.execute(f"SELECT * FROM {table}").fetchall()


# ---------------------------------------------------------------- contract
def test_frozen_schemas_examples_and_edge_parity():
    frozen = json.loads((PLAN / "CONTRACT_SCHEMAS.json").read_text(encoding="utf-8"))["operations"]
    assert ASSET_REVISION_REGISTER_SCHEMA == frozen["asset_revision_register"]
    assert ASSET_REVISION_RESOLVE_SCHEMA == frozen["asset_revision_resolve"]
    examples = json.loads((PLAN / "c00/REQUEST_EXAMPLES.json").read_text(encoding="utf-8"))
    examples = examples if isinstance(examples, list) else examples["examples"]
    extra = [{"device": A, "name": "g", "frame_id": "frm_x", "region": r} for r in
             ([1, 2, 3, 4], [1.0, 2, 3, 4], [1.5, 2, 3, 4], [True, 2, 3, 4], [-1, 2, 3, 4],
              [1, 2, 3], [1, 2, 3, 4, 5], "1,2,3,4", None)]
    extra += [{"device": A, "name": n, "frame_id": "frm_x", "session_id": s} for n, s in
              (("a.b-c_d", None), (".x", None), ("a", "ses_x"), ("a", "ses_"), ("a", "ses_x\n"),
               ("a", 5), ("x" * 64, None), ("x" * 65, None))]
    cases = [(e["op"], e["request"]) for e in examples if e["op"].startswith("asset_revision")]
    cases += [("asset_revision_register", r) for r in extra]
    assert len(cases) > 40
    for op, request in cases:
        expected = Draft202012Validator(frozen[op]).is_valid(request)
        try:
            validate_request(op, request)
            actual = True
        except OperationError as exc:
            assert exc.code == "INVALID_ARGUMENT" and exc.exit_code == 2
            actual = False
        assert actual == expected, (op, request)


def test_tools_are_additive_with_frozen_schemas():
    tools = {t["name"]: t for t in _tool_definitions()}
    assert tools["vision_asset_revision_register"]["inputSchema"] == ASSET_REVISION_REGISTER_SCHEMA
    assert tools["vision_asset_revision_resolve"]["inputSchema"] == ASSET_REVISION_RESOLVE_SCHEMA
    baseline = json.loads((PLAN / "c00/LEGACY_BASELINE.json").read_text(encoding="utf-8"))
    assert all(tools[t["name"]] == t for t in baseline["tools"]) and len(baseline["tools"]) == 61


# ------------------------------------------------------- scoped A/B (UC15)
def test_same_label_ab_distinct_immutable_revisions(tmp_path):
    store = frames(tmp_path)
    rec = Recorder(store)
    sa, sb = rec.start("a", "g", A)["session_id"], rec.start("b", "g", B)["session_id"]
    revs = AssetRevisionStore(tmp_path, frame_store=store)
    out = {}
    for dev, fid, sid, seed in ((A, "frm_a1", None, 1), (B, "frm_b1", None, 3),
                                (A, "frm_a2", sa, 2), (B, "frm_b2", sb, 4)):
        res = revs.register({"device": dev, "session_id": sid, "name": "settings-gear",
                             "frame_id": fid, "region": REGION})
        assert response_validator("asset_revision_register").is_valid({"ok": True, "result": res})
        png = crop_png(seed)
        assert (res["device"], res["session_id"], res["source_frame_id"]) == (dev, sid, fid)
        assert (res["png_sha256"], res["width"], res["height"], res["region"]) == (sha(png), 8, 6, REGION)
        frame_sha = sha((tmp_path / "frames" / f"{fid}.png").read_bytes())
        content = {**{k: res[k] for k in res if k not in ("asset_revision_id", "details")},
                   "source_frame_sha256": frame_sha}
        assert res["asset_revision_id"] == revision_id_for(content)
        assert revs.blob_path(res["png_sha256"]).read_bytes() == png
        out[(dev, sid)] = res
    assert len({r["asset_revision_id"] for r in out.values()}) == 4
    for (dev, sid), res in out.items():
        got = revs.resolve({"device": dev, "session_id": sid, "name": "settings-gear"})
        assert got == res
        assert response_validator("asset_revision_resolve").is_valid({"ok": True, "result": got})
    # Exact scope only: no session -> device-wide fallback, no foreign device.
    rec.transition(sa, "stop")
    assert code_of(lambda: revs.resolve({"device": A, "name": "other"})) == "NOT_FOUND"
    sc = rec.start("c", "g", A)["session_id"]
    assert code_of(lambda: revs.resolve({"device": A, "session_id": sc, "name": "settings-gear"})) == "NOT_FOUND"
    # Legacy global alias is never a scoped lookup.
    assert not AssetRegistry(tmp_path).list_assets()


def test_wrong_scope_and_invalid_rejected_without_publication(tmp_path):
    store = frames(tmp_path)
    rec = Recorder(store)
    sa, sb = rec.start("a", "g", A)["session_id"], rec.start("b", "g", B)["session_id"]
    revs = AssetRevisionStore(tmp_path, frame_store=store)
    base = {"device": A, "name": "gear", "frame_id": "frm_a1"}
    assert code_of(lambda: revs.register({**base, "frame_id": "frm_b1"})) == "SCOPE_MISMATCH"
    assert code_of(lambda: revs.register({**base, "session_id": sb})) == "SCOPE_MISMATCH"
    assert code_of(lambda: revs.register({**base, "session_id": "ses_unknown"})) == "NOT_FOUND"
    assert code_of(lambda: revs.register({**base, "frame_id": "frm_missing"})) == "NOT_FOUND"
    assert code_of(lambda: revs.register({**base, "region": [0, 0, 999, 5]})) == "INVALID_ARGUMENT"
    assert code_of(lambda: revs.register({**base, "region": [5, 5, 5, 9]})) == "INVALID_ARGUMENT"
    assert code_of(lambda: revs.resolve({"device": A, "session_id": sb, "name": "gear"})) == "SCOPE_MISMATCH"
    rec.transition(sa, "stop")
    assert code_of(lambda: revs.register({**base, "session_id": sa})) == "PRECONDITION_FAILED"
    assert rows(tmp_path, "scoped_asset_alias") == [] and rows(tmp_path, "asset_revision") == []
    sa2 = rec.start("a2", "g", A)["session_id"]
    rid = revs.register({**base, "session_id": sa2})["asset_revision_id"]
    wide = revs.register(base)["asset_revision_id"]
    for dev, sid in ((B, None), (B, sa2), (A, None), (A, sa)):
        assert code_of(lambda: revs.pin(rid, device=dev, session_id=sid).__enter__()) == "SCOPE_MISMATCH"
    with revs.pin(rid, device=A, session_id=sa2) as pinned:
        assert pinned.asset_revision_id == rid and sha(pinned.png_bytes) == pinned.revision["png_sha256"]
    for sid in (None, sa2, sa):  # device-wide revision: any session of the same device
        with revs.pin(wide, device=A, session_id=sid):
            pass
    assert code_of(lambda: revs.pin(wide, device=B).__enter__()) == "SCOPE_MISMATCH"
    assert code_of(lambda: revs.pin(wide, device=A, session_id=sb).__enter__()) == "SCOPE_MISMATCH"
    assert code_of(lambda: revs.pin("ar_" + "0" * 64, device=A).__enter__()) == "NOT_FOUND"
    assert revs.active_pins() == set()


def test_cli_mcp_share_service_and_store(tmp_path, capsys):
    store = frames(tmp_path / "store")
    server = VisionMcpServer(tmp_path / "store")
    req = tmp_path / "r.json"
    req.write_text(json.dumps({"device": A, "name": "gear", "frame_id": "frm_a1"}), encoding="utf-8")
    argv = ["--store-dir", str(tmp_path / "store"), "phase9"]
    assert run_cli(argv + ["asset-revision-register", "--request", str(req)]) == 0
    cli = json.loads(capsys.readouterr().out)
    mcp = server.call_tool("vision_asset_revision_resolve", {"device": A, "name": "gear"})
    assert mcp["isError"] is False and json.loads(mcp["content"][0]["text"]) == cli
    again = server.call_tool("vision_asset_revision_register", {"device": A, "name": "gear", "frame_id": "frm_a1"})
    assert json.loads(again["content"][0]["text"]) == cli  # same content, same immutable ID
    req.write_text(json.dumps({"device": B, "name": "gear"}), encoding="utf-8")
    assert run_cli(argv + ["asset-revision-resolve", "--request", str(req)]) == 3
    assert json.loads(capsys.readouterr().out)["error"] == {
        "code": "NOT_FOUND", "message": "No asset revision for this exact scope and name",
        "details": {}, "retryable": False}
    bad = server.call_tool("vision_asset_revision_resolve", {"device": "adb", "name": "gear"})
    assert bad["isError"] is True and json.loads(bad["content"][0]["text"])["error"]["code"] == "INVALID_ARGUMENT"
    req.write_text("{", encoding="utf-8")
    assert run_cli(argv + ["asset-revision-resolve", "--request", str(req)]) == 2
    capsys.readouterr()
    for payload in (cli, json.loads(bad["content"][0]["text"])):
        op = "asset_revision_register" if payload["ok"] else "asset_revision_resolve"
        assert response_validator(op).is_valid(payload)
    assert store.list_frames()  # same store observed by both adapters


def test_reregister_moves_alias_old_revision_immutable_and_conflict(tmp_path):
    store = frames(tmp_path)
    revs = AssetRevisionStore(tmp_path, frame_store=store)
    first = revs.register({"device": A, "name": "gear", "frame_id": "frm_a1"})
    second = revs.register({"device": A, "name": "gear", "frame_id": "frm_a2"})
    assert revs.resolve({"device": A, "name": "gear"}) == second != first
    with revs.pin(first["asset_revision_id"], device=A) as old:
        assert old.png_bytes == MatUtility.encode_png(image(1))
    assert [r[4] for r in rows(tmp_path, "scoped_asset_alias")] == [2]
    with sqlite3.connect(tmp_path / "asset_revisions.sqlite") as db:
        db.execute("UPDATE asset_revision SET immutable_json='{}' WHERE id=?", (second["asset_revision_id"],))
    assert code_of(lambda: revs.register({"device": A, "name": "gear", "frame_id": "frm_a2"})) == "ID_RESERVED"
    assert code_of(lambda: revs.resolve({"device": A, "name": "gear"})) == "STORE_ERROR"


def test_metadata_not_held_while_encoding(tmp_path, monkeypatch):
    store = frames(tmp_path)
    revs = AssetRevisionStore(tmp_path, frame_store=store)
    seen = []

    def hook(stage):
        if stage == "encoded":
            def probe():
                with metadata_transaction(tmp_path):
                    seen.append(True)
            t = threading.Thread(target=probe)
            t.start()
            t.join(10)
    monkeypatch.setattr(module, "_after_stage", hook)
    revs.register({"device": A, "name": "gear", "frame_id": "frm_a1"})
    assert seen == [True]


# --------------------------------------------------- concurrency and crash
def concurrent_writer(root, dev, fids, barrier):
    store = FrameStore(root, max_frames=1000)
    revs = AssetRevisionStore(root, frame_store=store)
    reg = AssetRegistry(root)
    barrier.wait(30)
    for i in range(6):
        fid = fids[i % 2]
        revs.register({"device": dev, "name": "settings-gear", "frame_id": fid})
        reg.register_from_frame("gear", store, fid, region=tuple(REGION))


def test_multiprocess_same_label_across_devices(tmp_path):
    store = frames(tmp_path)
    barrier = CTX.Barrier(4)
    procs = [CTX.Process(target=concurrent_writer, args=(tmp_path, dev, fids, barrier))
             for dev, fids in ((A, ["frm_a1", "frm_a2"]), (B, ["frm_b1", "frm_b2"])) for _ in range(2)]
    for p in procs:
        p.start()
    for p in procs:
        join(p)
    revs = AssetRevisionStore(tmp_path, frame_store=store)
    seeds = {"frm_a1": 1, "frm_a2": 2, "frm_b1": 3, "frm_b2": 4}
    for dev in (A, B):
        res = revs.resolve({"device": dev, "name": "settings-gear"})
        assert res["device"] == dev and res["source_frame_id"].startswith("frm_" + dev[-1].lower())
        assert revs.read_blob(res["png_sha256"]) == MatUtility.encode_png(image(seeds[res["source_frame_id"]]))
    assert len(rows(tmp_path, "asset_revision")) == 8  # 4 scoped + 4 legacy, none overwritten
    alias = rows(tmp_path, "scoped_asset_alias")
    assert sorted(r[4] for r in alias) == [12, 12]  # every commit serialized
    legacy = rows(tmp_path, "legacy_asset_alias")
    assert len(legacy) == 1 and legacy[0][3] == 24 and legacy[0][4] == "complete"
    record = json.loads((tmp_path / "assets/gear.json").read_text(encoding="utf-8"))
    png = (tmp_path / "assets/gear.png").read_bytes()
    assert png == crop_png(seeds[record["source_frame_id"]])
    assert record["device_id"] == (A if record["source_frame_id"].startswith("frm_a") else B)
    assert json.loads(legacy[0][2]) == record


def crash(root, stage, op):
    import vision_app.asset_revisions as m
    m._after_stage = lambda s: os._exit(81) if s == stage else None
    store = FrameStore(root, max_frames=1000)
    if op == "scoped":
        AssetRevisionStore(root, frame_store=store).register({"device": A, "name": "gear", "frame_id": "frm_a2"})
    else:
        AssetRegistry(root).register_from_frame("gear", store, "frm_a2")


def join(process, expected=0):
    process.join(60)
    if process.is_alive():
        process.kill()
        process.join()
        pytest.fail("spawned process exceeded test deadline")
    assert process.exitcode == expected


def run_crash(root, stage, op):
    p = CTX.Process(target=crash, args=(root, stage, op))
    p.start()
    join(p, 81)


@pytest.mark.parametrize("stage,new", [("encoded", False), ("blob_published", False),
                                       ("scoped_committed", True)])
def test_scoped_crash_leaves_old_or_complete_new(tmp_path, stage, new):
    store = frames(tmp_path)
    revs = AssetRevisionStore(tmp_path, frame_store=store)
    old = revs.register({"device": A, "name": "gear", "frame_id": "frm_a1"})
    run_crash(tmp_path, stage, "scoped")
    got = revs.resolve({"device": A, "name": "gear"})
    expect_png = MatUtility.encode_png(image(2 if new else 1))
    assert (got["asset_revision_id"] != old["asset_revision_id"]) is new
    assert got["source_frame_id"] == ("frm_a2" if new else "frm_a1")
    assert revs.read_blob(got["png_sha256"]) == expect_png
    assert len(rows(tmp_path, "asset_revision")) == (2 if new else 1)


@pytest.mark.parametrize("stage,new", [("blob_published", False), ("legacy_pointer_committed", True),
                                       ("legacy_projection_png", True), ("legacy_projection_json", True)])
def test_legacy_crash_never_exposes_torn_pair(tmp_path, stage, new):
    store = frames(tmp_path)
    reg = AssetRegistry(tmp_path)
    reg.register_from_frame("gear", store, "frm_a1")
    old_json = (tmp_path / "assets/gear.json").read_bytes()
    run_crash(tmp_path, stage, "legacy")
    raw_json = json.loads((tmp_path / "assets/gear.json").read_text(encoding="utf-8"))
    raw_png = (tmp_path / "assets/gear.png").read_bytes()
    if not new:
        assert (tmp_path / "assets/gear.json").read_bytes() == old_json
        assert raw_png == MatUtility.encode_png(image(1))
    # Upgraded readers consume only the committed pointer and repair projection.
    record, data, rid = AssetRegistry(tmp_path).snapshot("gear")
    fid = "frm_a2" if new else "frm_a1"
    assert record.source_frame_id == fid and data == MatUtility.encode_png(image(2 if new else 1))
    assert np.array_equal(AssetRegistry(tmp_path).load_image("gear"), image(2 if new else 1))
    assert [a.source_frame_id for a in AssetRegistry(tmp_path).list_assets()] == [fid]
    repaired = json.loads((tmp_path / "assets/gear.json").read_text(encoding="utf-8"))
    assert repaired == record.to_dict() and (tmp_path / "assets/gear.png").read_bytes() == data
    assert rows(tmp_path, "legacy_asset_alias")[0][4] == "complete"
    if stage == "legacy_projection_png":  # proves the raw torn state existed pre-repair
        assert raw_json["source_frame_id"] == "frm_a1" and raw_png == MatUtility.encode_png(image(2))


# ------------------------------------------------------ legacy compatibility
def test_legacy_shape_bytes_and_global_last_committed(tmp_path):
    store = frames(tmp_path)
    reg = AssetRegistry(tmp_path)
    rec_a = reg.register_from_frame("gear", store, "frm_a1", region=tuple(REGION))
    assert set(rec_a.to_dict()) == {"name", "image_path", "width", "height", "created_at",
                                    "source_frame_id", "device_id", "region"}
    assert rec_a.image_path == str(tmp_path.resolve() / "assets" / "gear.png")
    raw = (tmp_path / "assets/gear.json").read_bytes()
    assert raw == json.dumps(rec_a.to_dict(), indent=2, sort_keys=True).encode("utf-8")
    assert (tmp_path / "assets/gear.png").read_bytes() == crop_png(1)
    rec_b = reg.register_from_frame("gear", store, "frm_b1")
    assert reg.get("gear") == rec_b and rec_b.device_id == B
    assert [a.name for a in reg.list_assets()] == ["gear"]
    revs = AssetRevisionStore(tmp_path, frame_store=store)
    for dev in (A, B):
        assert code_of(lambda: revs.resolve({"device": dev, "name": "gear"})) == "NOT_FOUND"
    # Same-name cross-device legacy use still fails the recorded scope check.
    sid = Recorder(store).start("a", "g", A)["session_id"]
    with pytest.raises(RecorderError) as exc:
        Recorder(store)._asset("gear", A, {"frames": [], "assets": [], "references": []})
    assert exc.value.code == "SESSION_SCOPE_MISMATCH" and sid


def test_historical_assets_untouched_and_lazy_adoption(tmp_path):
    store = frames(tmp_path)
    assets = tmp_path / "assets"
    assets.mkdir()
    png = crop_png(1)
    record = {"name": "old", "image_path": str((assets / "old.png").resolve()), "width": 8, "height": 6,
              "created_at": 1.0, "source_frame_id": "frm_a1", "device_id": A, "region": REGION}
    (assets / "old.png").write_bytes(png)
    (assets / "old.json").write_bytes(json.dumps(record, indent=2, sort_keys=True).encode())
    bad = {**record, "name": "bad", "image_path": str((assets / "bad.png").resolve())}
    (assets / "bad.png").write_bytes(crop_png(2))
    (assets / "bad.json").write_text(json.dumps(bad))
    before = {p.name: sha(p.read_bytes()) for p in assets.iterdir()}
    reg = AssetRegistry(tmp_path)
    assert reg.get("old").to_dict() == record
    assert np.array_equal(reg.load_image("old"), image(1)[3:9, 2:10])
    assert [a.name for a in reg.list_assets()] == ["bad", "old"]
    rid = reg.adopt_legacy("old", store)
    assert reg.adopt_legacy("old", store) == rid
    with AssetRevisionStore(tmp_path).pin(rid, device=A) as pinned:
        assert pinned.png_bytes == png and pinned.revision["session_id"] is None
    with pytest.raises(StoreError):
        reg.adopt_legacy("bad", store)
    assert reg.get("old").to_dict() == record
    assert {p.name: sha(p.read_bytes()) for p in assets.iterdir()} == before


# ------------------------------------------------------------ Recorder seam
def test_recorder_pins_exact_revision_and_retained_digest(tmp_path):
    store = frames(tmp_path)
    rec = Recorder(store)
    sa, sa2 = rec.start("a", "g", A)["session_id"], rec.start("a2", "g", A)["session_id"]
    revs = AssetRevisionStore(tmp_path, frame_store=store)
    res = revs.register({"device": A, "session_id": sa, "name": "gear", "frame_id": "frm_a1", "region": REGION})
    revs.register({"device": A, "session_id": sa, "name": "gear", "frame_id": "frm_a2", "region": REGION})
    evidence = {"frames": [], "assets": [], "references": []}
    item = rec.retain_asset_revision(res["asset_revision_id"], A, evidence, session_id=sa)
    assert item["asset_revision_id"] == res["asset_revision_id"]  # exact pin, not the moved alias
    assert item["sha256"] == item["png_sha256"] == res["png_sha256"]
    assert sha((tmp_path / item["retained_path"]).read_bytes()) == res["png_sha256"]
    assert evidence["frames"] == ["frm_a1"] and evidence["assets"] == [item]
    for dev, sid in ((A, sa2), (A, None), (B, sa)):
        with pytest.raises(OperationError) as exc:
            rec.retain_asset_revision(res["asset_revision_id"], dev, evidence, session_id=sid)
        assert exc.value.code == "SCOPE_MISMATCH"


def pin_holder(root, rid, ready):
    revs = AssetRevisionStore(root)
    with revs.pin(rid, device=A):
        ready.set()
        threading.Event().wait(60)


def test_pin_owner_lifetime_reconciled_after_process_death(tmp_path):
    store = frames(tmp_path)
    rid = AssetRevisionStore(tmp_path, frame_store=store).register(
        {"device": A, "name": "gear", "frame_id": "frm_a1"})["asset_revision_id"]
    ready = CTX.Event()
    p = CTX.Process(target=pin_holder, args=(tmp_path, rid, ready))
    p.start()
    assert ready.wait(30)
    revs = AssetRevisionStore(tmp_path)
    assert revs.active_pins() == {rid}
    p.kill()
    p.join(30)
    assert revs.active_pins() == set() and rows(tmp_path, "asset_pin") == []

def test_source_frame_pin_spans_publication_and_explicit_use(tmp_path, monkeypatch):
    store = FrameStore(tmp_path, max_frames=1)
    store.save_frame(image(1), A, frame_id="frm_source")
    revisions = AssetRevisionStore(tmp_path, store)

    def advance(stage):
        if stage == "blob_published":
            store.save_frame(image(2), A, frame_id="frm_new")

    monkeypatch.setattr(module, "_after_stage", advance)
    result = revisions.register({"device": A, "name": "gear", "frame_id": "frm_source"})
    with revisions.pin(result["asset_revision_id"], device=A):
        store.save_frame(image(3), A, frame_id="frm_newer")
        assert store.get_frame("frm_source").device_id == A
    store.save_frame(image(4), A, frame_id="frm_latest")
    assert code_of(lambda: revisions.pin(result["asset_revision_id"], device=A).__enter__()) == "NOT_FOUND"


def test_registration_rejects_session_stopped_before_publication(tmp_path, monkeypatch):
    store = frames(tmp_path)
    recorder = Recorder(store)
    sid = recorder.start("a", "g", A)["session_id"]
    revisions = AssetRevisionStore(tmp_path, store)

    def stop(stage):
        if stage == "blob_published":
            recorder.transition(sid, "stop")

    monkeypatch.setattr(module, "_after_stage", stop)
    request = {"device": A, "session_id": sid, "name": "gear", "frame_id": "frm_a1"}
    assert code_of(lambda: revisions.register(request)) == "PRECONDITION_FAILED"
    assert rows(tmp_path, "asset_revision") == []
    assert rows(tmp_path, "scoped_asset_alias") == []


@pytest.mark.skipif(os.name != "nt", reason="Windows case-insensitive legacy paths")
def test_windows_legacy_case_variants_share_projection_and_pointer(tmp_path):
    store = frames(tmp_path)
    registry = AssetRegistry(tmp_path)
    registry.register_from_frame("Gear", store, "frm_a1")
    latest = registry.register_from_frame("gear", store, "frm_a2")
    record, data, _ = registry.snapshot("GEAR")
    assert record == latest and data == MatUtility.encode_png(image(2))
    assert registry.list_assets() == [latest]
    assert len(rows(tmp_path, "legacy_asset_alias")) == 1

def test_pending_repair_cannot_overwrite_newer_legacy_projection(tmp_path, monkeypatch):
    store = frames(tmp_path)
    registry = AssetRegistry(tmp_path)
    registry.register_from_frame("gear", store, "frm_a1")
    run_crash(tmp_path, "legacy_projection_png", "legacy")
    repair = registry.revisions.repair_projection

    def concurrent_commit(*args):
        AssetRegistry(tmp_path).register_from_frame("gear", store, "frm_b1")
        repair(*args)

    monkeypatch.setattr(registry.revisions, "repair_projection", concurrent_commit)
    record, png, _ = registry.snapshot("gear")
    assert record.source_frame_id == "frm_a2"
    assert png == MatUtility.encode_png(image(2))
    projected = json.loads((tmp_path / "assets/gear.json").read_text(encoding="utf-8"))
    assert projected["source_frame_id"] == "frm_b1"
    assert (tmp_path / "assets/gear.png").read_bytes() == MatUtility.encode_png(image(3))
