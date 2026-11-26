"""Recorder acceptance: durable receipts, scope, evidence and real process transport."""
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pytest

from vision_app.cli import run_cli
from vision_app.mcp_server import VisionMcpServer
from vision_app.observation import ObservationService
from vision_app.recorder import Recorder, RecorderError
from vision_app.store import FrameStore

class Fake:
    def __init__(self):
        self.image = np.random.default_rng(12).integers(0,256,(100,120,3),dtype=np.uint8)
        self.calls = []
    def snapshot(self):
        return self.image.copy()
    def click(self,x,y):
        self.calls.append((x,y))
        return True
    def type_text(self,text):
        raise RuntimeError("raw secret: "+text)
    def key_event(self,key):
        raise TimeoutError("timeout")
    def swipe(self,*args,**kwargs):
        return False

def mcp(server,tool,**args):
    r=server.call_tool("vision_"+tool,args)
    return json.loads(next(c["text"] for c in r["content"] if c["type"]=="text"))

@pytest.fixture
def env(tmp_path):
    fake=Fake()
    server=VisionMcpServer(tmp_path,platform_factory=lambda d:fake)
    rec=Recorder(server.store)
    sid=rec.start("explore","test goal","dev")["session_id"]
    return server,rec,sid,fake

def test_lifecycle_and_isolation(env):
    server,rec,sid,fake=env
    other=rec.start("other","other goal","other")["session_id"]
    assert rec.status(sid)["status"]=="active"
    rec.transition(sid,"pause")
    assert not mcp(server,"snapshot",device="dev",session_id=sid)["ok"]
    assert rec.events(sid)["items"]==[]
    rec.transition(sid,"resume")
    assert not mcp(server,"snapshot",device="other",session_id=sid)["ok"]
    assert mcp(server,"snapshot",device="other",session_id=other)["ok"]
    assert rec.events(sid)["items"][0]["status"]=="failed"
    assert len(rec.events(other)["items"])==1
    rec.transition(sid,"stop")
    with pytest.raises(RecorderError): rec.transition(sid,"resume")
    assert Recorder(FrameStore(server.store.store_dir)).status(sid)["status"]=="stopped"

def test_success_fail_timeout_and_redaction(env):
    server,rec,sid,fake=env
    snap=mcp(server,"snapshot",device="dev",session_id=sid)
    fid=snap["frame"]["frame_id"]
    click=mcp(server,"click",device="dev",frame_id=fid,point=[10,20],session_id=sid)
    assert click["ok"] and click["verified"] is False
    assert fake.calls==[(10,20)]
    assert not mcp(server,"type",device="dev",text="very-private-secret",session_id=sid)["ok"]
    assert not mcp(server,"key",device="dev",key="4",session_id=sid)["ok"]
    assert not mcp(server,"swipe",device="dev",from_point=[0,0],to_point=[10,10],session_id=sid)["ok"]
    assert not mcp(server,"wait",device="dev",mode="changed",timeout=0,session_id=sid)["ok"]
    assert not mcp(server,"crop",frame_id=fid,region=[0,0,999,999],session_id=sid)["ok"]
    counts=rec.summary(sid)["event_counts"]
    assert counts=={"success":2,"failed":3,"timeout":2}
    assert b"very-private-secret" not in rec.path.read_bytes()
    assert rec.event(sid,click["event_id"])["evidence"]["frames"]==[fid]
    assert rec.event(sid,click["event_id"])["result"]["verified"] is False

def test_evidence_and_asset_revision(env):
    server,rec,sid,fake=env
    store=server.store
    store.max_frames=1
    snap=mcp(server,"snapshot",device="dev",session_id=sid)
    fid=snap["frame"]["frame_id"]
    crop=mcp(server,"crop",frame_id=fid,region=[0,0,20,20],session_id=sid)
    cid=crop["frame"]["frame_id"]
    a=mcp(server,"assets_register",name="target",frame_id=cid,session_id=sid)
    first=rec.event(sid,a["event_id"])["evidence"]["assets"][0]
    p=store.store_dir/first["retained_path"]
    old=p.read_bytes()
    a2=mcp(server,"assets_register",name="target",frame_id=fid,region=[20,20,40,40],session_id=sid)
    revisions=rec.event(sid,a2["event_id"])["evidence"]["assets"]
    assert len(revisions)==2 and revisions[1]["sha256"]!=first["sha256"]
    assert p.read_bytes()==old
    assert store.cleanup(now=10**12)==[]
    assert store.load_image(cid).shape==(20,20,3)
    # Protected evidence does not consume transient frame capacity.
    normal=mcp(server,"snapshot",device="dev")
    assert store.get_frame(normal["frame"]["frame_id"]).protected is False

def test_pagination_annotation_and_resume(env):
    server,rec,sid,fake=env
    for _ in range(6): mcp(server,"snapshot",device="dev",session_id=sid)
    p=rec.events(sid,limit=2)
    assert [e["sequence"] for e in p["items"]]==[1,2]
    assert [e["sequence"] for e in rec.events(sid,after=p["next_cursor"],limit=2)["items"]]==[3,4]
    assert len(rec.events(sid,operation="snapshot",status="success")["items"])==6
    event=p["items"][0]["event_id"]
    ann=rec.annotate(sid,event,{"state":"聲音設定","verification":"PASS","completed_steps":["one"],"next_step":"two"},kind="checkpoint")
    for i in range(4): rec.annotate(sid,event,{"verification":"UNKNOWN","insight":str(i)})
    resume=rec.resume_context(sid,limit=1)
    assert resume["latest_verified_annotation"]["annotation_id"]==ann["annotation_id"]
    assert resume["latest_checkpoint"]["annotation"]["state"]=="聲音設定"
    assert len(resume["recent_events"])==1
    assert rec.history(sid,limit=1)["items"][0]["frames"]
    assert len(rec.annotations(sid,limit=2)["items"])==2
    with pytest.raises(RecorderError): rec.events(sid,limit=51)
    with pytest.raises(RecorderError): rec.annotate(sid,"wrong",{"state":"bad"})
    with pytest.raises(RecorderError): rec.annotate(sid,event,{"verification":"maybe"})

def test_concurrent_sessions(env):
    server,rec,sid,fake=env
    other=rec.start("other","other goal","dev")["session_id"]
    def work(i):
        s=sid if i%2 else other
        client=VisionMcpServer(server.store.store_dir,platform_factory=lambda _:fake)
        return mcp(client,"snapshot",device="dev",session_id=s)
    with ThreadPoolExecutor(max_workers=6) as pool:
        results=list(pool.map(work,range(12)))
    assert all(r["ok"] for r in results)
    for s in (sid,other):
        events=rec.events(s)["items"]
        assert [e["sequence"] for e in events]==list(range(1,7))
        assert all(e["session_id"]==s for e in events)
    assert len(server.store.list_frames())==12

def test_real_cli_and_stdio_restart(env):
    server,rec,sid,fake=env
    snap=mcp(server,"snapshot",device="dev",session_id=sid)
    fid=snap["frame"]["frame_id"]
    store=str(server.store.store_dir)
    cmd=[sys.executable,"-m","vision_app","--store-dir",store]
    def cli(*args):
        r=subprocess.run(cmd+list(args),capture_output=True,text=True,check=True)
        return json.loads(r.stdout)
    crop=cli("--session",sid,"crop","--frame",fid,"--region","0,0,20,20","--json")
    assert crop["sequence"]==2
    cli("record","pause","--session",sid)
    cli("record","resume","--session",sid)
    def stdio(tool,args):
        request={"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":tool,"arguments":args}}
        e={**os.environ,"VISION_STORE_DIR":store}
        p=subprocess.run([sys.executable,"-m","vision_app.mcp_server"],input=json.dumps(request)+"\n",capture_output=True,text=True,env=e,check=True)
        return json.loads(json.loads(p.stdout)["result"]["content"][-1]["text"])
    resize=stdio("vision_resize",{"session_id":sid,"frame_id":crop["result"]["frame_id"],"scale":0.5})
    assert resize["sequence"]==3
    context=stdio("vision_record_resume_context",{"session_id":sid})
    assert context["result"]["recent_events"][0]["sequence"]==3
    assert cli("record","inspect","--session",sid)["result"]["event_counts"]=={"success":3}

def test_pending_durable_before_execution(env):
    server,rec,sid,fake=env
    def interrupt():
        events=Recorder(server.store).events(sid)["items"]
        assert events[-1]["status"]=="pending"
        raise KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt): rec.execute(sid,"snapshot",{"device":"dev"},interrupt)
    assert Recorder(server.store).events(sid)["items"][0]["status"]=="pending"
    assert mcp(server,"snapshot",device="dev",session_id=sid)["sequence"]==2

def test_raw_utf8_stdio_annotation(env):
    server,rec,sid,fake=env
    snap=mcp(server,"snapshot",device="dev",session_id=sid)
    state="聲音設定"
    req={"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"vision_record_annotate","arguments":{"session_id":sid,"event_id":snap["event_id"],"annotation":{"state":state,"verification":"PASS"}}}}
    proc=subprocess.run([sys.executable,"-m","vision_app.mcp_server"],input=(json.dumps(req,ensure_ascii=False)+"\n").encode("utf-8"),capture_output=True,env={**os.environ,"VISION_STORE_DIR":str(server.store.store_dir),"PYTHONIOENCODING":"cp950"},check=True)
    assert not json.loads(proc.stdout)["result"]["isError"]
    assert rec.annotations(sid)["items"][0]["annotation"]["state"]==state
