"""Lifecycle regression and recovery routing with actual application services."""
import copy,json,subprocess,sys
import pytest
from test_workflow import recorded
from test_runtime import prepared, PROFILE, RID
from test_recovery import recovery, record_route, RID2
from vision_app.lifecycle import LifecycleService
from vision_app.workflow import WorkflowBuilder, WorkflowError

R3="run_"+"c"*32
R4="run_"+"d"*32
R5="run_"+"e"*32
R6="run_"+"f"*32
F="test-family"

@pytest.fixture
def registered(prepared):
    rt,b,server,p,rec,sid,wid=prepared
    assert rt.run(b["binding_id"],RID)["status"]=="completed"
    lc=LifecycleService(server.store,runtime=rt)
    item=lc.register(F,wid,RID,0,"initial version")
    assert item["family"]["generation"]==1 and item["family"]["active_version"] is None
    return rt,b,server,p,rec,sid,wid,lc

def test_enable_disable_duplicate_and_restart(registered):
    rt,b,server,p,rec,sid,wid,lc=registered
    p.state=0
    count=len(p.actions)
    assert rt.run(b["binding_id"],R3)["reason"]["code"]=="WORKFLOW_INACTIVE"
    assert len(p.actions)==count
    assert rt.run(b["binding_id"],RID)["duplicate_request"] is True
    lc.activate(F,1,1,"enable")
    assert rt.run(b["binding_id"],R4)["status"]=="completed"
    lc.disable(F,2,"disable")
    p.state=0
    assert rt.run(b["binding_id"],R5)["reason"]["code"]=="WORKFLOW_INACTIVE"
    assert len(p.actions)==count+1
    again=LifecycleService(server.store,runtime=rt)
    assert again.inspect(F)["family"]["active_version"] is None
    assert [x["operation"] for x in again.history(F)["items"]]==["register","activate","disable"]
    assert again.history(F,limit=1)["next_cursor"]==1
    assert again.list()["items"][0]["family_id"]==F

def test_rollback_two_versions(registered):
    rt,b,server,p,rec,sid,wid,lc=registered
    lc.activate(F,1,1,"enable v1")
    plan=copy.deepcopy(json.loads((rt.builder.root/wid/"plan.json").read_text()))
    plan["name"]="v2 reviewed"
    child=rt.builder.build(sid,plan)["workflow_id"]
    p.state=0
    cb=rt.qualify(child,"dev",PROFILE)
    assert rt.run(cb["binding_id"],R3)["status"]=="completed"
    lc.register(F,child,R3,2,"reviewed revision",parent_version=1)
    assert lc.inspect(F)["family"]["active_version"]==1
    with pytest.raises(WorkflowError,match="previously active"):lc.rollback(F,2,3,"never active")
    lc.activate(F,2,3,"switch to v2")
    p.state=0
    assert rt.run(b["binding_id"],R4)["reason"]["code"]=="WORKFLOW_INACTIVE"
    lc.rollback(F,1,4,"rollback")
    assert rt.run(b["binding_id"],R5)["status"]=="completed"
    assert lc.inspect(F)["family"]["active_version"]==1
    assert [v["version"] for v in lc.inspect(F)["versions"]["items"]]==[1,2]

def test_stale_generation_and_duplicate_registration(registered):
    rt,b,server,p,rec,sid,wid,lc=registered
    with pytest.raises(WorkflowError,match="Stale"):lc.activate(F,1,0,"stale")
    with pytest.raises(WorkflowError,match="already managed"):lc.register(F,wid,RID,1,"duplicate")
    assert lc.inspect(F)["family"]["generation"]==1

def test_failed_proof_rejected(prepared):
    rt,b,server,p,rec,sid,wid=prepared
    p.state=1
    assert rt.run(b["binding_id"],RID)["status"]=="needs_agent"
    with pytest.raises(WorkflowError,match="completed matching"):LifecycleService(server.store,runtime=rt).register(F,wid,RID,0,"bad")

def test_proof_tamper_rejected(registered):
    rt,b,server,p,rec,sid,wid,lc=registered
    path=rt._path("runs",RID)
    data=json.loads(path.read_text())
    data["finished_at"]+=1
    path.write_text(json.dumps(data))
    with pytest.raises(WorkflowError,match="proof changed"):lc.activate(F,1,1,"tampered")
    assert lc.inspect(F)["family"]["generation"]==1

@pytest.fixture
def linked(recovery):
    rt,b,server,p,rec,sid,wid,svc,case=recovery
    plan,reconcile=record_route(recovery)
    proposal=svc.propose(case["case_id"],"recovery_route","a",reconcile,plan)
    child=proposal["payload"]["child_workflow_id"]
    p.state=1
    cb=rt.qualify(child,"dev",PROFILE)
    assert rt.run(cb["binding_id"],RID2)["status"]=="completed"
    q=svc.verify(proposal["proposal_id"],RID2)
    p.state=0
    assert rt.run(b["binding_id"],R3)["status"]=="completed"
    lc=LifecycleService(server.store,runtime=rt)
    lc.register(F,wid,R3,0,"register")
    lc.activate(F,1,1,"activate")
    result=lc.link(F,1,proposal["proposal_id"],q["qualification_id"],2,"link")
    return rt,b,server,p,lc,cb,result["active_version_routes"][0],proposal,q

def test_select_and_route_disable(linked):
    rt,b,server,p,lc,cb,route,proposal,q=linked
    p.state=1
    before=len(p.actions)
    result=lc.select(F,RID)
    assert result["status"]=="selected" and result["selected"]["route_id"]==route["route_id"]
    assert result["automatic_execution"] is False and len(p.actions)==before
    assert rt.run(cb["binding_id"],R4)["status"]=="completed"
    lc.route_status(F,route["route_id"],False,3,"disable")
    p.state=1
    assert lc.select(F,RID)["status"]=="no_match"
    assert rt.run(cb["binding_id"],R5)["reason"]["code"]=="WORKFLOW_INACTIVE"
    assert len(p.actions)==before+1
    lc.route_status(F,route["route_id"],True,4,"restore")
    lc.disable(F,5,"disable parent")
    assert rt.run(cb["binding_id"],R6)["reason"]["code"]=="WORKFLOW_INACTIVE"

def test_selection_no_match(linked):
    rt,b,server,p,lc,cb,route,proposal,q=linked
    p.state=0
    assert lc.select(F,RID)["status"]=="no_match"

def test_uncertain_requires_review(linked):
    rt,b,server,p,lc,cb,route,proposal,q=linked
    path=rt._path("runs",RID)
    data=json.loads(path.read_text())
    data["action_outcome"]="unknown"
    path.write_text(json.dumps(data))
    assert lc.select(F,RID)["status"]=="manual_review"

def test_route_qualification_tamper_rejected(linked):
    rt,b,server,p,lc,cb,route,proposal,q=linked
    path=rt._path("runs",RID2)
    data=json.loads(path.read_text())
    data["finished_at"]+=1
    path.write_text(json.dumps(data))
    p.state=1
    before=len(p.actions)
    with pytest.raises(WorkflowError,match="qualification changed"):lc.select(F,RID)
    assert len(p.actions)==before

def test_cli_and_mcp_registry(registered):
    rt,b,server,p,rec,sid,wid,lc=registered
    proc=subprocess.run([sys.executable,"-m","vision_app","--store-dir",str(server.store.store_dir),"lifecycle","inspect","--family",F],capture_output=True,text=True,check=True)
    assert json.loads(proc.stdout)["result"]["family"]["generation"]==1
    res=server.call_tool("vision_lifecycle_activate",{"family_id":F,"version":1,"expected_generation":1,"reason":"MCP activation"})
    assert json.loads(res["content"][0]["text"])["result"]["family"]["active_version"]==1

def test_ambiguous_route_selection(linked):
    rt,b,server,p,lc,cb,route,proposal,q=linked
    # A second independently compiled and live-qualified child for the same anchor.
    case=lc.recovery._case(proposal["case_id"])
    plan=json.loads((rt.builder.root/proposal["payload"]["child_workflow_id"]/"plan.json").read_text())
    plan["name"]="alternate reviewed recovery"
    alt=lc.recovery.propose(case["case_id"],"recovery_route","a",proposal["payload"]["reconciliation"],plan)
    p.state=1
    bind=rt.qualify(alt["payload"]["child_workflow_id"],"dev",PROFILE)
    assert rt.run(bind["binding_id"],R4)["status"]=="completed"
    qual=lc.recovery.verify(alt["proposal_id"],R4)
    lc.link(F,1,alt["proposal_id"],qual["qualification_id"],3,"second route")
    p.state=1
    before=len(p.actions)
    result=lc.select(F,RID)
    assert result["status"]=="ambiguous" and result["selected"] is None and len(result["candidates"])==2
    assert len(p.actions)==before

def test_disabled_family_routes_remain_inspectable(linked):
    rt,b,server,p,lc,cb,route,proposal,q=linked
    lc.disable(F,3,"disable")
    assert lc.inspect(F)["active_version_routes"]==[]
    assert lc.inspect(F,parent_version=1)["active_version_routes"][0]["route_id"]==route["route_id"]

def test_managed_profile_mismatch(registered):
    rt,b,server,p,rec,sid,wid,lc=registered
    lc.activate(F,1,1,"enable")
    p.state=0
    other={**PROFILE,"locale":"en-US"}
    rt.probe=lambda d,p:other
    bind=rt.qualify(wid,"dev",other)
    n=len(p.actions)
    r=rt.run(bind["binding_id"],R3)
    assert r["reason"]["code"]=="REGISTRY_PROFILE_MISMATCH" and len(p.actions)==n
