"""C11 adapter contention tests using real subprocesses and fixture platforms."""
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from contextlib import ExitStack, closing
import hashlib
import json
import queue
import sqlite3
import threading

import numpy as np
import pytest

from test_runtime import PROFILE, RID, prepared
from test_workflow import call, recorded
from vision_app.assets import AssetRegistry
from vision_app.lifecycle import LifecycleService
from vision_app.mcp_server import VisionMcpServer
from vision_app.recorder import Recorder
from vision_app.recovery import RecoveryService
from vision_app.test.test_coordinator import worker


_EFFECT_WORKER = """
import json
from vision_app.cli import run_cli
from vision_app.mcp_server import VisionMcpServer
from vision_app.runtime import WorkflowRuntime
from vision_app.test.test_workflow import Platform, call

operation, device, sid, binding, run_id, profile = sys.argv[2:]
class BarrierPlatform(Platform):
    def click(self, x, y):
        print("effect")
        assert sys.stdin.readline().strip() == "release"
        return super().click(x, y)

    def key_event(self, key):
        print("effect")
        assert sys.stdin.readline().strip() == "release"
        return True

platform = BarrierPlatform()
server = VisionMcpServer(sys.argv[1], platform_factory=lambda serial: platform)
runtime = WorkflowRuntime(server.store, observation=server.obs, actions=server.actions,
                          probe=lambda *_: json.loads(profile))
print("ready")
assert sys.stdin.readline().strip() == "start"
print("started")
if operation == "runtime":
    result = runtime.run(binding, run_id)
    print(json.dumps(result))
elif operation == "recorded":
    print(json.dumps(call(server, "key", device=device, key="4", session_id=sid)))
else:
    sys.exit(run_cli(["key", "--device", device, "--key", "4", "--json"], service=server.obs))
"""


def begin(process):
    messages = queue.Queue()
    def read():
        for line in process.stdout:
            messages.put(line.strip())
    threading.Thread(target=read, daemon=True).start()
    process.stdin.write("start\n")
    process.stdin.flush()
    assert messages.get(timeout=20) == "started"
    return messages


def release(process, messages):
    process.stdin.write("release\n")
    process.stdin.flush()
    result = json.loads(messages.get(timeout=20))
    assert process.wait(timeout=20) == 0
    return result


def test_device_overlap_and_same_device_adapter_exclusion(prepared):
    runtime, binding, server, _, recorder, *_ = prepared
    session_a = recorder.start("a", "overlap", "dev")["session_id"]
    session_b = recorder.start("b", "overlap", "devB")["session_id"]
    root = server.store.store_dir
    epoch_a = runtime.epochs.current("dev")
    epoch_b = runtime.epochs.current("devB")

    def launch(stack, operation, device, sid=""):
        process = stack.enter_context(worker(root, _EFFECT_WORKER, operation, device, sid,
                                             binding["binding_id"], RID, json.dumps(PROFILE)))
        return process, begin(process)

    with ExitStack() as stack:
        run, run_messages = launch(stack, "runtime", "dev")
        assert run_messages.get(timeout=20) == "effect"
        b, b_messages = launch(stack, "recorded", "devB", session_b)
        assert b_messages.get(timeout=20) == "effect"
        raw, raw_messages = launch(stack, "raw", "dev")
        rec, rec_messages = launch(stack, "recorded", "dev", session_a)
        assert runtime.inspect(RID)["status"] == "running"
        assert release(b, b_messages)["ok"]
        for messages in (raw_messages, rec_messages):
            with pytest.raises(queue.Empty):
                messages.get(timeout=0.25)
        assert recorder.events(session_a)["items"] == []
        assert runtime.epochs.current("dev") == epoch_a + 1
        assert release(run, run_messages)["status"] == "completed"

        # Whichever pending A contender wins must still exclude the other.
        effects = queue.Queue()
        def await_effect(process, messages):
            effects.put((process, messages, messages.get(timeout=20)))
        threading.Thread(target=await_effect, args=(raw, raw_messages), daemon=True).start()
        threading.Thread(target=await_effect, args=(rec, rec_messages), daemon=True).start()
        first, first_messages, event = effects.get(timeout=20)
        assert event == "effect"
        with pytest.raises(queue.Empty):
            effects.get(timeout=0.25)
        assert release(first, first_messages)["ok"]
        second, second_messages, event = effects.get(timeout=20)
        assert second is not first and event == "effect"
        assert release(second, second_messages)["ok"]

    assert runtime.epochs.current("dev") == epoch_a + 3
    assert runtime.epochs.current("devB") == epoch_b + 1
    for sid in (session_a, session_b):
        assert [e["sequence"] for e in recorder.events(sid)["items"]] == [1]
    assert not (root / "operations.lock.sqlite").exists()


@pytest.mark.parametrize("operation", ["find", "wait"])
def test_recorded_alias_race_retains_exact_match_bytes(tmp_path, monkeypatch, operation):
    image_a, image_b = [np.random.default_rng(seed).integers(0, 256, (60, 60, 3), dtype=np.uint8)
                        for seed in (73, 74)]
    class Platform:
        def snapshot(self):
            return image_a.copy()

    server = VisionMcpServer(tmp_path, platform_factory=lambda _: Platform())
    store = server.store
    rec = Recorder(store)
    sid = rec.start("a", "asset race", "A")["session_id"]
    a = call(server, "snapshot", device="A")["frame"]["frame_id"]
    b = store.save_frame(image_b, "B", protected=True).frame_id
    assets = AssetRegistry(tmp_path)
    region = [5, 5, 20, 20]
    assets.register_from_frame("shared", store, a, region=tuple(region))
    _, png, revision = assets.snapshot("shared")
    arrived, replaced = threading.Event(), threading.Event()
    dispatch = server._call_tool

    def after_evidence(name, args, **scope):
        if name == "vision_" + operation:
            arrived.set()
            assert replaced.wait(20)
        return dispatch(name, args, **scope)

    monkeypatch.setattr(server, "_call_tool", after_evidence)
    args = ({"frame_id": a, "target": "shared"} if operation == "find"
            else {"device": "A", "mode": "image", "target": "shared", "timeout": 2})
    with ThreadPoolExecutor(max_workers=1) as pool:
        recorded_call = pool.submit(call, server, operation, session_id=sid, threshold=0.99, **args)
        try:
            assert arrived.wait(20)
            assert call(server, "assets_register", name="shared", frame_id=b, region=region)["ok"]
        finally:
            replaced.set()
        result = recorded_call.result(timeout=20)
    assert result["ok"] and result["found" if operation == "find" else "verified"], result
    item, = rec.event(sid, result["event_id"])["evidence"]["assets"]
    assert item["asset_revision_id"] == revision != assets.snapshot("shared")[2]
    assert item["sha256"] == hashlib.sha256(png).hexdigest()
    assert (tmp_path / item["retained_path"]).read_bytes() == png


def test_concurrent_recovery_open_admits_one_session(prepared, monkeypatch):
    runtime, binding, server, platform, rec, *_ = prepared
    platform.state = 1
    assert runtime.run(binding["binding_id"], RID)["status"] == "needs_agent"
    services = [RecoveryService(server.store), RecoveryService(server.store)]
    barrier = threading.Barrier(2)
    for service in services:
        inspect = service.builder.inspect
        def synchronized(workflow_id, inspect=inspect):
            barrier.wait(timeout=20)
            return inspect(workflow_id)
        monkeypatch.setattr(service.builder, "inspect", synchronized)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = list(pool.map(lambda svc: svc.open(RID), services))
    assert (first["case_id"], first["session_id"]) == (second["case_id"], second["session_id"])
    with closing(sqlite3.connect(rec.path)) as db:
        assert db.execute("SELECT COUNT(*) FROM recovery_cases").fetchone() == (1,)
        assert db.execute("SELECT COUNT(*) FROM sessions").fetchone() == (2,)
        assert db.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []


def test_session_stop_waits_for_recorded_event(tmp_path):
    server = VisionMcpServer(tmp_path)
    recorder = Recorder(server.store)
    sid = recorder.start("explore", "stop race", "dev")["session_id"]
    with worker(tmp_path, _EFFECT_WORKER, "recorded", "dev", sid, "", "", "{}") as process:
        messages = begin(process)
        assert messages.get(timeout=20) == "effect"
        with ThreadPoolExecutor(max_workers=1) as pool:
            stopping = threading.Event()
            def stop():
                stopping.set()
                return recorder.transition(sid, "stop")
            stopped = pool.submit(stop)
            assert stopping.wait(20)
            try:
                with pytest.raises(TimeoutError):
                    stopped.result(timeout=0.25)
                assert recorder.events(sid)["items"][0]["status"] == "pending"
            finally:
                assert release(process, messages)["ok"]
            assert stopped.result(timeout=20)["status"] == "stopped"
    assert recorder.events(sid)["items"][0]["status"] == "success"
    assert call(server, "key", device="dev", key="4", session_id=sid)["error"]["code"] == "SESSION_INACTIVE"


def test_registry_cas_from_two_processes(prepared):
    runtime, binding, server, _, rec, _, wid = prepared
    assert runtime.run(binding["binding_id"], RID)["status"] == "completed"
    lifecycle = LifecycleService(server.store, runtime=runtime)
    lifecycle.register("race", wid, RID, 0, "register")
    lifecycle.activate("race", 1, 1, "activate")
    script = """
import json
from vision_app.lifecycle import LifecycleService
from vision_app.store import FrameStore
from vision_app.workflow import WorkflowError

service = LifecycleService(FrameStore(sys.argv[1]))
print("ready")
assert sys.stdin.readline().strip() == "start"
print("started")
try:
    result = service.disable("race", 2, sys.argv[2])
except WorkflowError as exc:
    result = {"error": str(exc)}
print(json.dumps(result))
"""
    with ExitStack() as stack:
        processes = [stack.enter_context(worker(server.store.store_dir, script, reason))
                     for reason in ("A", "B")]
        with runtime.epochs.device_owner("dev", legacy=True) as owner:
            assert owner is not None
            replies = [begin(process) for process in processes]
            for messages in replies:
                with pytest.raises(queue.Empty):
                    messages.get(timeout=0.25)
        results = [json.loads(messages.get(timeout=20)) for messages in replies]
        assert all(process.wait(timeout=20) == 0 for process in processes)
    assert sum(result.get("error") == "Stale registry generation" for result in results) == 1
    assert sum("error" not in result for result in results) == 1
    with closing(sqlite3.connect(rec.path)) as db:
        assert db.execute("SELECT generation,active_version FROM workflow_families").fetchall() == [(3, None)]
        assert db.execute("SELECT generation FROM workflow_lifecycle_log ORDER BY seq").fetchall() == [(1,), (2,), (3,)]
