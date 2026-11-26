"""C02: real spawned-process barriers and abrupt OS-owner death, no devices."""
import hashlib
import json
import multiprocessing as mp
import os
import threading

import cv2
import numpy as np
import pytest

from vision_app.store import FrameStore, StoreError
from vision_app.metadata import FileLock, metadata_transaction

CTX = mp.get_context("spawn")


def image(value=0):
    return np.full((12, 16, 3), value, np.uint8)


def writer(root, number, barrier):
    store = FrameStore(root, max_frames=1000)
    barrier.wait(20)
    for i in range(12):
        fid = f"f{number}_{i}"
        store.save_frame(image(number), "A", frame_id=fid, protected=True)
        store.set_protected(fid, False)
        store.set_protected(fid, True)
        store.cleanup()


def collision(root, value, barrier, results):
    store = FrameStore(root)
    barrier.wait(20)
    try:
        store.save_frame(image(value), "A", frame_id="same", protected=True)
        results.put(("saved", value))
    except StoreError:
        results.put(("collision", value))


def pinned(root, ready, release):
    with FrameStore(root).pin_frames(["pinned"]):
        ready.set()
        release.wait(30)


def crash(root, stage, ready=None, release=None):
    import vision_app.store as module
    store = FrameStore(root)
    real_bytes = module._atomic_write_bytes
    real_index = store._save_index
    def write(path, data):
        if path.suffix == ".png":
            if stage == "before_png":
                os._exit(71)
            real_bytes(path, data)
            if stage == "after_png":
                os._exit(72)
            if stage == "publishing":
                ready.set()
                release.wait(30)
            return
        real_bytes(path, data)
    def index(records):
        real_index(records)
        if stage == "after_index":
            os._exit(73)
    module._atomic_write_bytes = write
    store._save_index = index
    if stage == "cleanup":
        store._delete_record_file = lambda rec: os._exit(74)
        store.cleanup(now=10**12)
    else:
        store.save_frame(image(33), "A", frame_id="crash", protected=True)


def join(process, expected=0):
    process.join(30)
    if process.is_alive():
        process.kill()
        process.join()
        pytest.fail("spawned process exceeded test deadline")
    assert process.exitcode == expected


def test_multiprocess_save_protect_cleanup_no_lost_rows(tmp_path):
    barrier = CTX.Barrier(4)
    workers = [CTX.Process(target=writer, args=(tmp_path, i, barrier)) for i in range(4)]
    for p in workers:
        p.start()
    for p in workers:
        join(p)
    store = FrameStore(tmp_path)
    assert len(store.list_frames()) == 48
    for rec in store.list_frames():
        assert rec.protected
        assert store.load_image(rec.frame_id)[0, 0, 0] == int(rec.frame_id[1])


def test_atomic_collision_and_no_id_reuse(tmp_path):
    barrier, results = CTX.Barrier(2), CTX.Queue()
    workers = [CTX.Process(target=collision, args=(tmp_path, i, barrier, results)) for i in (11, 22)]
    for p in workers:
        p.start()
    for p in workers:
        join(p)
    outcomes = [results.get(timeout=5) for _ in workers]
    winner = next(value for result, value in outcomes if result == "saved")
    assert sorted(result for result, _ in outcomes) == ["collision", "saved"]
    store = FrameStore(tmp_path)
    assert store.load_image("same")[0, 0, 0] == winner
    store.set_protected("same", False)
    store.cleanup(now=10**12)
    with pytest.raises(StoreError, match="reserved"):
        store.save_frame(image(), "A", frame_id="same")


@pytest.mark.parametrize("kill_owner", [False, True])
def test_live_pin_survives_cleanup_and_dead_owner_reconciles(tmp_path, kill_owner):
    store = FrameStore(tmp_path, ttl_seconds=1)
    store.save_frame(image(), "A", frame_id="pinned", timestamp=1)
    ready, release = CTX.Event(), CTX.Event()
    p = CTX.Process(target=pinned, args=(tmp_path, ready, release))
    p.start()
    try:
        assert ready.wait(20)
        assert store.cleanup(now=100) == []
        assert store.resolve_image_path(store.get_frame("pinned").image_path).exists()
    finally:
        if kill_owner:
            p.kill()
            p.join(20)
        else:
            release.set()
            join(p)
    assert store.cleanup(now=100) == ["pinned"]
    assert json.loads(store.lifetime_path.read_text())["pins"] == {}


@pytest.mark.parametrize("stage,exit_code,indexed", [
    ("before_png", 71, False), ("after_png", 72, False), ("after_index", 73, True)])
def test_crash_publication_only_orphans_never_dangling_protected(tmp_path, stage, exit_code, indexed):
    p = CTX.Process(target=crash, args=(tmp_path, stage))
    p.start()
    join(p, exit_code)
    store = FrameStore(tmp_path)
    assert bool(store.list_frames()) == indexed
    store.cleanup(now=10**12)
    if indexed:
        assert store.get_frame("crash").protected
        assert store.load_image("crash")[0, 0, 0] == 33
    else:
        assert not list(store.frames_dir.glob("*.png"))
    with pytest.raises(StoreError):
        store.save_frame(image(), "A", frame_id="crash")


def test_cleanup_crash_removes_pointer_before_bytes(tmp_path):
    store = FrameStore(tmp_path)
    store.save_frame(image(), "A", frame_id="old")
    p = CTX.Process(target=crash, args=(tmp_path, "cleanup"))
    p.start()
    join(p, 74)
    assert store.list_frames() == []
    assert (store.frames_dir / "old.png").exists()
    store.cleanup()
    assert not (store.frames_dir / "old.png").exists()


def test_live_publication_claim_excludes_orphan_cleanup(tmp_path):
    ready, release = CTX.Event(), CTX.Event()
    p = CTX.Process(target=crash, args=(tmp_path, "publishing", ready, release))
    p.start()
    try:
        assert ready.wait(20)
        FrameStore(tmp_path).cleanup(now=10**12)
        assert (tmp_path / "frames/crash.png").exists()
    finally:
        release.set()
        join(p)
    assert FrameStore(tmp_path).load_image("crash")[0, 0, 0] == 33


def test_codec_outside_metadata_and_legacy_bytes_unchanged(tmp_path, monkeypatch):
    store = FrameStore(tmp_path)
    def check_available():
        acquired = []
        def probe():
            lock = FileLock(tmp_path, "metadata", "shared")
            acquired.append(lock.acquire(blocking=False))
            if acquired[-1]:
                lock.release()
        t = threading.Thread(target=probe)
        t.start()
        t.join(5)
        assert acquired == [True]
    encode, decode = cv2.imencode, cv2.imread
    def encode_checked(*args):
        check_available()
        return encode(*args)
    def decode_checked(*args):
        check_available()
        store.cleanup(now=10**12)  # active image reader cannot lose its PNG
        return decode(*args)
    monkeypatch.setattr(cv2, "imencode", encode_checked)
    monkeypatch.setattr(cv2, "imread", decode_checked)
    rec = store.save_frame(image(7), "A", frame_id="legacy", protected=True)
    expected = encode(".png", image(7))[1].tobytes()
    assert hashlib.sha256((store.frames_dir / "legacy.png").read_bytes()).digest() == hashlib.sha256(expected).digest()
    assert json.loads(store.index_path.read_text()) == {"frames": {"legacy": rec.to_dict()}}
    assert store.load_image("legacy")[0, 0, 0] == 7


def test_thread_exclusion_nested_metadata_and_context_pins(tmp_path):
    store = FrameStore(tmp_path)
    store.save_frame(image(), "A", frame_id="thread")
    with metadata_transaction(store):
        with metadata_transaction(store):
            assert store.get_frame("thread").frame_id == "thread"
    with store.pin_frames(["thread"]):
        t = threading.Thread(target=lambda: store.cleanup(now=10**12))
        t.start()
        t.join(5)
        assert not t.is_alive()
        assert store.get_frame("thread")
    assert store.cleanup(now=10**12) == ["thread"]


def case_alias_publisher(root, ready, release):
    """Hold a durable reservation before any PNG is published."""
    import vision_app.store as module
    original = module._atomic_write_bytes
    def write(path, data):
        if path.suffix == ".png":
            ready.set()
            if not release.wait(30):
                raise RuntimeError("publication barrier timed out")
        return original(path, data)
    module._atomic_write_bytes = write
    FrameStore(root).save_frame(image(17), "A", frame_id="CaseAlias", protected=True)


def test_case_insensitive_path_alias_cannot_overwrite_reserved_frame(tmp_path):
    probe = tmp_path / "CaseProbe"
    probe.write_bytes(b"x")
    insensitive = (tmp_path / "caseprobe").exists()
    probe.unlink()
    if not insensitive:
        pytest.skip("requires case-insensitive filesystem")
    ready, release = CTX.Event(), CTX.Event()
    p = CTX.Process(target=case_alias_publisher, args=(tmp_path, ready, release))
    p.start()
    store = FrameStore(tmp_path)
    try:
        assert ready.wait(20)
        with pytest.raises(StoreError, match="reserved"):
            store.save_frame(image(99), "B", frame_id="casealias", protected=True)
    finally:
        release.set()
        join(p)
    assert [r.frame_id for r in store.list_frames()] == ["CaseAlias"]
    assert store.load_image("CaseAlias")[0, 0, 0] == 17
    store.set_protected("CaseAlias", False)
    store.cleanup(now=10**12)
    with pytest.raises(StoreError, match="reserved"):
        store.save_frame(image(), "B", frame_id="CASEALIAS")
