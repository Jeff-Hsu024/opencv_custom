"""Grouped device preflight, trial and slot CAS tests with real fixture receipts."""
import json
from pathlib import Path
import pytest
from jsonschema import Draft202012Validator

from test_portable_core import published
from test_runtime import prepared,PROFILE,RID
from test_workflow import recorded,Platform
from vision_app.observation import ObservationService
from vision_app.portable_service import PortableService,SCHEMAS
from vision_app.runtime import WorkflowRuntime
from vision_app.observation import OperationError
from vision_app.mcp_server import _tool_definitions
from vision_app.portable_contract import CATALOG

PLAN=Path(__file__).resolve().parents[2]/"specs/agent-vision-phase9"
ASSERTION={"verification":"PASS","observation":"Expected screen verified in fixture","reviewer":"fixture-reviewer"}

@pytest.fixture
def devices(published):
    rt,b,server,p,rec,sid,wid,defs,record=published
    target=Platform()
    profiles={"dev":dict(PROFILE),"device-B":dict(PROFILE)}
    platforms={"dev":p,"device-B":target}
    online=["dev","device-B"]
    obs=ObservationService(server.store,platform_factory=lambda d:platforms[d])
    obs.android_devices=lambda:{"devices":[{"device_id":d,"platform":"adb"} for d in online]}
    runtime=WorkflowRuntime(server.store,observation=obs,probe=lambda d,p:dict(profiles[d]))
    return PortableService(server.store,runtime=runtime),record,p,target,profiles,online

def trial_request(svc,pid,device,rid):
    pf=svc.preflight(pid,device)
    assert pf["status"]=="pass",pf
    return {"preflight_id":pf["preflight_id"],"device":device,"run_id":rid}

def commit_trial(svc,pid,device,rid,generation):
    return svc.slots.commit(pid,device,generation,"trial",rid,ASSERTION)

def validate_response(op,result):
    schemas=json.loads((PLAN/"c00/RESPONSE_SCHEMAS.json").read_text())["operations"]
    Draft202012Validator(schemas[op]).validate({"ok":True,"result":result})

def test_preflight_trial_commit_duplicate_and_revoke(devices):
    svc,record,p,target,profiles,online=devices
    pid=record["portable_id"]
    rid="prun_"+"1"*32
    req=trial_request(svc,pid,"device-B",rid)
    assert not target.actions
    pf=svc.preflight_inspect(req["preflight_id"])
    validate_response("portable_preflight",pf)
    assert svc.slots.inspect(pid,"device-B")["status"]=="absent"
    result=svc.trial(**req)
    assert result["status"]=="completed",result
    validate_response("portable_trial",result)
    assert len(target.actions)==1 and svc.slots.inspect(pid,"device-B")["status"]=="absent"
    q=commit_trial(svc,pid,"device-B",rid,0)
    validate_response("portable_qualify_commit",q)
    assert q["slot_generation"]==1 and svc.slots.inspect(pid,"device-B")["status"]=="active"
    revoked=svc.slots.revoke(pid,"device-B",1,"operator revoke")
    validate_response("portable_qualification_revoke",revoked)
    assert revoked["slot_generation"]==2
    assert commit_trial(svc,pid,"device-B",rid,0)=={**q,"duplicate_request":True}
    assert svc.slots.revoke(pid,"device-B",1,"operator revoke")=={**revoked,"duplicate_request":True}
    assert svc.slots.record(q["qualification_id"])==q
    assert svc.slots.inspect(pid,"device-B")["status"]=="revoked"
    online.remove("device-B")
    assert svc.trial(**req,return_image=True)=={**result,"duplicate_request":True}
    assert len(target.actions)==1
    with pytest.raises(OperationError,match="fresh trial"):
        commit_trial(svc,pid,"device-B",rid,2)

def test_drift_and_stale_observation(devices):
    svc,record,p,target,profiles,online=devices
    pid=record["portable_id"]
    rid="prun_"+"2"*32
    svc.trial(**trial_request(svc,pid,"device-B",rid))
    q=commit_trial(svc,pid,"device-B",rid,0)
    old=svc.slots.observe(pid,"device-B")
    online.remove("device-B")
    assert svc.preflight(pid,"device-B")["reason"]["code"]=="DEVICE_UNAVAILABLE"
    assert svc.slots.inspect(pid,"device-B")["slot_generation"]==1
    online.append("device-B")
    profiles["device-B"]["version_code"]+=1
    failure=svc.preflight(pid,"device-B")
    assert failure["reason"]["code"]=="PROFILE_MISMATCH"
    validate_response("portable_preflight",failure)
    slot=svc.slots.inspect(pid,"device-B")
    assert slot["status"]=="invalidated" and slot["slot_generation"]==2
    profiles["device-B"]=dict(PROFILE)
    target.state=0
    assert svc.preflight(pid,"device-B")["status"]=="pass"
    assert svc.slots.inspect(pid,"device-B")["status"]=="invalidated"
    next_id="prun_"+"3"*32
    svc.trial(**trial_request(svc,pid,"device-B",next_id))
    new=commit_trial(svc,pid,"device-B",next_id,2)
    assert new["slot_generation"]==3
    assert not svc.slots.invalidate(old,failure["reason"])
    assert svc.slots.inspect(pid,"device-B")["qualification_id"]==new["qualification_id"]

def test_source_and_target_qualification_independent(devices):
    svc,record,p,target,profiles,online=devices
    pid=record["portable_id"]
    q=svc.slots.commit(pid,"dev",0,"source",RID,ASSERTION)
    assert q["status"]=="active"
    with pytest.raises(OperationError,match="scope mismatch"):
        svc.slots.commit(pid,"device-B",0,"source",RID,ASSERTION)
    assert svc.slots.inspect(pid,"device-B")["status"]=="absent"
    svc.slots.revoke(pid,"dev",1,"source changed")
    with pytest.raises(OperationError,match="first enrollment"):
        svc.slots.commit(pid,"dev",2,"source",RID,ASSERTION)

def test_interrupted_trial_no_replay(devices):
    svc,record,p,target,profiles,online=devices
    pid=record["portable_id"]
    req=trial_request(svc,pid,"device-B","prun_"+"4"*32)
    def crash(x,y):
        target.actions.append(("click",x,y))
        raise KeyboardInterrupt()
    target.click=crash
    with pytest.raises(KeyboardInterrupt):
        svc.trial(**req)
    receipt=svc.trial_inspect(req["run_id"])
    assert receipt["status"]=="interrupted" and receipt["action_outcome"]=="unknown"
    assert receipt["last_frame_id"] is None and receipt["observation_phase"]=="post_action_unknown"
    validate_response("portable_trial_inspect",receipt)
    assert svc.trial(**req)=={**receipt,"duplicate_request":True}
    assert len(target.actions)==1

def test_frozen_schema_catalog_and_preflight_image(devices,monkeypatch):
    svc,record,p,target,profiles,online=devices
    frozen=json.loads((PLAN/"CONTRACT_SCHEMAS.json").read_text())["operations"]
    assert all(schema==frozen[op] for op,schema in CATALOG.items())
    tools={t["name"]:t["inputSchema"] for t in _tool_definitions()}
    assert all(tools["vision_"+op]==schema for op,schema in SCHEMAS.items())
    from vision_app.mcp_server import VisionMcpServer
    import vision_app.runtime as runtime
    monkeypatch.setattr(runtime,"adb_profile",lambda d,p:dict(profiles[d]))
    server=VisionMcpServer(svc.store.store_dir,platform_factory=lambda d:target)
    server.obs.android_devices=svc.rt.obs.android_devices
    result=server.call_tool("vision_portable_preflight",{"portable_id":record["portable_id"],"device":"device-B","return_image":True})
    assert not result["isError"] and [x["type"] for x in result["content"]]==["text","image"]
    payload=json.loads(result["content"][0]["text"])
    validate_response("portable_preflight",payload["result"])
    import base64
    assert base64.b64decode(result["content"][1]["data"])==svc.store.resolve_image_path(
        svc.store.get_frame(payload["result"]["frame_id"]).image_path).read_bytes()


def test_preflight_timeout_receipt_and_exit_code(devices,monkeypatch):
    svc,record,p,target,profiles,online=devices
    def timeout(*args,**kwargs):
        raise OperationError("CAPTURE_TIMEOUT","Fixture capture timeout",exit_code=4)
    monkeypatch.setattr(svc.rt.obs,"snapshot",timeout)
    reply,code=svc.invoke("portable_preflight",{"portable_id":record["portable_id"],"device":"device-B"})
    assert code==4 and reply["ok"] is True
    receipt=reply["result"]
    assert receipt["status"]=="fail" and receipt["reason"]["code"]=="CAPTURE_TIMEOUT"
    assert receipt["frame_id"] is None and target.actions==[]
    validate_response("portable_preflight",receipt)
    inspected,code=svc.invoke("portable_preflight_inspect",{"preflight_id":receipt["preflight_id"]})
    assert code==0 and inspected["result"]==receipt
