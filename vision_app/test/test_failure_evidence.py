"""Phase 8.1 failure evidence: no pre-click image masquerading as current."""
import base64
import json
import time
from pathlib import Path
import numpy as np
import pytest

from test_transition import env,T
from test_workflow import call
from test_waits_cli import _FakeClock, _SequencePlatform, _solid_frame
from vision_app.waits import WaitService,WaitFailure
from vision_app.store import FrameStore
from vision_app.assets import AssetRegistry
from vision_app.cli import run_cli
from vision_app.transition import TransitionService
from vision_app.runtime import RuntimeFault
from vision_app.mcp_server import _tool_definitions

@pytest.mark.parametrize("mode",["changed","stable","image"])
@pytest.mark.parametrize("termination",["cap","deadline"])
def test_wait_retains_last_full_frame(tmp_path,mode,termination):
    store=FrameStore(tmp_path);clock=_FakeClock()
    base=_solid_frame()
    final=base.copy();final[0:4,0:4]=(200,100,50) # outside ROI
    # Random template never matches constant ROI.
    tpl=np.random.default_rng(41).integers(0,256,(10,10,3),dtype=np.uint8)
    registry=AssetRegistry(store.store_dir)
    src=store.save_frame(tpl,"dev")
    registry.register_from_frame("absent",store,src.frame_id)
    p=_SequencePlatform([base,final])
    svc=WaitService(store,platform_factory=lambda _:p,clock=clock,sleeper=clock.sleep)
    kw=dict(region=(20,20,60,60),timeout=5 if termination=="cap" else .6,interval=.5,max_captures=2 if termination=="cap" else 10)
    if mode=="stable":kw["stable_duration"]=10
    if mode=="image":kw.update(target_name="absent",threshold=.999)
    start=time.time()
    with pytest.raises(WaitFailure) as ei:getattr(svc,"wait_"+mode)("dev",**kw)
    e=ei.value;o=e.observation
    assert e.code=="WAIT_TIMEOUT" and e.exit_code==4 and not o["verified"] and o["status"]=="timeout"
    assert o["captures"]==p.calls and o["captures"]>=2
    assert start<=o["last_capture_timestamp"]<=time.time()
    rec=store.get_frame(o["frame_id"],device_id="dev")
    assert rec.timestamp==o["last_capture_timestamp"] and rec.width==100 and rec.height==80
    assert np.array_equal(store.load_image(rec.frame_id),final)
    assert len(list((tmp_path/"frames").glob("*.png")))==2 # source template + final only

@pytest.mark.parametrize("first", [True,False])
def test_capture_failure_retains_only_actual_samples(tmp_path,first):
    store=FrameStore(tmp_path);base=store.save_frame(_solid_frame(),"dev")
    actual=_solid_frame(bgr=(40,50,60))
    class P:
        calls=0
        def snapshot(self):
            self.calls+=1
            if first or self.calls>1:raise RuntimeError("capture stopped")
            return actual.copy()
    p=P();c=_FakeClock()
    w=WaitService(store,platform_factory=lambda _:p,clock=c,sleeper=c.sleep)
    with pytest.raises(WaitFailure) as ei:
        w.wait_changed("dev",baseline_frame_id=base.frame_id,min_changed_ratio=1,region=(20,20,60,60),pixel_tolerance=255,timeout=5)
    o=ei.value.observation
    assert ei.value.code=="CAPTURE_FAILED"
    assert o["captures"]==(0 if first else 1)
    if first:
        assert o["frame_id"] is None and o["artifact"] is None and o["last_capture_timestamp"] is None
    else:
        assert o["frame_id"]!=base.frame_id
        assert np.array_equal(store.load_image(o["frame_id"]),actual)

def test_fresh_baseline_timeout(tmp_path):
    store=FrameStore(tmp_path);p=_SequencePlatform([_solid_frame()])
    w=WaitService(store,platform_factory=lambda _:p)
    with pytest.raises(WaitFailure) as ei:w.wait_changed("dev",max_captures=1)
    assert ei.value.observation["capture_role"]=="fresh_baseline"
    assert ei.value.observation["captures"]==1 and ei.value.observation["frame_id"]

def test_recognition_failure_retains_valid_capture(env,monkeypatch):
    p,s,r,sid,args=env
    from service.core.opencv.open_cv_service import OpenCvService
    def bad(*a,**kw):raise RuntimeError("recognition failure")
    monkeypatch.setattr(OpenCvService,"match_template",bad)
    out=call(s,"wait",device="dev",mode="image",target="button",session_id=sid,timeout=.1)
    assert not out["ok"] and out["error"]["code"]=="WAIT_EVALUATION_FAILED"
    o=out["operation_result"];assert o["captures"]==1 and not o["verified"]
    ev=r.event(sid,out["event_id"])
    assert ev["status"]=="failed" and o["frame_id"] in ev["evidence"]["frames"]
    assert s.store.get_frame(o["frame_id"]).protected

@pytest.mark.parametrize("mode",["changed","stable","image"])
@pytest.mark.parametrize("recorded", [True,False])
def test_cli_mcp_failed_wait_parity(env,capsys,mode,recorded):
    p,s,r,sid,args=env;p.state=1
    fid=call(s,"snapshot",device="dev")["frame"]["frame_id"]
    kw={"device":"dev","mode":mode,"timeout":.05,"max_captures":1}
    flags=["--"+mode]
    if mode=="changed":kw["baseline_frame_id"]=fid;flags+=["--baseline",fid]
    if mode=="stable":kw["stable_duration"]=10;flags+=["--stable-duration","10"]
    if mode=="image":kw.update(target="button",threshold=.999);flags+=["button","--threshold",".999"]
    if recorded:kw["session_id"]=sid
    res=s.call_tool("vision_wait",kw)
    assert res["isError"] is True
    a=json.loads(next(x["text"] for x in res["content"] if x["type"]=="text"))
    av=["--store-dir",str(s.store.store_dir)]+(["--session",sid] if recorded else [])+["wait","--device","dev","--timeout",".05","--max-captures","1",*flags,"--json"]
    assert run_cli(av,service=s.obs)==4
    b=json.loads(capsys.readouterr().out)
    for x in (a,b):
        assert not x["ok"] and x["error"]["code"]=="WAIT_TIMEOUT"
        o=x["operation_result"];assert o["captures"]==1 and not o["verified"] and o["frame_id"]!=fid
        assert np.array_equal(s.store.load_image(o["frame_id"]),p.images[1])
        if recorded:
            ev=r.event(sid,x["event_id"])
            assert ev["status"]=="timeout" and o["frame_id"] in ev["evidence"]["frames"]
            assert s.store.get_frame(o["frame_id"]).protected
    assert not p.actions

@pytest.mark.parametrize("mode",["image","changed"])
def test_transition_timeout_observation(env,mode):
    p,s,r,sid,args=env
    if mode=="image":args["postcondition"]={"mode":"image","target":"button","timeout":.05,"threshold":.999}
    else:
        p.images[1][2:10,2:10]=p.images[0][2:10,2:10]
        args["postcondition"]={"mode":"changed","timeout":.05,"region":[2,2,10,10],"min_changed_ratio":1.0}
    args["return_image"]=True
    res=s.call_tool("vision_transition",args)
    t=json.loads(next(x["text"] for x in res["content"] if x["type"]=="text"))["result"]
    assert t["status"]=="needs_agent" and t["reason"]["code"]=="WAIT_TIMEOUT"
    assert t["action_outcome"]=="executed_unverified" and t["semantic_verification"]=="UNKNOWN"
    assert t["pre_frame_id"]!=t["last_observed_frame_id"]==t["last_frame_id"] and t["post_frame_id"] is None
    assert t["observation_phase"]=="post_action" and t["wait"]["status"]=="timeout"
    ev=r.event(sid,t["events"]["wait"]);o=ev["result"]["operation_result"]
    assert ev["status"]=="timeout" and o["frame_id"]==t["last_frame_id"] in ev["evidence"]["frames"]
    assert np.array_equal(s.store.load_image(o["frame_id"]),p.images[1])
    assert base64.b64decode(next(x["data"] for x in res["content"] if x["type"]=="image"))==Path(t["artifact"]["path"]).read_bytes()
    assert call(s,"transition",**args)["result"]["duplicate_request"] and len(p.actions)==1

def test_transition_no_post_capture(env):
    p,s,r,sid,args=env
    def capture():
        if p.actions:raise RuntimeError("offline")
        return p.images[0].copy()
    p.snapshot=capture;args["return_image"]=True
    res=s.call_tool("vision_transition",args)
    assert [x["type"] for x in res["content"]]==["text"]
    t=json.loads(res["content"][0]["text"])["result"]
    assert t["status"]=="needs_agent" and t["reason"]["code"]=="CAPTURE_FAILED"
    assert t["pre_frame_id"] and t["last_frame_id"] is None and t["last_observed_frame_id"] is None
    assert t["artifact"] is None and t["post_frame_id"] is None and t["observation_phase"]=="post_action_unknown"
    assert t["wait"]["captures"]==0 and len(p.actions)==1

def test_transition_reconcile_durable_failed_wait(env,monkeypatch):
    p,s,r,sid,args=env
    args["postcondition"]={"mode":"image","target":"button","threshold":.999,"timeout":.05}
    svc=TransitionService(s.store,observation=s.obs,matcher=s.matcher,actions=s.actions,waits=s.waits)
    original=svc._save
    def crash(t):
        if t["events"].get("wait") and t["status"]=="running":raise KeyboardInterrupt()
        original(t)
    monkeypatch.setattr(svc,"_save",crash)
    with pytest.raises(KeyboardInterrupt):svc.execute(**args)
    t=call(s,"transition",**args)["result"]
    assert t["status"]=="interrupted" and t["duplicate_request"] and len(p.actions)==1
    assert t["last_frame_id"]!=t["pre_frame_id"] and t["observation_phase"]=="post_action"
    assert t["wait"]["status"]=="timeout"

def test_pending_click_clears_observation(env):
    p,s,r,sid,args=env
    def click(x,y):p.actions.append((x,y));raise KeyboardInterrupt()
    p.click=click
    with pytest.raises(KeyboardInterrupt):call(s,"transition",**args)
    t=call(s,"transition",**args)["result"]
    assert t["status"]=="interrupted" and t["action_outcome"]=="unknown"
    assert t["pre_frame_id"] and t["last_frame_id"] is None and t["artifact"] is None
    assert t["observation_phase"]=="post_action_unknown" and len(p.actions)==1

def test_legacy_failure_projection_no_rewrite(env):
    p,s,r,sid,args=env
    args["postcondition"]={"mode":"image","target":"button","threshold":.999,"timeout":.05}
    t=call(s,"transition",**args)["result"]
    # Emulate old receipt and missing failure evidence in test-only DB.
    path=s.store.store_dir/"transitions"/(T+".json")
    pre=t["pre_frame_id"]
    for k in ("observation_phase","pre_frame_id","post_frame_id","last_observed_frame_id","last_capture_timestamp"):t.pop(k)
    t["last_frame_id"]=pre;t["artifact"]={"path":"old"}
    path.write_text(json.dumps(t));old=path.read_bytes()
    ev=r.event(sid,t["events"]["wait"]);data=ev["result"];data["operation_result"]=None
    with r.db() as db:db.execute("UPDATE events SET result=? WHERE event_id=?",(json.dumps(data),ev["event_id"]))
    out=call(s,"transition_inspect",transition_id=T)["result"]
    assert out["legacy_receipt"] and out["pre_frame_id"]==pre and out["last_frame_id"] is None
    assert out["artifact"] is None and path.read_bytes()==old

def test_profile_probe_adapters(env,monkeypatch,capsys):
    p,s,r,sid,args=env
    profile={"package":"com.test.app","version_code":123,"rotation":1,"locale":"zh-Hant-TW","ui_mode":"0x21"}
    seen=[]
    def probe(d,pkg):seen.append((d,pkg));return profile
    monkeypatch.setattr("vision_app.runtime.adb_profile",probe)
    schema=next(t for t in _tool_definitions() if t["name"]=="vision_runtime_probe_profile")
    assert set(schema["inputSchema"]["required"])=={"device","package"}
    assert call(s,"runtime_probe_profile",device="dev",package=profile["package"])["result"]==profile
    assert run_cli(["--store-dir",str(s.store.store_dir),"runtime","probe-profile","--device","dev","--package",profile["package"]],service=s.obs)==0
    assert json.loads(capsys.readouterr().out)["result"]==profile and len(seen)==2
    assert not p.actions and not list((s.store.store_dir/"runtime").rglob("*.json"))
    assert call(s,"runtime_probe_profile",device="desktop",package=profile["package"])["error"]["code"]=="INVALID_DEVICE"
    assert call(s,"runtime_probe_profile",device="dev",package="invalid")["error"]["code"]=="INVALID_PACKAGE"
    assert call(s,"runtime_probe_profile",device="dev",package="com.other.app")["error"]["code"]=="APP_MISMATCH"

def test_precise_errors(env):
    p,s,r,sid,args=env
    event=r.events(sid)["items"][0]["event_id"]
    assert call(s,"record_annotate",session_id="ses_missing",event_id=event,annotation={"verification":"PASS"})["error"]["code"]=="SESSION_NOT_FOUND"
    assert call(s,"record_annotate",session_id=sid,event_id="evt_missing",annotation={"verification":"PASS"})["error"]["code"]=="EVENT_NOT_FOUND"
    p.images[0][60:80,110:130]=p.images[0][60:80,80:100]
    out=call(s,"transition",**args)["result"]
    assert out["reason"]["code"]=="TARGET_AMBIGUOUS" and out["reason"]["match_count"]==2 and not p.actions
    assert not r.annotations(sid)["items"]


def test_wait_retention_failure_does_not_claim_artifact(env,monkeypatch):
    p,s,r,sid,args=env
    def bad(*a,**kw):raise OSError("disk failure")
    # Wait receives valid pixels, but persistence cannot complete.
    p.state=1
    monkeypatch.setattr(s.store,"save_frame",bad)
    out=call(s,"wait",device="dev",mode="image",target="button",threshold=.999,
             timeout=.05,max_captures=1,session_id=sid)
    o=out["operation_result"]
    assert out["error"]["code"]=="WAIT_TIMEOUT" and o["captures"]==1
    assert o["retention_error"]=="FRAME_RETENTION_FAILED" and o["frame_id"] is None and o["artifact"] is None
    ev=r.event(sid,out["event_id"])
    assert ev["status"]=="timeout" and o==ev["result"]["operation_result"]

def test_failed_wait_cross_device_evidence_rejected(env,monkeypatch):
    p,s,r,sid,args=env
    from vision_app.observation import OperationError
    foreign=s.store.save_frame(p.images[1],"other-device")
    def bad(*a,**kw):
        raise WaitFailure(OperationError("WAIT_TIMEOUT","fixture",exit_code=4),
            {"device_id":"other-device","frame_id":foreign.frame_id,"artifact":{"path":"foreign"},"verified":False})
    monkeypatch.setattr(s.waits,"wait_changed",bad)
    out=call(s,"wait",device="dev",mode="changed",session_id=sid)
    assert out["error"]["code"]=="SESSION_SCOPE_MISMATCH"
    assert out["operation_result"] is None
    ev=r.event(sid,out["event_id"])
    assert foreign.frame_id not in ev["evidence"]["frames"] and not s.store.get_frame(foreign.frame_id).protected

def test_failed_final_snapshot_keeps_only_real_post_action_wait_frame(env,monkeypatch):
    p,s,r,sid,args=env
    orig=s.obs.snapshot
    count=[0]
    def capture(*a,**kw):
        count[0]+=1
        if count[0]>1:raise RuntimeError("capture failed")
        return orig(*a,**kw)
    monkeypatch.setattr(s.obs,"snapshot",capture)
    out=call(s,"transition",**args)["result"]
    assert out["status"]=="needs_agent" and out["post_frame_id"] is None
    assert out["last_observed_frame_id"]==out["wait"]["frame_id"]!=out["pre_frame_id"]
    assert out["observation_phase"]=="post_action" and out["semantic_verification"]=="UNKNOWN"
    assert np.array_equal(s.store.load_image(out["last_frame_id"]),p.images[1])
    assert len(p.actions)==1
