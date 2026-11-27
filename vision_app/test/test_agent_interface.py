import json,copy
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import pytest
from test_workflow import recorded,call
from test_transition import env,T
from vision_app.workflow import WorkflowBuilder,WorkflowError
from vision_app.validation_context import validation_scope
from vision_app.transition import TransitionService
from vision_app.cli import run_cli

def test_response_projection(recorded,capsys):
    s,r,sid,plan,p=recorded
    full=call(s,"workflow_build",session_id=sid,plan=plan)["result"]
    compact=call(s,"workflow_build",session_id=sid,plan=plan,response_mode="summary")["result"]
    wid=full["workflow_id"]
    assert compact["workflow_id"]==wid and compact["status"]=="offline_pass" and compact["steps"]==1
    assert len(json.dumps(compact))<len(json.dumps(full))*.3
    assert call(s,"workflow_inspect",workflow_id=wid)["result"]==full
    detail=call(s,"workflow_inspect",workflow_id=wid,response_mode="detail",detail_id="step_1")["result"]
    assert detail["step"]==full["definition"]["steps"][0]
    assert run_cli(["--store-dir",str(s.store.store_dir),"workflow","inspect","--workflow",wid,"--response-mode","summary"])==0
    assert json.loads(capsys.readouterr().out)["result"]==compact
    bad=call(s,"workflow_build",session_id=sid,plan={**plan,"name":"bad"},response_mode="invalid")
    assert bad["error"]["code"]=="INVALID_RESPONSE_MODE" and len(WorkflowBuilder(s.store).list()["items"])==1

def test_metadata_only_and_find_wait_options(env):
    p,s,r,sid,args=env
    result=s.call_tool("vision_snapshot",{"device":"dev","session_id":sid,"return_image":False})
    assert [c["type"] for c in result["content"]]==["text"]
    payload=json.loads(result["content"][0]["text"])
    fid=payload["frame"]["frame_id"]
    assert Path(payload["artifact"]["path"]).is_file()
    found=call(s,"find",frame_id=fid,target="button",all=True,max_results=2,color_mode="bgr",threshold=.98,session_id=sid)
    assert found["count"]==1
    p.state=1
    w=call(s,"wait",device="dev",mode="changed",baseline_frame_id=fid,max_captures=2,pixel_tolerance=0,min_changed_ratio=.01,timeout=3,session_id=sid)
    assert w["verified"] is True

def test_asset_cursor(env):
    p,s,r,sid,args=env
    first=call(s,"snapshot",device="dev",session_id=sid)["frame"]["frame_id"]
    for i in range(3):call(s,"assets_register",name="a"+str(i),frame_id=first,region=[2+i,2,22+i,22],session_id=sid)
    page=r.asset_evidence(sid,limit=2)
    assert page["next_cursor"]==2
    second=r.asset_evidence(sid,limit=2,after=2)
    assert len(second["items"])==2 and second["next_cursor"] is None
    call(s,"find",frame_id=first,target="button",all=True,session_id=sid)
    assert r.asset_evidence(sid,limit=2)==page
    assert call(s,"record_asset_evidence",session_id=sid,limit=2,after=2)["result"]==second
    assert all(i["asset"]["sha256"] and i["event_id"] for i in page["items"]+second["items"])

def test_transition_wait_failure(env):
    p,s,r,sid,args=env
    def click(x,y):p.actions.append((x,y));return True
    p.click=click
    args["postcondition"]["timeout"]=.05
    result=call(s,"transition",**args)["result"]
    assert result["status"]=="needs_agent" and result["action_outcome"]=="executed_unverified" and len(p.actions)==1
    assert "post" not in result["events"]
    assert call(s,"transition",**args)["result"]["duplicate_request"] and len(p.actions)==1

def test_transition_failed_click(env):
    p,s,r,sid,args=env
    def click(x,y):p.actions.append((x,y));return False
    p.click=click
    result=call(s,"transition",**args)["result"]
    assert result["status"]=="needs_agent" and result["action_outcome"]=="unknown" and len(p.actions)==1
    assert "wait" not in result["events"]

def test_transition_stale(env,monkeypatch):
    p,s,r,sid,args=env
    orig=s.obs.snapshot
    def snapshot(*a,**kw):
        x=orig(*a,**kw);x["frame"]["timestamp"]-=100;return x
    monkeypatch.setattr(s.obs,"snapshot",snapshot)
    res=call(s,"transition",**args)["result"]
    assert res["reason"]["code"]=="FRAME_STALE" and len(p.actions)==0

def test_post_snapshot_failure(env,monkeypatch):
    p,s,r,sid,args=env;count=[0];orig=s.obs.snapshot
    def snapshot(*a,**kw):
        count[0]+=1
        if count[0]>1:raise RuntimeError("capture failed")
        return orig(*a,**kw)
    monkeypatch.setattr(s.obs,"snapshot",snapshot)
    res=call(s,"transition",**args)["result"]
    assert res["status"]=="needs_agent" and res["action_outcome"]=="executed_unverified"
    assert len(p.actions)==1 and r.event(sid,res["events"]["post"])["status"]=="failed"

def test_transition_concurrent_duplicate(env):
    p,s,r,sid,args=env
    def invoke(_):return call(s,"transition",**args)["result"]
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(invoke,range(2)))
    assert all(x["status"]=="observed" for x in results)
    assert sum(bool(x.get("duplicate_request")) for x in results)==1 and len(p.actions)==1

def test_transition_guard_failure(env):
    p,s,r,sid,args=env
    p.state=1
    res=call(s,"transition",**{**args,"pre_state":"button"})["result"]
    assert res["reason"]["code"]=="PRECONDITION_FAILED" and not p.actions

@pytest.mark.parametrize("tamper",["template","frame","annotation","ref","asset","plan"])
def test_task_validation_tamper(recorded,tamper,monkeypatch):
    s,r,sid,plan,p=recorded;b=WorkflowBuilder(s.store)
    item=b.build(sid,plan);wid=item["workflow_id"];d=item["definition"];n=[0]
    orig=WorkflowBuilder._validate_uncached
    def wrapped(self,w):n[0]+=1;return orig(self,w)
    monkeypatch.setattr(WorkflowBuilder,"_validate_uncached",wrapped)
    with validation_scope(s.store):
        assert b._validate(wid)["status"]=="offline_pass"
        assert b._validate(wid)["status"]=="offline_pass" and n[0]==1
        if tamper=="annotation":
            r.annotate(sid,plan["steps"][0]["post_event_id"],{"verification":"FAIL","observation":"disputed"})
        elif tamper=="template":
            path=Path(item["bundle_path"])/d["states"][0]["guard"]["template"]["path"]
            path.write_bytes(b"bad")
        elif tamper=="frame":
            fid=next(iter(d["source"]["frame_sha256"]))
            path=s.store.resolve_image_path(s.store.get_frame(fid).image_path);path.write_bytes(b"bad")
        elif tamper=="ref":
            rid=next(iter(d["source"]["ref_sha256"]));path=s.store.store_dir/"refs"/(rid+".json")
            data=json.loads(path.read_text());data["score"]=0.1;path.write_text(json.dumps(data))
        elif tamper=="asset":
            e=r.event(sid,plan["steps"][0]["find_event_id"]);path=s.store.store_dir/e["evidence"]["assets"][0]["retained_path"];path.write_bytes(b"bad")
        else:
            path=Path(item["bundle_path"])/"plan.json";data=json.loads(path.read_text());data["name"]="modified";path.write_text(json.dumps(data))
        with pytest.raises((WorkflowError,ValueError)):b._validate(wid)
        assert n[0]==2

def test_task_validation_not_cross_scope(recorded,monkeypatch):
    s,r,sid,plan,p=recorded;b=WorkflowBuilder(s.store);wid=b.build(sid,plan)["workflow_id"]
    n=[0];orig=WorkflowBuilder._validate_uncached
    def wrapped(self,w):n[0]+=1;return orig(self,w)
    monkeypatch.setattr(WorkflowBuilder,"_validate_uncached",wrapped)
    for _ in range(2):
        with validation_scope(s.store):
            b._validate(wid);b._validate(wid)
    assert n[0]==2
