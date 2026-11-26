import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from vision_app.asset_revisions import AssetRevisionStore
from vision_app.cli import run_cli
from vision_app.epochs import DeviceEpochs
from vision_app.mcp_server import VisionMcpServer, _tool_definitions
from vision_app.primitives import SCHEMAS
from vision_app.recorder import Recorder
from vision_app.test.test_coordinator import worker


class Platform:
    def __init__(self, root):
        self.root = Path(root)

    def snapshot(self):
        return np.random.default_rng(1).integers(0, 255, (24, 24, 3), dtype=np.uint8)

    def click(self, x, y):
        with (self.root / "effect.log").open("a") as stream:
            stream.write(f"{x},{y}\n")
        return True

    def swipe(self, *args, **kwargs):
        return True

    def type_text(self, text):
        return False

    def key_event(self, key):
        raise TimeoutError("key result unknown")


def server(root, platform=None):
    platform = platform or Platform(root)
    mcp = VisionMcpServer(root, platform_factory=lambda _: platform)
    mcp.obs.android_devices = lambda: {"devices": [{"device_id": key, "platform": "adb"} for key in ("A", "B")]}
    return mcp


def call(mcp, operation, **request):
    return json.loads(mcp.call_tool("vision_" + operation, request)["content"][-1]["text"])


def fixture(root):
    mcp = server(root)
    rec = Recorder(mcp.store)
    sid = rec.start("record", "test effect", "A")["session_id"]
    frame = call(mcp, "snapshot", device="A", return_image=False, session_id=sid)["frame"]["frame_id"]
    revisions = AssetRevisionStore(root, frame_store=mcp.store)
    asset = revisions.register(dict(device="A", session_id=sid, frame_id=frame,
                                    name="icon", region=[1, 1, 8, 8]))
    return mcp, rec, sid, frame, asset


def find_request(sid, frame, asset):
    return dict(device="A", session_id=sid, frame_id=frame, asset_revision_id=asset["asset_revision_id"])


def test_exact_revision_legacy_shape_and_session_scope(tmp_path):
    mcp, rec, sid, frame, asset = fixture(tmp_path)
    catalog = json.loads(Path("specs/agent-vision-phase9/CONTRACT_SCHEMAS.json").read_text())
    defs = {tool["name"]: tool["inputSchema"] for tool in _tool_definitions()}
    for op, schema in SCHEMAS.items():
        assert schema == catalog["operations"][op] == defs["vision_" + op]

    request = find_request(sid, frame, asset)
    revisions = AssetRevisionStore(tmp_path, frame_store=mcp.store)
    revisions.register(dict(device="A", session_id=sid, frame_id=frame, name="icon", region=[10, 10, 20, 20]))
    result = call(mcp, "scoped_find", **request)["result"]
    assert result["match_count"] == 1
    match, = result["matches"]
    assert match["epoch"] == 0 and match["device_bbox"] == [1, 1, 8, 8]
    other_session = rec.start("other", "test scope", "A")["session_id"]
    foreign = call(mcp, "scoped_find", **dict(request, session_id=other_session))
    assert foreign["error"]["code"] == "SCOPE_MISMATCH"
    foreign_frame = call(mcp, "snapshot", device="B", return_image=False)["frame"]["frame_id"]
    assert call(mcp, "scoped_find", **dict(request, frame_id=foreign_frame))["error"]["code"] == "SCOPE_MISMATCH"
    assert call(mcp, "click", device="A", ref=match["ref_id"], session_id=other_session)["error"]["code"] == "SCOPE_MISMATCH"

    click = dict(device="A", session_id=sid, action_id="act_" + "a" * 32, ref_id=match["ref_id"])
    wrong = call(mcp, "guarded_click", **dict(click, session_id=other_session, action_id="act_" + "b" * 32))
    assert wrong["result"]["reason"]["code"] == "SCOPE_MISMATCH"
    receipt = call(mcp, "guarded_click", **click)["result"]
    assert receipt["status"] == "completed" and receipt["action_outcome"] == "executed_unverified"
    assert receipt["steps"][0]["target"]["template_sha256"] == asset["png_sha256"]
    assert receipt["last_frame_id"] is None
    assert call(mcp, "guarded_click", **click, max_ref_age_seconds=15)["result"] == dict(receipt, duplicate_request=True)
    assert call(mcp, "guarded_click", **click, max_ref_age_seconds=14)["error"]["code"] == "REQUEST_ID_CONFLICT"
    assert call(mcp, "click", device="A", ref=match["ref_id"], session_id=sid)["error"]["code"] == "STALE_REF_EPOCH"
    for op in ("find", "click"):
        event, = rec.events(sid, operation=op, status="success")["items"]
        detail = rec.event(sid, event["event_id"])
        evidence, = detail["evidence"]["assets"]
        assert evidence["asset_revision_id"] == asset["asset_revision_id"]
        assert evidence["sha256"] == asset["png_sha256"]
    assert (tmp_path / "effect.log").read_text().splitlines() == ["4.0,4.0"]
    assert DeviceEpochs(mcp.store).current("A") == 1


def test_same_device_recorded_mcp_and_raw_cli_contend(tmp_path, capsys):
    mcp, rec, sid, frame, asset = fixture(tmp_path)
    recorded = call(mcp, "scoped_find", **find_request(sid, frame, asset))["result"]["matches"][0]
    asset_wide = AssetRevisionStore(tmp_path, frame_store=mcp.store).register(
        dict(device="A", frame_id=frame, name="wide", region=[1, 1, 8, 8]))
    bare = call(mcp, "scoped_find", **find_request(None, frame, asset_wide))["result"]["matches"][0]
    click = dict(device="A", session_id=sid, action_id="act_" + "c" * 32, ref_id=recorded["ref_id"])
    with worker(tmp_path, """
import json
from vision_app.test.test_primitives import call, Platform, server
class BlockedPlatform(Platform):
    def click(self, x, y):
        print("ready")
        sys.stdin.readline()
        return super().click(x, y)
print(json.dumps(call(server(sys.argv[1], BlockedPlatform(sys.argv[1])),
                      "guarded_click", **json.loads(sys.argv[2]))))
""", json.dumps(click)) as process, ThreadPoolExecutor(max_workers=1) as pool:
        started = threading.Event()

        def raw():
            started.set()
            return run_cli(["click", "--device", "A", "--ref", bare["ref_id"]], service=mcp.obs)

        future = pool.submit(raw)
        try:
            assert started.wait(5)
            # The child has durably advanced the epoch and still owns the serial.
            epochs = DeviceEpochs(mcp.store)
            assert epochs.inspect(click["action_id"])["action_outcome"] == "unknown"
            with epochs.device_owner("A", timeout=0) as owner:
                assert owner is None
        finally:
            process.stdin.write("\n")
            process.stdin.flush()
        assert json.loads(process.stdout.readline())["result"]["status"] == "completed"
        assert future.result(timeout=15) == 3

    assert json.loads(capsys.readouterr().out)["error"]["code"] == "STALE_REF_EPOCH"
    req_file = tmp_path / "request.json"
    req_file.write_text(json.dumps(click), encoding="utf-8")
    assert run_cli(["phase9", "guarded-click", "--request", str(req_file)], service=mcp.obs) == 0
    assert json.loads(capsys.readouterr().out)["result"]["duplicate_request"]
    assert len(rec.events(sid, operation="click")["items"]) == 1
    assert (tmp_path / "effect.log").read_text().splitlines() == ["4.0,4.0"]


def test_interrupted_guarded_click_reconciles_without_replay(tmp_path):
    mcp, rec, sid, frame, asset = fixture(tmp_path)
    match = call(mcp, "scoped_find", **find_request(sid, frame, asset))["result"]["matches"][0]
    request = dict(device="A", session_id=sid, action_id="act_" + "d" * 32, ref_id=match["ref_id"])
    with worker(tmp_path, """
import json
from vision_app.test.test_primitives import call, Platform, server
class InterruptedPlatform(Platform):
    def click(self, x, y):
        super().click(x, y)
        print("ready")
        sys.stdin.readline()
        return True
call(server(sys.argv[1], InterruptedPlatform(sys.argv[1])), "guarded_click", **json.loads(sys.argv[2]))
""", json.dumps(request)) as process:
        process.kill()
        process.wait(timeout=15)

    duplicate = call(mcp, "guarded_click", **request)["result"]
    assert duplicate["duplicate_request"] and duplicate["status"] == "interrupted"
    assert duplicate["last_frame_id"] is None and duplicate["action_outcome"] == "unknown"
    assert duplicate["reason"]["code"] == "ACTION_UNCERTAIN"
    assert DeviceEpochs(mcp.store).current("A") == 1
    assert (tmp_path / "effect.log").read_text().splitlines() == ["4.0,4.0"]
    event, = rec.events(sid, operation="click", status="pending")["items"]
    assert event["evidence"]["assets"][0]["asset_revision_id"] == asset["asset_revision_id"]


def test_historical_frame_match_keeps_its_scope_and_is_not_guarded_input(tmp_path):
    mcp, rec, sid, _, asset = fixture(tmp_path)
    frame = mcp.store.save_frame(Platform(tmp_path).snapshot(), "A").frame_id
    result = call(mcp, "scoped_find", **find_request(sid, frame, asset))["result"]
    match, = result["matches"]
    assert match["epoch"] is None
    result = call(mcp, "guarded_click", device="A", session_id=sid, ref_id=match["ref_id"],
                  action_id="act_" + "e" * 32)["result"]
    assert result["reason"]["code"] == "REF_UNVERSIONED"
    other = rec.start("other", "test scope", "A")["session_id"]
    assert call(mcp, "click", device="A", ref=match["ref_id"], session_id=other)["error"]["code"] == "SCOPE_MISMATCH"
    rec.transition(sid, "pause")
    assert call(mcp, "scoped_find", **find_request(sid, frame, asset))["error"]["code"] == "PRECONDITION_FAILED"
    assert not (tmp_path / "effect.log").exists()


def test_legacy_effects_advance_epoch_even_on_failure(tmp_path, capsys):
    mcp, _, sid, frame, _ = fixture(tmp_path)
    epochs = DeviceEpochs(mcp.store)
    raw = call(mcp, "click", device="A", frame_id=frame, point=[1, 1])
    assert set(raw) == {"ok", "action", "device_id", "status", "verified", "target", "source", "executed_at"}
    assert epochs.current("A") == 1
    assert call(mcp, "swipe", device="A", from_point=[1, 1], to_point=[2, 2], session_id=sid)["ok"]
    assert epochs.current("A") == 2
    assert not call(mcp, "type", device="A", text="fixture", session_id=sid)["ok"]
    assert epochs.current("A") == 3
    assert run_cli(["key", "--device", "A", "--key", "BACK"], service=mcp.obs) == 4
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "ACTION_TIMEOUT"
    assert epochs.current("A") == 4
    assert epochs.current("B") == 0
