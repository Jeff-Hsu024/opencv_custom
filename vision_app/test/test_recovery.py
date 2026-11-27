"""Recovery service tests using actual Recorder/Builder/Runtime and a fake device."""
import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from test_runtime import prepared, PROFILE, RID
from test_workflow import recorded
from vision_app.recovery import RecoveryService, seal
from vision_app.workflow import WorkflowError

RID2="run_"+"b"*32

@pytest.fixture
def recovery(prepared):
    rt,b,server,p,rec,sid,wid=prepared
    p.state=1
    result=rt.run(b["binding_id"],RID)
    assert result["status"]=="needs_agent" and result["action_outcome"]=="not_attempted"
    svc=RecoveryService(server.store)
    case=svc.open(RID)
    return rt,b,server,p,rec,sid,wid,svc,case

def record_route(recovery, *, late_anchor=False, separate_anchor=False):
    rt,b,server,p,rec,sid,wid,svc,case=recovery
    csid=case["session_id"]
    def op(tool,**args):
        r=server.call_tool("vision_"+tool,{"session_id":csid,**args})
        out=json.loads(next(c["text"] for c in r["content"] if c["type"]=="text"))
        assert out["ok"],out
        return out
    first=op("snapshot",device="dev")
    anchor=first["event_id"]
    fid=first["frame"]["frame_id"]
    if not late_anchor:
        ann=rec.annotate(csid,anchor,{"state":"B","observation":"Actual page B","verification":"PASS"})
    if not separate_anchor:
        op("assets_register",name="recover_target",frame_id=fid,region=[80,60,100,80])
    pre=op("snapshot",device="dev")
    fid=pre["frame"]["frame_id"]
    if separate_anchor:
        op("assets_register",name="recover_target",frame_id=fid,region=[80,60,100,80])
    found=op("find",frame_id=fid,target="recover_target",all=True,threshold=.98)
    click=op("click",device="dev",ref=found["matches"][0]["ref_id"],max_age_seconds=15)
    wait=op("wait",device="dev",mode="changed",baseline_frame_id=fid,timeout=5)
    post=op("snapshot",device="dev")
    end=rec.annotate(csid,post["event_id"],{"state":"A","observation":"Returned to A","verification":"PASS"})
    if late_anchor:
        ann=rec.annotate(csid,anchor,{"state":"B","observation":"Late","verification":"PASS"})
    rec.transition(csid,"stop")
    plan={"name":"return to A","goal":"recover","states":[
        {"id":"b","label":"B","event_id":pre["event_id"],"region":[2,2,35,30],"threshold":.98},
        {"id":"a","label":"A","event_id":post["event_id"],"region":[2,2,35,30],"threshold":.98}],
        "steps":[{"from":"b","to":"a","pre_event_id":pre["event_id"],"find_event_id":found["event_id"],
                  "action_event_id":click["event_id"],"wait_event_id":wait["event_id"],
                  "post_event_id":post["event_id"],"annotation_id":end["annotation_id"]}],"excluded_actions":[]}
    reconciliation={"anchor_event_id":anchor,"annotation_id":ann["annotation_id"],"outcome":"not_attempted","note":"No original action."}
    return plan,reconciliation


def test_proposal_rejects_changed_anchor_outside_plan(recovery, monkeypatch):
    from vision_app.validation_context import EvidenceChanged, evidence_snapshot

    _, _, server, _, rec, _, _, svc, case = recovery
    plan, reconciliation = record_route(recovery, separate_anchor=True)
    sid = case["session_id"]
    anchor = rec.event(sid, reconciliation["anchor_event_id"])["result"]["frame"]["frame_id"]
    with evidence_snapshot(svc.builder, sid, plan) as snapshot:
        assert anchor not in snapshot.frames

    publish = svc.builder._publish_locked

    def change_anchor(*args, **kwargs):
        server.store.set_protected(anchor, False)
        server.store.set_protected(anchor, True)
        return publish(*args, **kwargs)

    monkeypatch.setattr(svc.builder, "_publish_locked", change_anchor)
    with pytest.raises(EvidenceChanged):
        svc.propose(case["case_id"], "recovery_route", "a", reconciliation, plan)
    assert not svc.inspect(case["case_id"])["proposals"]["items"]

def test_case_open_idempotent_and_persistent(recovery):
    rt,b,server,p,rec,sid,wid,svc,case=recovery
    before=len(p.actions)
    duplicate=RecoveryService(server.store).open(RID)
    assert duplicate["case_id"]==case["case_id"] and duplicate["session_id"]==case["session_id"]
    assert svc.list()["items"][0]["case_id"]==case["case_id"]
    assert case["handoff"]["action_outcome"]=="not_attempted"
    assert len(case["handoff"]["remaining_steps"])==1
    assert len(p.actions)==before
    assert seal(rt._load("runs",RID))==case["handoff"]["failed_run_sha256"]

def test_completed_run_rejected(prepared):
    rt,b,server,p,rec,sid,wid=prepared
    assert rt.run(b["binding_id"],RID)["status"]=="completed"
    with pytest.raises(WorkflowError,match="Completed run"):RecoveryService(server.store).open(RID)

def test_interrupted_run_no_replay(prepared):
    rt,b,server,p,rec,sid,wid=prepared
    def click(x,y):
        p.actions.append(("click",x,y))
        raise KeyboardInterrupt()
    p.click=click
    with pytest.raises(KeyboardInterrupt):rt.run(b["binding_id"],RID)
    n=len(p.actions)
    svc=RecoveryService(server.store)
    case=svc.open(RID)
    assert case["handoff"]["action_outcome"]=="unknown"
    assert rt.inspect(RID)["status"]=="interrupted"
    assert svc.open(RID)["case_id"]==case["case_id"]
    assert len(p.actions)==n

def test_propose_and_live_qualification(recovery):
    rt,b,server,p,rec,sid,wid,svc,case=recovery
    plan,reconcile=record_route(recovery)
    before=len(p.actions)
    result=svc.propose(case["case_id"],"recovery_route","a",reconcile,plan)
    pid=result["proposal_id"]
    child=result["payload"]["child_workflow_id"]
    assert child!=wid and result["payload"]["status"]=="offline_pass"
    assert result["payload"]["automatic_resume"] is False
    assert svc.propose(case["case_id"],"recovery_route","a",reconcile,plan)["proposal_id"]==pid
    assert len(p.actions)==before
    p.state=1
    binding=rt.qualify(child,"dev",PROFILE)
    r=rt.run(binding["binding_id"],RID2)
    assert r["status"]=="completed"
    q=svc.verify(pid,RID2)
    assert q["payload"]["status"]=="live_pass"
    assert q["payload"]["automatic_promotion"] is False
    assert svc.verify(pid,RID2)["qualification_id"]==q["qualification_id"]
    assert svc.proposal(pid)["qualifications"]["items"][0]["qualification_id"]==q["qualification_id"]
    assert rt.inspect(RID)["status"]=="needs_agent"
    assert rec.summary(sid)["event_counts"]=={"success":6}
    assert len(p.actions)==before+1

@pytest.mark.parametrize("case,match",[
    ("wrong_outcome","contradicts"),("wrong_destination","endpoint"),
    ("replacement","Full replacement"),("wrong_anchor","First recovery event"),
    ("missing_annotation","annotation"),("excluded_actions","cannot exclude")])
def test_invalid_proposal(recovery,case,match):
    rt,b,server,p,rec,sid,wid,svc,c=recovery
    plan,reconcile=record_route(recovery)
    kind,dest="recovery_route","a"
    if case=="wrong_outcome":reconcile["outcome"]="unknown"
    elif case=="wrong_destination":dest="b"
    elif case=="replacement":kind="replacement"
    elif case=="wrong_anchor":reconcile["anchor_event_id"]=plan["steps"][0]["pre_event_id"]
    elif case=="missing_annotation":reconcile["annotation_id"]="ann_missing"
    elif case=="excluded_actions":plan["excluded_actions"]=[{"event_id":plan["steps"][0]["action_event_id"],"reason":"skip"}]
    with pytest.raises(WorkflowError,match=match):svc.propose(c["case_id"],kind,dest,reconcile,plan)
    assert svc.inspect(c["case_id"])["proposals"]["items"]==[]

def test_late_anchor_rejected(recovery):
    *_,svc,c=recovery
    plan,reconcile=record_route(recovery,late_anchor=True)
    with pytest.raises(WorkflowError,match="before recovery actions"):svc.propose(c["case_id"],"recovery_route","a",reconcile,plan)

def test_disputed_anchor_rejected(recovery):
    rt,b,server,p,rec,sid,wid,svc,c=recovery
    plan,reconcile=record_route(recovery)
    rec.annotate(c["session_id"],reconcile["anchor_event_id"],{"verification":"FAIL","observation":"Disputed"})
    with pytest.raises(WorkflowError,match="disputes anchor"):svc.propose(c["case_id"],"recovery_route","a",reconcile,plan)

def test_wrong_live_run_rejected(recovery):
    rt,b,server,p,rec,sid,wid,svc,c=recovery
    plan,reconcile=record_route(recovery)
    pid=svc.propose(c["case_id"],"recovery_route","a",reconcile,plan)["proposal_id"]
    with pytest.raises(WorkflowError,match="later completed child"):svc.verify(pid,RID)

def test_failed_journal_tamper_rejected(recovery):
    rt,b,server,p,rec,sid,wid,svc,c=recovery
    path=rt._path("runs",RID)
    data=json.loads(path.read_text())
    data["reason"]["message"]="tampered"
    path.write_text(json.dumps(data))
    with pytest.raises(WorkflowError,match="journal changed"):svc.inspect(c["case_id"])

def test_case_cli_restart_and_mcp(recovery):
    rt,b,server,p,rec,sid,wid,svc,c=recovery
    cmd=[sys.executable,"-m","vision_app","--store-dir",str(server.store.store_dir),"recovery","inspect","--case",c["case_id"]]
    result=subprocess.run(cmd,capture_output=True,text=True,check=True)
    assert json.loads(result.stdout)["result"]["session_id"]==c["session_id"]
    res=server.call_tool("vision_recovery_inspect",{"case_id":c["case_id"]})
    out=json.loads(res["content"][0]["text"])
    assert out["result"]["run_id"]==RID
