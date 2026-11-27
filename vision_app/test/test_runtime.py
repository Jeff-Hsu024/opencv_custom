"""Runtime tests using real recorded fixture and injected deterministic device."""
import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from test_workflow import recorded
from vision_app.mcp_server import VisionMcpServer
from vision_app.recovery import RecoveryService
from vision_app.runtime import WorkflowRuntime, RuntimeFault
from vision_app.test.test_coordinator import worker
from vision_app.workflow import WorkflowBuilder, WorkflowError

PROFILE={"package":"com.example.app","version_code":1,"rotation":1,"locale":"zh-Hant-TW","ui_mode":"0x21"}
RID="run_"+"a"*32


@pytest.fixture
def prepared(recorded):
    server,rec,sid,plan,platform=recorded
    wid=WorkflowBuilder(server.store).build(sid,plan)["workflow_id"]
    platform.state=0
    clock=[0.]
    def sleep(dt): clock[0]+=dt
    runtime=WorkflowRuntime(server.store,observation=server.obs,actions=server.actions,
                            probe=lambda device,package:dict(PROFILE),clock=lambda:clock[0],sleep=sleep)
    binding=runtime.qualify(wid,"dev",PROFILE)
    return runtime,binding,server,platform,rec,sid,wid


def test_live_mock_one_click_and_idempotency(prepared):
    rt,b,server,p,rec,sid,wid=prepared
    before=len(p.actions)
    result=rt.run(b["binding_id"],RID)
    assert result["status"]=="completed" and result["completed_steps"]==1
    assert len(p.actions)==before+1
    s=result["steps"][0]
    assert s["action_receipt"]["verified"] is False
    assert s["status"]=="verified" and s["pre_frame_id"]!=s["post_frame_id"]
    assert s["target"]["ref_id"] != rt.builder.inspect(wid)["definition"]["steps"][0]["provenance"]["source_ref_id"]
    replay=rt.run(b["binding_id"],RID)
    assert replay["duplicate_request"] and replay["status"]=="completed"
    assert len(p.actions)==before+1
    log=rt.inspect(RID)
    assert all(server.store.get_frame(fid).protected for fid in log["frames"])
    assert rt.list()["items"][0]["run_id"]==RID
    assert rec.summary(sid)["event_counts"]=={"success":6}


@pytest.mark.parametrize("case,code",[
    ("profile","PROFILE_MISMATCH"),("geometry","GEOMETRY_MISMATCH"),
    ("wrong_state","PRECONDITION_FAILED"),("unknown_state","PRECONDITION_FAILED"),
    ("ambiguous_state","PRECONDITION_FAILED"),("missing_target","TARGET_NOT_UNIQUE"),
    ("duplicate_target","TARGET_NOT_UNIQUE")])
def test_precondition_stops_before_click(prepared,case,code):
    rt,b,server,p,rec,sid,wid=prepared
    before=len(p.actions)
    if case=="profile":
        rt.probe=lambda d,p:{**PROFILE,"rotation":2}
    elif case=="geometry":p.images[0]=p.images[0][:90]
    elif case=="wrong_state":p.state=1
    elif case=="unknown_state":p.images[0][:]=0
    elif case=="ambiguous_state":p.images[0][40:68,2:35]=p.images[0][2:30,2:35]
    elif case=="missing_target":p.images[0][60:80,80:100]=0
    elif case=="duplicate_target":p.images[0][60:80,110:130]=p.images[0][60:80,80:100]
    r=rt.run(b["binding_id"],RID)
    assert r["status"]=="needs_agent" and r["reason"]["code"]==code,r
    assert r["action_outcome"]=="not_attempted"
    assert len(p.actions)==before


def test_timeout_no_retry(prepared):
    rt,b,server,p,rec,sid,wid=prepared
    before=len(p.actions)
    def click(x,y):
        p.actions.append(("click",x,y))
        return True
    p.click=click
    epoch=rt.epochs.current("dev")
    r=rt.run(b["binding_id"],RID)
    assert r["status"]=="needs_agent" and r["reason"]["code"]=="POSTCONDITION_TIMEOUT"
    assert r["action_outcome"]=="executed_unverified"
    assert len(p.actions)==before+1
    journal=rt.inspect(RID)
    step=journal["steps"][0]
    observed=step["post_observations"][-1]["frame_id"]
    assert step["post_frame_id"] is None and observed==journal["last_frame_id"]
    assert observed!=step["pre_frame_id"]
    np.testing.assert_array_equal(server.store.load_image(observed),p.images[0])
    assert rt.epochs.ref_epoch(step["target"]["ref_id"]).epoch==epoch
    assert rt.epochs.frame_epoch(observed,"dev")==rt.epochs.current("dev")==epoch+1
    assert rt.run(b["binding_id"],RID)["duplicate_request"]
    assert len(p.actions)==before+1


def test_action_failure_unknown_outcome(prepared):
    rt,b,server,p,rec,sid,wid=prepared
    before=len(p.actions)
    def click(x,y):
        p.actions.append(("click",x,y))
        return False
    p.click=click
    r=rt.run(b["binding_id"],RID)
    assert r["status"]=="needs_agent" and r["reason"]["code"]=="ACTION_FAILED"
    assert r["action_outcome"]=="unknown"
    assert len(p.actions)==before+1


def test_crash_pending_never_replays(prepared):
    rt,b,server,p,rec,sid,wid=prepared
    before=len(p.actions)
    def click(x,y):
        p.actions.append(("click",x,y))
        raise KeyboardInterrupt()
    p.click=click
    with pytest.raises(KeyboardInterrupt):rt.run(b["binding_id"],RID)
    pending=rt._load("runs",RID)
    assert pending["status"]=="running" and pending["steps"][-1]["status"]=="action_pending"
    assert pending["action_outcome"]=="unknown"
    restored=WorkflowRuntime(server.store,observation=server.obs,actions=server.actions,probe=lambda d,p:PROFILE)
    r=restored.run(b["binding_id"],RID)
    assert r["status"]=="interrupted" and r["duplicate_request"]
    assert len(p.actions)==before+1


def test_live_owner_then_process_death_inside_input(prepared):
    rt,b,server,p,*_=prepared
    epoch=rt.epochs.current("dev")
    before=len(p.actions)
    recovery=RecoveryService(server.store)
    with worker(server.store.store_dir, """
import json
from vision_app.mcp_server import VisionMcpServer
from vision_app.runtime import WorkflowRuntime
from vision_app.test.test_workflow import Platform

class PausedPlatform(Platform):
    def click(self, x, y):
        print("ready")
        sys.stdin.readline()
        return True

platform = PausedPlatform()
server = VisionMcpServer(sys.argv[1], platform_factory=lambda _: platform)
runtime = WorkflowRuntime(server.store, observation=server.obs, actions=server.actions,
                          probe=lambda *_: json.loads(sys.argv[4]))
runtime.run(sys.argv[2], sys.argv[3])
""", b["binding_id"], RID, json.dumps(PROFILE)):
        journal_path=rt._path("runs",RID)
        raw=journal_path.read_bytes()
        live=rt.inspect(RID)
        assert live["status"]=="running" and live["action_outcome"]=="unknown"
        assert live["steps"][0]["status"]=="action_pending"
        assert live["last_frame_id"]==live["steps"][0]["pre_frame_id"]
        assert rt.epochs.current("dev")==epoch+1
        with rt.epochs.device_owner("dev",timeout=0) as owner:
            assert owner is None
        with pytest.raises(RuntimeFault,match="still active"):
            recovery.open(RID)
        assert journal_path.read_bytes()==raw

    dead=rt.inspect(RID)
    assert dead["status"]=="interrupted" and dead["action_outcome"]=="unknown"
    assert dead["last_frame_id"]==live["last_frame_id"]
    assert recovery.open(RID)["handoff"]["action_outcome"]=="unknown"
    duplicate=rt.run(b["binding_id"],RID)
    assert duplicate["duplicate_request"] and duplicate["status"]=="interrupted"
    assert len(p.actions)==before and rt.epochs.current("dev")==epoch+1


def test_app_change_after_action(prepared):
    rt,b,server,p,rec,sid,wid=prepared
    before=len(p.actions)
    rt.probe=lambda d,pkg:dict(PROFILE) if p.state==0 else {**PROFILE,"locale":"en-US"}
    r=rt.run(b["binding_id"],RID)
    assert r["status"]=="needs_agent" and r["reason"]["code"]=="PROFILE_MISMATCH"
    assert r["action_outcome"]=="executed_unverified" and len(p.actions)==before+1


def test_tampered_bundle_rejected_before_click(prepared):
    rt,b,server,p,rec,sid,wid=prepared
    before=len(p.actions)
    item=rt.builder.inspect(wid)
    path=Path(item["bundle_path"])/item["definition"]["steps"][0]["action"]["template"]["path"]
    path.write_bytes(b"bad")
    r=rt.run(b["binding_id"],RID)
    assert r["status"]=="needs_agent" and r["action_outcome"]=="not_attempted"
    assert len(p.actions)==before


def test_wrong_device_qualification(prepared):
    rt,b,server,p,rec,sid,wid=prepared
    before=len(p.actions)
    with pytest.raises(WorkflowError,match="Device differs"):rt.qualify(wid,"other",PROFILE)
    assert len(p.actions)==before


def test_wrong_profile_qualification(prepared):
    rt,b,server,p,rec,sid,wid=prepared
    with pytest.raises(RuntimeFault,match="profile changed"):rt.qualify(wid,"dev",{**PROFILE,"rotation":2})


def test_receipt_restart_cli_mcp(prepared):
    rt,b,server,p,rec,sid,wid=prepared
    r=rt.run(b["binding_id"],RID)
    assert r["status"]=="completed"
    cmd=[sys.executable,"-m","vision_app","--store-dir",str(server.store.store_dir),"runtime","inspect","--run-id",RID]
    proc=subprocess.run(cmd,capture_output=True,text=True,check=True)
    assert json.loads(proc.stdout)["result"]["completed_steps"]==1
    request={"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"vision_runtime_inspect","arguments":{"run_id":RID}}}
    proc=subprocess.run([sys.executable,"-m","vision_app.mcp_server"],input=json.dumps(request)+"\n",
                        capture_output=True,text=True,env={**os.environ,"VISION_STORE_DIR":str(server.store.store_dir)},check=True)
    payload=json.loads(json.loads(proc.stdout)["result"]["content"][0]["text"])
    assert payload["result"]["status"]=="completed"
