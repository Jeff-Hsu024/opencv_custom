"""Grouped portable core tests, using real evidence and injected fixture devices."""
import copy
import time
import json
from dataclasses import replace
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from test_runtime import prepared, PROFILE, RID
from test_workflow import Platform, recorded
from vision_app.coordinator import Claim
from vision_app.definition_core import ExecutionContext, verify_proof
from vision_app.lifecycle import LifecycleService
from vision_app.mcp_server import _tool_definitions
from vision_app.portable import PortableDefinitions, SCHEMAS
from vision_app.runtime import WorkflowRuntime
from vision_app.workflow import WorkflowError
from vision_app.validation_context import EvidenceChanged

PLAN=Path(__file__).resolve().parents[2]/"specs/agent-vision-phase9"

@pytest.fixture
def published(prepared):
    rt,b,server,p,rec,sid,wid=prepared
    assert rt.run(b["binding_id"],RID)["status"]=="completed"
    service=PortableDefinitions(server.store,runtime=rt)
    record=service.publish(wid,RID)
    return rt,b,server,p,rec,sid,wid,service,record

def test_portable_publish_deterministic_and_adapters(published,tmp_path):
    from vision_app.cli import run_cli
    rt,b,server,p,rec,sid,wid,svc,record=published
    original=rt._load("runs",RID)
    before=len(p.actions)
    assert svc.publish(wid,RID)==record
    assert svc.inspect(record["portable_id"])==record
    assert svc.list()=={"items":[record],"next_cursor":None}
    assert rt._load("runs",RID)==original and len(p.actions)==before
    schemas=json.loads((PLAN/"CONTRACT_SCHEMAS.json").read_text())["operations"]
    responses=json.loads((PLAN/"c00/RESPONSE_SCHEMAS.json").read_text())["operations"]
    tools={t["name"]:t["inputSchema"] for t in _tool_definitions()}
    for op in SCHEMAS:
        assert schemas[op]==tools["vision_"+op]==SCHEMAS[op]
    req={"source_workflow_id":wid,"source_run_id":RID}
    r=server.call_tool("vision_portable_publish",req)
    payload=json.loads(r["content"][0]["text"])
    assert payload=={"ok":True,"result":record}
    Draft202012Validator(responses["portable_publish"]).validate(payload)
    request_file=tmp_path/"publish.json"
    request_file.write_text(json.dumps(req),encoding="utf-8")
    import subprocess,sys
    cli=subprocess.run([sys.executable,"-m","vision_app","--store-dir",str(server.store.store_dir),
                        "phase9","portable-publish","--request",str(request_file)],capture_output=True,text=True)
    assert cli.returncode==0 and json.loads(cli.stdout)==payload
    assert svc.invoke("portable_list",{"limit":True})[1]==2

def test_source_drift_and_immutable_history(published):
    rt,b,server,p,rec,sid,wid,svc,record=published
    pid=record["portable_id"]
    d=rt.builder.inspect(wid)["definition"]
    rec.annotate(sid,d["steps"][0]["provenance"]["post_event_id"],{"observation":"later evidence"})
    with pytest.raises(EvidenceChanged):
        svc.resolve(pid)
    assert svc.inspect(pid)==record

def test_source_proof_tamper_rejected(published):
    rt,b,server,p,rec,sid,wid,svc,record=published
    run=rt._load("runs",RID)
    run["steps"][0]["target"]["device_bbox"][0]+=1
    rt._persist(run)
    payload,code=svc.invoke("portable_publish",{"source_workflow_id":wid,"source_run_id":RID})
    assert code==3 and payload["error"]["code"]=="PROOF_INVALID"
    assert svc.inspect(record["portable_id"])==record

def test_portable_context_uses_shared_interpreter_and_proof(published):
    rt,b,server,p,rec,sid,wid,svc,record=published
    resolved=svc.resolve(record["portable_id"])
    with pytest.raises(WorkflowError,match="source workflow"):
        rt._definition(wid,"device-B",PROFILE)
    # The fixture platform has the same rendered states but separate action history.
    from vision_app.observation import ObservationService
    from vision_app.actions import ActionService
    target=Platform()
    obs=ObservationService(server.store,platform_factory=lambda _:target)
    target_rt=WorkflowRuntime(server.store,observation=obs,probe=lambda d,p:dict(PROFILE))
    rid="prun_"+"b"*32
    ctx=ExecutionContext.create(resolved,"trial","device-B",PROFILE,rid)
    with pytest.raises(WorkflowError):
        replace(ctx,device="device-B",profile_json=b'{}').verify(resolved)
    receipt={"id":rid,"kind":"trial","context":ctx.to_dict(),"device":"device-B",
             "status":"in_progress","request":{},"steps":[],"action_outcome":"not_attempted",
             "completed_steps":0,"last_frame_id":None,"last_confirmed_state":None,
             "observation_phase":"none","reason":None,"created_at":time.time(),"finished_at":None,
             "duplicate_request":False,"action_receipt":None}
    with target_rt.epochs.request_owner(rid) as owner:
        with target_rt.epochs.device_owner("device-B") as device_owner:
            target_rt.epochs.admit(owner,Claim(rid,"trial",{},receipt,device="device-B"))
            def persist(run):
                target_rt.epochs.record(owner,rid,run)
            def observe(fid):
                receipt["last_frame_id"]=fid
                persist(receipt)
            target_rt._interpret(resolved,ctx,owner,device_owner,receipt,persist,observe)
            receipt.update(status="completed",finished_at=time.time())
            target_rt.epochs.record(owner,rid,receipt,terminal=True)
    assert len(target.actions)==1 and receipt["completed_steps"]==1
    proof=verify_proof(target_rt,resolved,ctx,receipt)
    assert proof["context"]==ctx.to_dict()
    assert target_rt.epochs.current("device-B")==1
    assert receipt["steps"][0]["target"]["epoch"]==0
    for key,value in (("action_epoch",0),("from","wrong")):
        forged=copy.deepcopy(receipt)
        forged["steps"][0][key]=value
        with pytest.raises(WorkflowError):
            verify_proof(target_rt,resolved,ctx,forged)
    with pytest.raises(WorkflowError):
        verify_proof(target_rt,resolved,replace(ctx,device="dev"),receipt)


def test_publication_cas_rejects_later_source_change(prepared,monkeypatch):
    import vision_app.portable as portable
    from vision_app.metadata import metadata_held
    rt,b,server,p,rec,sid,wid=prepared
    assert rt.run(b["binding_id"],RID)["status"]=="completed"
    svc=PortableDefinitions(server.store,runtime=rt)
    original=portable._atomic_write_bytes
    changed=False
    def write(path,data):
        nonlocal changed
        original(path,data)
        assert not metadata_held()
        if not changed:
            changed=True
            event=rt.builder.inspect(wid)["definition"]["steps"][0]["provenance"]["post_event_id"]
            rec.annotate(sid,event,{"observation":"changed during publication"})
    monkeypatch.setattr(portable,"_atomic_write_bytes",write)
    with pytest.raises(EvidenceChanged):
        svc.publish(wid,RID)
    assert svc.list()=={"items":[],"next_cursor":None}
    assert list(svc.root.iterdir())==[]


def test_portable_templates_not_mutable_alias_and_tamper(published):
    rt,b,server,p,rec,sid,wid,svc,record=published
    pid=record["portable_id"]
    resolved=svc.resolve(pid)
    path=svc.root/pid/"templates"/(record["template_sha256"][0]+".png")
    path.write_bytes(path.read_bytes()+b"changed")
    with pytest.raises(WorkflowError):
        svc.resolve(pid)
    assert resolved.templates()
    assert svc.inspect(pid)==record
