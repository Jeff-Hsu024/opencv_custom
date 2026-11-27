"""Portable family and pinned execution tests with actual fixture proof."""
import pytest

from test_portable_qualification import devices,trial_request,commit_trial,validate_response,ASSERTION
from test_portable_core import published
from test_runtime import prepared,PROFILE,RID
from test_workflow import recorded,Platform
from vision_app.coordinator import task_run_id,ClaimError
from vision_app.observation import OperationError

@pytest.fixture
def admitted_devices(devices):
    svc,record,p,target,profiles,online=devices
    pid=record["portable_id"]
    qa=svc.slots.commit(pid,"dev",0,"source",RID,ASSERTION)
    tr="prun_"+"5"*32
    assert svc.trial(**trial_request(svc,pid,"device-B",tr))["status"]=="completed"
    qb=commit_trial(svc,pid,"device-B",tr,0)
    family=svc.families.publish("test",pid,0,"publish")
    assert family=={"family_id":"test","generation":1,"active_revision":None,
                    "revisions":[{"revision":1,"portable_id":pid}]}
    validate_response("portable_family_publish",family)
    family=svc.families.activate("test",1,1,"enable")
    assert family["generation"]==2
    validate_response("portable_family_activate",family)
    p.state=target.state=0
    return svc,record,p,target,profiles,online,qa,qb

def test_family_namespace_and_pinned_execution(admitted_devices):
    svc,record,p,target,profiles,online,qa,qb=admitted_devices
    pid=record["portable_id"]
    svc.families.publish("other",pid,0,"reuse")
    svc.families.activate("other",1,1,"enable")
    assert svc.slots.inspect(pid,"device-B")["qualification_id"]==qb["qualification_id"]
    assert svc.families.inspect("other")["generation"]==2
    task="ptask_"+"1"*32
    result=svc.admission.execute("test",2,"device-B",task)
    assert result["status"]=="completed",result
    assert result["qualification_id"]==qb["qualification_id"]
    assert result["context"]["device"]=="device-B"
    assert result["run_id"]==task_run_id(task,"device-B")
    validate_response("portable_execute",result)
    validate_response("portable_run_inspect",svc.admission.run_inspect(result["run_id"]))
    validate_response("portable_task_list",svc.admission.task_list())
    count=len(target.actions)
    svc.slots.revoke(pid,"device-B",1,"revoke")
    svc.families.activate("test",None,2,"disable")
    online.remove("device-B")
    assert svc.admission.execute("test",2,"device-B",task,True)=={**result,"duplicate_request":True}
    assert len(target.actions)==count
    with pytest.raises(ClaimError,match="REQUEST_ID_CONFLICT"):
        svc.admission.execute("other",2,"device-B",task)
    with pytest.raises(OperationError,match="inactive"):
        svc.admission.execute("test",3,"dev","ptask_"+"2"*32)

def test_admission_rechecks_qualification_before_atomic_reservation(admitted_devices,monkeypatch):
    svc,record,p,target,profiles,online,qa,qb=admitted_devices
    tid="ptask_"+"3"*32
    old=svc.ledger.admit
    def race(owner,claim,**kwargs):
        svc.slots.revoke(record["portable_id"],"device-B",1,"race before admission")
        return old(owner,claim,**kwargs)
    monkeypatch.setattr(svc.ledger,"admit",race)
    count=len(target.actions)
    with pytest.raises(OperationError,match="changed before admission"):
        svc.admission.execute("test",2,"device-B",tid)
    assert len(target.actions)==count
    with svc.ledger.transaction() as db:
        assert svc.ledger._row(db,tid) is None and svc.ledger._row(db,task_run_id(tid,"device-B")) is None

def test_admitted_context_survives_family_disable_and_revoke(admitted_devices,monkeypatch):
    svc,record,p,target,profiles,online,qa,qb=admitted_devices
    old=svc.admission.run_task_owned
    def race(resolved,plan,owner,**kwargs):
        svc.slots.revoke(record["portable_id"],"device-B",1,"after admission")
        svc.families.activate("test",None,2,"after admission")
        return old(resolved,plan,owner,**kwargs)
    monkeypatch.setattr(svc.admission,"run_task_owned",race)
    result=svc.admission.execute("test",2,"device-B","ptask_"+"4"*32)
    assert result["status"]=="completed" and result["qualification_id"]==qb["qualification_id"]
    assert svc.slots.inspect(record["portable_id"],"device-B")["status"]=="revoked"
    assert svc.families.inspect("test")["active_revision"] is None

def test_task_owner_crash_reconciles_nested_run_without_replay(admitted_devices):
    svc,record,p,target,profiles,online,qa,qb=admitted_devices
    tid="ptask_"+"5"*32
    before=len(target.actions)
    def crash(x,y):
        target.actions.append(("click",x,y))
        raise KeyboardInterrupt()
    target.click=crash
    with pytest.raises(KeyboardInterrupt):
        svc.admission.execute("test",2,"device-B",tid)
    run=svc.admission.run_inspect(task_run_id(tid,"device-B"))
    task=svc.admission.task_inspect(tid)
    assert run["status"]==task["status"]=="interrupted"
    assert run["action_outcome"]==task["action_outcome"]=="unknown"
    assert run["last_frame_id"] is None
    assert svc.admission.execute("test",2,"device-B",tid)=={**task,"duplicate_request":True}
    assert len(target.actions)==before+1
