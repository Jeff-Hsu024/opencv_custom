"""Batch admission, bounded overlap and crash reconciliation through real OS owners."""
from contextlib import ExitStack
import json
import queue
import threading
import time

import pytest

from test_portable_admission import admitted_devices
from test_portable_qualification import devices,trial_request,commit_trial,validate_response,ASSERTION
from test_portable_core import published
from test_runtime import prepared,PROFILE,RID
from test_workflow import recorded,Platform
from vision_app.coordinator import ClaimError,child_task_id,task_run_id
from vision_app.observation import OperationError
from vision_app.portable_batch import aggregate
from vision_app.test.test_coordinator import worker

BID="batch_"+"6"*32

def read_messages(process):
    messages=queue.Queue()
    def read():
        for line in process.stdout:
            messages.put(line.strip())
    threading.Thread(target=read,daemon=True).start()
    return messages

def test_atomic_rejection_and_collision(admitted_devices):
    svc,record,p,target,profiles,online,qa,qb=admitted_devices
    before=(len(p.actions),len(target.actions))
    with pytest.raises(OperationError,match="Invalid request shape"):
        svc.batches.batch_execute(BID,"test",2,["dev","dev"])
    with pytest.raises(OperationError,match="unavailable"):
        svc.batches.batch_execute(BID,"test",2,["dev","unknown"])
    svc.slots.revoke(record["portable_id"],"device-B",1,"unqualified")
    with pytest.raises(OperationError,match="inactive"):
        svc.batches.batch_execute(BID,"test",2,["dev","device-B"])
    assert (len(p.actions),len(target.actions))==before
    with svc.ledger.transaction() as db:
        assert svc.ledger._row(db,BID) is None
        assert all(svc.ledger._row(db,child_task_id(BID,d)) is None for d in ("dev","device-B"))
    # A real prior standalone task owns the deterministic child ID.
    tid=child_task_id(BID,"dev")
    assert svc.admission.execute("test",2,"dev",tid)["status"]=="completed"
    p.state=0
    before=(len(p.actions),len(target.actions))
    with pytest.raises(ClaimError,match="REQUEST_ID_CONFLICT"):
        svc.batches.batch_execute(BID,"test",2,["dev"])
    assert (len(p.actions),len(target.actions))==before
    with svc.ledger.transaction() as db:
        assert svc.ledger._row(db,BID) is None

def test_batch_subprocess_overlap_pending_receipts_and_duplicate(admitted_devices):
    svc,record,p,target,profiles,online,qa,qb=admitted_devices
    body="""
import json, threading
from vision_app.store import FrameStore
from vision_app.observation import ObservationService
from vision_app.runtime import WorkflowRuntime
from vision_app.portable_service import PortableService
from vision_app.test.test_workflow import Platform
profile=json.loads(sys.argv[2]); bid=sys.argv[3]
release=threading.Event()
class Blocking(Platform):
    def __init__(self,serial):
        super().__init__()
        self.serial=serial
    def click(self,x,y):
        print("effect:"+self.serial,flush=True)
        assert release.wait(30)
        return super().click(x,y)
platforms={d:Blocking(d) for d in ("dev","device-B")}
store=FrameStore(sys.argv[1])
obs=ObservationService(store,platform_factory=lambda d:platforms[d])
obs.android_devices=lambda:{"devices":[{"device_id":d,"platform":"adb"} for d in platforms]}
runtime=WorkflowRuntime(store,observation=obs,probe=lambda *_:profile)
svc=PortableService(store,runtime=runtime)
def unblock():
    sys.stdin.readline()
    release.set()
print("ready",flush=True)
threading.Thread(target=unblock,daemon=True).start()
result=svc.batches.batch_execute(bid,"test",2,["dev","device-B"],2)
print(json.dumps(result),flush=True)
"""
    with worker(svc.store.store_dir,body,json.dumps(PROFILE),BID) as process:
        msgs=read_messages(process)
        assert {msgs.get(timeout=30),msgs.get(timeout=30)}=={"effect:dev","effect:device-B"}
        live=svc.batches.batch_inspect(BID)
        assert live["status"]=="in_progress" and live["counts"]["in_progress"]==2
        assert all(c["action_outcome"]=="unknown" for c in live["children"])
        for c in live["children"]:
            run=svc.admission.run_inspect(c["run_id"])
            assert run["action_outcome"]=="unknown" and run["last_frame_id"] is None
        duplicate=svc.batches.batch_execute(BID,"test",2,["dev","device-B"],2)
        assert duplicate["duplicate_request"] and duplicate["status"]=="in_progress"
        process.stdin.write("release\n");process.stdin.flush()
        result=json.loads(msgs.get(timeout=30))
        assert process.wait(timeout=20)==0
    assert result["status"]=="completed" and result["counts"]["completed"]==2
    validate_response("portable_batch_execute",result)
    validate_response("portable_batch_list",svc.batches.batch_list())
    assert svc.batches.batch_inspect(BID)==result
    online.clear()
    assert svc.batches.batch_execute(BID,"test",2,["dev","device-B"],2)=={**result,"duplicate_request":True}
    assert [c["device"] for c in result["children"]]==["dev","device-B"]
    for child in result["children"]:
        task=svc.admission.task_inspect(child["task_id"])
        assert all(svc.store.get_frame(s["pre_frame_id"]).device_id==child["device"] for s in task["steps"])

def test_batch_bound_and_isolated_failure(admitted_devices):
    svc,record,p,target,profiles,online,qa,qb=admitted_devices
    active=0; peak=0; order=[]
    lock=threading.Lock()
    def tracked(platform,serial):
        original=platform.click
        def click(x,y):
            nonlocal active,peak
            with lock:
                active+=1;peak=max(peak,active);order.append(serial)
            try:
                time.sleep(.05)
                if serial=="device-B":
                    platform.actions.append(("click",x,y))
                    return False
                return original(x,y)
            finally:
                with lock:active-=1
        return click
    p.click=tracked(p,"dev");target.click=tracked(target,"device-B")
    result=svc.batches.batch_execute(BID,"test",2,["dev","device-B"],1)
    assert peak==1 and order==["dev","device-B"]
    assert result["status"]=="partial" and result["counts"]["completed"]==1
    assert result["children"][1]["action_outcome"]=="unknown"
    validate_response("portable_batch_execute",result)

def test_dead_parent_live_child_never_reconciled(admitted_devices):
    svc,record,p,target,profiles,online,qa,qb=admitted_devices
    req={"batch_id":BID,"family_id":"test","expected_generation":2,"devices":["dev","device-B"],"max_concurrency":2}
    parent_body="""
import json
from vision_app.store import FrameStore
from vision_app.observation import ObservationService
from vision_app.runtime import WorkflowRuntime
from vision_app.portable_service import PortableService
store=FrameStore(sys.argv[1])
obs=ObservationService(store)
obs.android_devices=lambda:{"devices":[{"device_id":d,"platform":"adb"} for d in ("dev","device-B")]}
svc=PortableService(store,runtime=WorkflowRuntime(store,observation=obs))
req=json.loads(sys.argv[2])
with svc.ledger.request_owner(req["batch_id"],parent=True) as owner:
    duplicate,resolved,plans=svc.batches._admit(owner,req)
    assert duplicate is None
    print("ready")
    sys.stdin.readline()
"""
    child_body="""
import json
from vision_app.store import FrameStore
from vision_app.observation import ObservationService
from vision_app.runtime import WorkflowRuntime
from vision_app.portable_service import PortableService
from vision_app.definition_core import ExecutionContext
from vision_app.test.test_workflow import Platform
tid,bid,pid,profile=sys.argv[2:]
profile=json.loads(profile)
class Paused(Platform):
    def click(self,x,y):
        print("ready")
        sys.stdin.readline()
        return super().click(x,y)
store=FrameStore(sys.argv[1]);p=Paused()
obs=ObservationService(store,platform_factory=lambda _:p)
obs.android_devices=lambda:{"devices":[{"device_id":"dev","platform":"adb"}]}
svc=PortableService(store,runtime=WorkflowRuntime(store,observation=obs,probe=lambda *_:profile))
task=svc.ledger.inspect(tid)
run=svc.ledger.inspect(task["run_id"])
resolved=svc.definitions.resolve(pid)
context=ExecutionContext.create(resolved,"portable_run","dev",profile,run["id"],qualification_id=task["qualification_id"])
with svc.ledger.request_owner(tid) as owner:
    assert svc.ledger.start_reserved(owner,bid)
    svc.admission.run_task_owned(resolved,(context,task,run),owner,nested_started=True)
"""
    tid=child_task_id(BID,"dev")
    with worker(svc.store.store_dir,parent_body,json.dumps(req)) as parent:
        assert svc.batches.batch_inspect(BID)["status"]=="in_progress"
        with pytest.raises(ClaimError,match="ID_RESERVED"):
            svc.admission.execute("test",2,"dev",tid)
        with worker(svc.store.store_dir,child_body,tid,BID,record["portable_id"],json.dumps(PROFILE)) as child:
            parent.kill();parent.wait(timeout=15)
            # Windows OS release may lag process termination briefly.
            for _ in range(20):
                recovered=svc.batches.batch_inspect(BID)
                if recovered["phase"]=="reconciling":break
                time.sleep(.05)
            assert recovered["phase"]=="reconciling" and recovered["status"]=="in_progress"
            assert recovered["children"][0]["status"]=="in_progress"
            assert recovered["children"][0]["action_outcome"]=="unknown"
            assert recovered["children"][1]["status"]=="not_attempted"
            child.kill();child.wait(timeout=15)
        for _ in range(20):
            final=svc.batches.batch_inspect(BID)
            if final["status"]=="interrupted":break
            time.sleep(.05)
    assert final["status"]=="interrupted" and final["phase"]=="terminal"
    assert final["children"][0]["status"]=="interrupted" and final["children"][0]["action_outcome"]=="unknown"
    assert final["children"][1]["status"]=="not_attempted"
    validate_response("portable_batch_inspect",final)
    assert svc.batches.batch_execute(**req)=={**final,"duplicate_request":True}
    with svc.ledger.transaction() as db:
        assert db.execute("PRAGMA integrity_check").fetchone()[0]=="ok"

@pytest.mark.parametrize("statuses,abandoned,expected",[
    (["completed","completed"],False,"completed"),
    (["completed","busy"],False,"partial"),
    (["rejected","needs_agent"],False,"needs_agent"),
    (["completed","not_attempted"],True,"interrupted"),
    (["interrupted","not_attempted"],True,"interrupted"),
    (["in_progress","not_attempted"],True,"in_progress")])
def test_aggregate_truth_table(statuses,abandoned,expected):
    status,counts=aggregate([{"status":s} for s in statuses],abandoned=abandoned)
    assert status==expected and sum(counts.values())==len(statuses)
