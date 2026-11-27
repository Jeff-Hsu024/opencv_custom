import base64
import json
from pathlib import Path

from jsonschema import Draft202012Validator
import pytest
from test_workflow import Platform,call
from vision_app.mcp_server import VisionMcpServer,_tool_definitions
from vision_app.recorder import Recorder,ANNOTATION_FIELDS
from vision_app.transition import SCOPED_TRANSITION_SCHEMA, TransitionService
from vision_app.asset_revisions import AssetRevisionStore
from vision_app.epochs import DeviceEpochs
from vision_app.test.test_coordinator import worker
from vision_app.workflow import WorkflowBuilder
from vision_app.cli import run_cli

T="trans_"+"a"*32

@pytest.fixture
def env(tmp_path):
    p=Platform();s=VisionMcpServer(tmp_path,platform_factory=lambda _:p)
    r=Recorder(s.store);sid=r.start("test","navigation","dev")["session_id"]
    pre=call(s,"snapshot",device="dev",session_id=sid)
    call(s,"assets_register",name="button",frame_id=pre["frame"]["frame_id"],region=[80,60,100,80],session_id=sid)
    args=dict(device="dev",session_id=sid,transition_id=T,target="button",postcondition={"mode":"changed","timeout":5},return_image=False)
    return p,s,r,sid,args

def test_annotation_contract(env,capsys):
    p,s,r,sid,args=env
    schema=next(t for t in _tool_definitions() if t["name"]=="vision_record_checkpoint")["inputSchema"]["properties"]["annotation"]
    assert set(schema["properties"])==ANNOTATION_FIELDS and schema["additionalProperties"] is False
    eid=r.events(sid)["items"][0]["event_id"]
    bad=call(s,"record_checkpoint",session_id=sid,event_id=eid,annotation={"known_assets":["sensitivevalue"]})
    assert bad["error"]["code"]=="INVALID_ANNOTATION" and bad["error"]["details"]["unknown_fields"]==["known_assets"]
    assert "sensitivevalue" not in json.dumps(bad) and not r.annotations(sid)["items"]
    code=run_cli(["--store-dir",str(s.store.store_dir),"record","annotate","--session",sid,"--event",eid,"--annotation",'{"known_assets":[]}'])
    assert code==3 and json.loads(capsys.readouterr().out)["error"]["code"]=="INVALID_ANNOTATION"

@pytest.mark.parametrize("scoped", [False, True])
def test_transition_buildable_and_idempotent(env, scoped):
    p,s,r,sid,args=env
    operation = "scoped_transition" if scoped else "transition"
    if scoped:
        args, revision = scoped_args(env)
        # Move the alias to a different crop so the expected ref can only come from the original revision.
        AssetRevisionStore(s.store.store_dir, frame_store=s.store).register({
            "device": "dev", "session_id": sid, "name": "button",
            "frame_id": revision["source_frame_id"], "region": [20, 21, 40, 41],
        })
    payload = call(s, operation, **args)
    a = payload["result"]
    if scoped:
        validate_scoped(payload)
        assert a["status"] == "completed"
        step, = a["steps"]
        assert step["target"]["template_sha256"] == revision["png_sha256"]
        assert step["target"]["epoch"] == 0 and step["action_epoch"] == 1
        assert step["target"]["device_bbox"] == [80, 60, 100, 80]
        assert step["semantic_verification"] == "UNKNOWN"
        es = step["events"]
        assert call(s, operation, **dict(args, return_image=True))["result"] == dict(a, duplicate_request=True)
    else:
        assert a["status"] == "observed" and a["semantic_verification"] == "UNKNOWN"
        es = a["events"]
    assert a["action_outcome"] == "executed_unverified" and len(p.actions) == 1
    assert [r.event(sid,es[k])["operation"] for k in ("pre","find","action","wait","post")]==["snapshot","find","click","wait","snapshot"]
    assert call(s, operation, **args)["result"]["duplicate_request"] and len(p.actions) == 1
    bad=call(s, operation, **dict(args, threshold=.99))
    assert bad["error"]["code"] == ("REQUEST_ID_CONFLICT" if scoped else "INVALID_TRANSITION")
    ann=r.annotate(sid,es["post"],{"state":"B","observation":"B visible","verification":"PASS"})
    r.transition(sid,"stop")
    plan={"name":"transition","goal":"navigate","states":[{"id":"a","label":"A","event_id":es["pre"],"region":[2,2,35,30],"threshold":.98},{"id":"b","label":"B","event_id":es["post"],"region":[2,2,35,30],"threshold":.98}],"steps":[{"from":"a","to":"b","pre_event_id":es["pre"],"find_event_id":es["find"],"action_event_id":es["action"],"wait_event_id":es["wait"],"post_event_id":es["post"],"annotation_id":ann["annotation_id"]}],"excluded_actions":[]}
    item=WorkflowBuilder(s.store).build(sid,plan)
    assert item["definition"]["validation"]["status"]=="offline_pass"
    assert WorkflowBuilder(s.store).validate(item["workflow_id"])["status"]=="offline_pass"

def test_no_match(env):
    p,s,r,sid,args=env;p.state=1
    res=call(s,"transition",**args)["result"]
    assert res["status"]=="needs_agent" and res["reason"]["code"]=="TARGET_NOT_FOUND" and res["action_outcome"]=="not_attempted"
    assert len(p.actions)==0

def test_ambiguous(env):
    p,s,r,sid,args=env;p.images[0][60:80,110:130]=p.images[0][60:80,80:100]
    res=call(s,"transition",**args)["result"]
    assert res["status"]=="needs_agent" and res["match_count"]==2 and not p.actions

def test_crash_pending(env):
    p,s,r,sid,args=env
    def click(x,y):
        p.actions.append((x,y));raise KeyboardInterrupt()
    p.click=click
    with pytest.raises(KeyboardInterrupt):call(s,"transition",**args)
    res=call(s,"transition",**args)["result"]
    assert res["status"]=="interrupted" and res["action_outcome"]=="unknown" and res["events"]["action"] and len(p.actions)==1
    assert r.event(sid,res["events"]["action"])["status"]=="pending"
    assert DeviceEpochs(s.store).current("dev") == 1

def test_image_content(env):
    p,s,r,sid,args=env
    result=s.call_tool("vision_transition",{**args,"return_image":True})
    assert [c["type"] for c in result["content"]]==["image","text"]
    text=json.loads(result["content"][1]["text"])
    assert text["result"]["status"]=="observed" and "base64" not in result["content"][1]["text"]

def test_cli_parity(env,capsys):
    p,s,r,sid,args=env
    code=run_cli(["--store-dir",str(s.store.store_dir),"--session",sid,"transition","execute","--transition-id",T,"--device","dev","--target","button","--postcondition",'{"mode":"changed","timeout":5}',"--return-image","false"],service=s.obs)
    assert code==0
    res=json.loads(capsys.readouterr().out)["result"]
    assert res["status"]=="observed" and len(p.actions)==1
    assert call(s,"transition_inspect",transition_id=T)["result"]["events"]==res["events"]


def scoped_args(env):
    _, server, recorder, sid, _ = env
    server.obs.android_devices = lambda: {"devices": [{"device_id": "dev", "platform": "adb"}]}
    pre = call(server, "snapshot", device="dev", session_id=sid, return_image=False)
    revision = AssetRevisionStore(server.store.store_dir, frame_store=server.store).register({
        "device": "dev", "session_id": sid, "frame_id": pre["frame"]["frame_id"],
        "name": "button", "region": [80, 60, 100, 80],
    })
    return {
        "device": "dev", "session_id": sid, "transition_id": "strans_" + "a" * 32,
        "target_asset_revision_id": revision["asset_revision_id"],
        "postcondition": {"mode": "changed", "timeout": 5},
    }, revision


def validate_scoped(payload):
    specs = Path("specs/agent-vision-phase9")
    schema = json.loads((specs / "c00/RESPONSE_SCHEMAS.json").read_text())["operations"]["scoped_transition"]
    Draft202012Validator(schema).validate(payload)
    requests = json.loads((specs / "CONTRACT_SCHEMAS.json").read_text())["operations"]
    assert SCOPED_TRANSITION_SCHEMA == requests["scoped_transition"]


def test_scoped_image_wait_failure_and_cli_duplicate(env, tmp_path, capsys):
    platform, server, recorder, sid, _ = env
    args, revision = scoped_args(env)
    args["postcondition"] = {"mode": "image", "timeout": .04, "asset_revision_id": revision["asset_revision_id"]}
    response = server.call_tool("vision_scoped_transition", dict(args, return_image=True))
    assert [item["type"] for item in response["content"]] == ["text", "image"]
    payload = json.loads(response["content"][0]["text"])
    validate_scoped(payload)
    receipt = payload["result"]
    step, = receipt["steps"]
    assert receipt["status"] == "needs_agent" and receipt["observation_phase"] == "post_action"
    assert receipt["action_outcome"] == "executed_unverified"
    assert step["wait"]["status"] == "timeout" and step["semantic_verification"] == "UNKNOWN"
    assert receipt["last_frame_id"] == step["wait"]["frame_id"] != step["pre_frame_id"]
    wait = recorder.event(sid, step["events"]["wait"])
    assert wait["status"] == "timeout" and wait["evidence"]["assets"][0]["asset_revision_id"] == revision["asset_revision_id"]
    assert base64.b64decode(response["content"][1]["data"]) == Path(
        wait["result"]["operation_result"]["artifact"]["path"]).read_bytes()
    request_path = tmp_path / "request.json"
    request_path.write_text(json.dumps(args), encoding="utf-8")
    code = run_cli(["phase9", "scoped-transition", "--request", str(request_path)], service=server.obs)
    assert code == 3
    assert json.loads(capsys.readouterr().out)["result"] == dict(receipt, duplicate_request=True)
    assert len(platform.actions) == 1


def test_scoped_transition_rejects_cross_session_revision(env):
    platform, server, recorder, _, _ = env
    args, _ = scoped_args(env)
    other = recorder.start("other", "test scope", "dev")["session_id"]
    payload = call(server, "scoped_transition", **dict(args, session_id=other))
    validate_scoped(payload)
    assert payload["error"]["code"] == "SCOPE_MISMATCH"
    assert not platform.actions


def test_scoped_pending_survives_process_kill_without_replay(env):
    platform, server, recorder, sid, _ = env
    args, _ = scoped_args(env)
    tid = args["transition_id"]
    with worker(server.store.store_dir, """
import json
from pathlib import Path
from vision_app.mcp_server import VisionMcpServer
from vision_app.test.test_workflow import Platform

class PausedPlatform(Platform):
    def click(self, x, y):
        Path(sys.argv[1], "click-entered").write_text(f"{x},{y}")
        print("ready")
        sys.stdin.readline()
        return True

mcp = VisionMcpServer(sys.argv[1], platform_factory=lambda _: PausedPlatform())
mcp.obs.android_devices = lambda: {"devices": [{"device_id": "dev", "platform": "adb"}]}
mcp.call_tool("vision_scoped_transition", json.loads(sys.argv[2]))
""", json.dumps(args)):
        epochs = DeviceEpochs(server.store)
        svc = TransitionService(server.store, observation=server.obs)
        live = epochs.inspect(tid, svc._reconcile_scoped)
        assert live["status"] == "in_progress" and live["action_outcome"] == "unknown"
        assert live["last_frame_id"] is None and epochs.current("dev") == 1
        assert live["steps"][0]["action_epoch"] == 1
        validate_scoped({"ok": True, "result": live})
        with epochs.device_owner("dev", timeout=0) as owner:
            assert owner is None
    payload = call(server, "scoped_transition", **args)
    validate_scoped(payload)
    receipt = payload["result"]
    assert receipt["status"] == "interrupted" and receipt["duplicate_request"]
    assert receipt["action_outcome"] == "unknown" and receipt["last_frame_id"] is None
    assert receipt["steps"][0]["action_epoch"] == epochs.current("dev") == 1
    event = recorder.event(sid, receipt["steps"][0]["events"]["action"])
    assert event["status"] == "pending"
    assert call(server, "scoped_transition", **args)["result"] == receipt
    assert not platform.actions
