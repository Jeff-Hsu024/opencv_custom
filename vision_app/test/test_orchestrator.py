"""Orchestrator tests over real Runtime, lifecycle and recovery fixtures."""
import json,subprocess,sys,os
from concurrent.futures import ThreadPoolExecutor
import pytest
from test_workflow import recorded
from test_runtime import prepared
from test_recovery import recovery
from test_lifecycle import registered, linked, F
from vision_app.orchestrator import ExecutionOrchestrator
from vision_app.workflow import WorkflowError

T="task_"+"1"*32
T2="task_"+"2"*32

def engine(linked):
    rt,b,server,p,lc,cb,route,proposal,q=linked
    return ExecutionOrchestrator(server.store,runtime=rt),p

def test_normal_and_duplicate(linked):
    o,p=engine(linked)
    p.state=0;n=len(p.actions)
    t=o.execute(F,T,3,True)
    assert t["status"]=="completed" and not t["recovered"]
    assert [c["role"] for c in t["children"]]==["primary"]
    assert len(p.actions)==n+1
    assert o.execute(F,T,3,True)["duplicate_request"]
    assert len(p.actions)==n+1
    with pytest.raises(WorkflowError,match="another request"):o.execute(F,T,3,False)
    assert o.list()["items"][0]["task_id"]==T

def test_recovery_then_full_restart(linked):
    o,p=engine(linked)
    p.state=1;n=len(p.actions)
    epoch=o.rt.epochs.current("dev")
    click=p.click
    epochs=[]
    def contend():
        with o.rt.epochs.device_owner("dev",timeout=0) as owner:
            return owner is None
    with ThreadPoolExecutor(max_workers=1) as pool:
        def record_owner(x,y):
            assert pool.submit(contend).result(timeout=5)
            epochs.append(o.rt.epochs.current("dev"))
            return click(x,y)
        p.click=record_owner
        t=o.execute(F,T,3,True)
    assert t["status"]=="completed" and t["recovered"]
    assert [c["role"] for c in t["children"]]==["primary","recovery","restart"]
    assert [c["receipt"]["status"] for c in t["children"]]==["needs_agent","completed","completed"]
    assert t["selection"]["status"]=="selected" and t["recovery_endpoint"]["state"]=="a"
    assert len(p.actions)==n+2
    assert epochs==[epoch+1,epoch+2]
    assert o.execute(F,T,3,True)["duplicate_request"] and len(p.actions)==n+2

@pytest.mark.parametrize("mode",["disabled_policy","disabled_route","unknown","uncertain","ambiguous","unsafe_endpoint"])
def test_handoff_no_retry(linked,mode,monkeypatch):
    o,p=engine(linked);p.state=1;n=len(p.actions);generation=3
    if mode=="disabled_route":
        route=linked[6]
        o.lc.route_status(F,route["route_id"],False,3,"disable")
        generation=4
    elif mode=="unknown":p.images[1][:]=0
    elif mode=="uncertain":
        p.state=0
        def click(x,y):p.actions.append(("click",x,y));return False
        p.click=click
    elif mode in ("ambiguous","unsafe_endpoint"):
        real=o.lc._select_locked
        def select(*args):
            r=real(*args)
            if mode=="ambiguous":r.update(status="ambiguous",selected=None)
            else:r["selected"]["destination_state"]="b"
            return r
        monkeypatch.setattr(o.lc,"_select_locked",select)
    t=o.execute(F,T,generation,mode!="disabled_policy")
    assert t["status"]=="needs_agent" and not t["recovered"]
    assert len(t["children"])==1 and t["handoff"]["original_task_completed"] is False
    assert len(p.actions)==n+int(mode=="uncertain")

def test_recovery_failure_not_retried(linked):
    o,p=engine(linked);p.state=1;n=len(p.actions)
    def click(x,y):p.actions.append(("click",x,y));return False
    p.click=click
    t=o.execute(F,T,3,True)
    assert t["status"]=="needs_agent" and t["reason"]["code"]=="RECOVERY_FAILED"
    assert len(t["children"])==2 and len(p.actions)==n+1

def test_restart_failure_not_retried(linked):
    o,p=engine(linked);p.state=1;n=len(p.actions)
    real=p.click
    def click(x,y):
        if p.state==1:return real(x,y)
        p.actions.append(("click",x,y));return False
    p.click=click
    t=o.execute(F,T,3,True)
    assert t["status"]=="needs_agent" and t["reason"]["code"]=="RESTART_FAILED" and t["recovered"]
    assert len(t["children"])==3 and len(p.actions)==n+2

def test_midpath_never_restarts(linked,monkeypatch):
    o,p=engine(linked);p.state=1
    real=o.rt._run_locked
    def run(*args):
        r=real(*args)
        r["completed_steps"]=1
        return r
    monkeypatch.setattr(o.rt,"_run_locked",run)
    t=o.execute(F,T,3,True)
    assert t["status"]=="needs_agent" and len(t["children"])==1 and t["selection"] is None

def test_interrupted_no_replay(linked):
    o,p=engine(linked);p.state=0;n=len(p.actions)
    def click(x,y):p.actions.append(("click",x,y));raise KeyboardInterrupt()
    p.click=click
    with pytest.raises(KeyboardInterrupt):o.execute(F,T,3,True)
    assert o.inspect(T)["status"]=="running"
    other=ExecutionOrchestrator(o.store,runtime=o.rt)
    t=other.execute(F,T,3,True)
    assert t["status"]=="interrupted" and t["duplicate_request"]
    assert t["children"][0]["receipt"]["action_outcome"]=="unknown"
    assert len(p.actions)==n+1

def test_generation_and_collision(linked):
    o,p=engine(linked);p.state=0;n=len(p.actions)
    with pytest.raises(WorkflowError,match="Stale"):o.execute(F,T,2,True)
    rid=o._run_id(T,"restart");path=o.rt._path("runs",rid);path.write_text("{}")
    with pytest.raises(WorkflowError,match="collision"):o.execute(F,T,3,True)
    assert len(p.actions)==n and o.list()["items"]==[]

def test_cli_mcp_inspect_restart(linked):
    o,p=engine(linked);p.state=0
    assert o.execute(F,T,3,False)["status"]=="completed"
    proc=subprocess.run([sys.executable,"-m","vision_app","--store-dir",str(o.store.store_dir),"task","inspect","--task-id",T],capture_output=True,text=True,check=True)
    assert json.loads(proc.stdout)["result"]["status"]=="completed"
    server=linked[2]
    r=server.call_tool("vision_task_inspect",{"task_id":T})
    assert json.loads(r["content"][0]["text"])["result"]["task_id"]==T

def test_concurrent_duplicate_serialized(linked):
    o,p=engine(linked);p.state=0;n=len(p.actions)
    def submit(_):
        return ExecutionOrchestrator(o.store,runtime=o.rt).execute(F,T,3,True)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(submit,range(2)))
    assert all(r["status"]=="completed" for r in results)
    assert sum(bool(r.get("duplicate_request")) for r in results)==1
    assert len(p.actions)==n+1

def test_interrupted_after_recovery_before_restart(linked,monkeypatch):
    o,p=engine(linked);p.state=1;n=len(p.actions)
    original=o._child
    def child(t,role,*args):
        if role=="restart":raise KeyboardInterrupt()
        return original(t,role,*args)
    monkeypatch.setattr(o,"_child",child)
    with pytest.raises(KeyboardInterrupt):o.execute(F,T,3,True)
    result=ExecutionOrchestrator(o.store,runtime=o.rt).execute(F,T,3,True)
    assert result["status"]=="interrupted" and result["recovered"]
    assert result["handoff"]["original_task_completed"] is False
    assert len(result["children"])==2 and len(p.actions)==n+1
