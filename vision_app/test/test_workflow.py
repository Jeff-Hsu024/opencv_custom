"""Workflow Builder tests: actual recorder receipts, offline checks and fail-closed rules."""
import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from vision_app.mcp_server import VisionMcpServer
from vision_app.recorder import Recorder
from vision_app.store import FrameStore
from vision_app.workflow import WorkflowBuilder, WorkflowError


class Platform:
    def __init__(self):
        rng=np.random.default_rng(31)
        self.images=[rng.integers(0,256,(100,140,3),dtype=np.uint8) for _ in range(2)]
        self.state=0
        self.actions=[]
    def snapshot(self):
        return self.images[self.state].copy()
    def click(self,x,y):
        self.actions.append(("click",x,y))
        self.state=1-self.state
        return True
    def key_event(self,key):
        self.actions.append(("key",key))
        return False


def call(server,tool,**args):
    response=server.call_tool("vision_"+tool,args)
    return json.loads(next(c["text"] for c in response["content"] if c["type"]=="text"))


@pytest.fixture
def recorded(tmp_path):
    platform=Platform()
    server=VisionMcpServer(tmp_path,platform_factory=lambda _:platform)
    rec=Recorder(server.store)
    sid=rec.start("explore","two pages","dev")["session_id"]
    def op(tool,**args):
        r=call(server,tool,session_id=sid,**args)
        assert r["ok"],r
        return r
    a=op("snapshot",device="dev")
    fid=a["frame"]["frame_id"]
    op("assets_register",name="button",frame_id=fid,region=[80,60,100,80])
    find=op("find",frame_id=fid,target="button",all=True,threshold=0.98)
    click=op("click",device="dev",ref=find["matches"][0]["ref_id"],max_age_seconds=15)
    wait=op("wait",device="dev",mode="changed",baseline_frame_id=fid,timeout=5)
    z=op("snapshot",device="dev")
    ann=rec.annotate(sid,z["event_id"],{"state":"page B","observation":"page B visible","verification":"PASS"})
    rec.transition(sid,"stop")
    plan={"name":"test","goal":"navigate","states":[
        {"id":"a","label":"page A","event_id":a["event_id"],"region":[2,2,35,30],"threshold":0.98},
        {"id":"b","label":"page B","event_id":z["event_id"],"region":[2,2,35,30],"threshold":0.98}],
        "steps":[{"from":"a","to":"b","pre_event_id":a["event_id"],"find_event_id":find["event_id"],
                  "action_event_id":click["event_id"],"wait_event_id":wait["event_id"],
                  "post_event_id":z["event_id"],"annotation_id":ann["annotation_id"]}],"excluded_actions":[]}
    return server,rec,sid,plan,platform


def test_compile_and_verify_offline(recorded):
    server,rec,sid,plan,platform=recorded
    b=WorkflowBuilder(server.store)
    actions=list(platform.actions)
    item=b.build(sid,plan)
    wid=item["workflow_id"]
    d=item["definition"]
    assert d["validation"]["status"]=="offline_pass"
    assert d["validation"]["live_runtime_qualified"] is False
    assert len(d["validation"]["state_checks"])==6
    assert len(d["source"]["event_sha256"])==5
    assert len(d["source"]["annotation_sha256"])==1
    assert d["steps"][0]["action"]["kind"]=="click_unique_template"
    assert "ref_id" not in d["steps"][0]["action"] and "point" not in d["steps"][0]["action"]
    assert d["steps"][0]["max_attempts"]==1
    assert b.validate(wid)["templates"]==3
    assert b.build(sid,plan)["workflow_id"]==wid
    assert b.list()["items"][0]["workflow_id"]==wid
    assert platform.actions==actions
    assert rec.summary(sid)["event_counts"]=={"success":6}


@pytest.mark.parametrize("mutation",["wrong_order","wrong_session","no_semantic_pass","bad_roi","same_marker","missing_action","wrong_ref","wrong_wait"])
def test_reject_bad_plan(recorded,mutation):
    server,rec,sid,plan,_=recorded
    b=WorkflowBuilder(server.store)
    p=copy.deepcopy(plan)
    step=p["steps"][0]
    if mutation=="wrong_order": step["pre_event_id"]=step["post_event_id"]
    elif mutation=="wrong_session": sid=rec.start("other","other","dev")["session_id"]; rec.transition(sid,"stop")
    elif mutation=="no_semantic_pass":
        ann=rec.annotate(sid,step["post_event_id"],{"state":"B","verification":"FAIL","observation":"not B"})
        step["annotation_id"]=ann["annotation_id"]
    elif mutation=="bad_roi": p["states"][0]["region"]=[0,0,10000,10000]
    elif mutation=="same_marker": p["states"][1]["event_id"]=p["states"][0]["event_id"]
    elif mutation=="missing_action": p["excluded_actions"]=[{"event_id":step["action_event_id"],"reason":"skip"}]
    elif mutation=="wrong_ref": step["find_event_id"]=step["pre_event_id"]
    elif mutation=="wrong_wait": step["wait_event_id"]=step["post_event_id"]
    with pytest.raises(WorkflowError): b.build(sid,p)
    assert b.list()["items"]==[]


def test_disputed_annotation_rejected(recorded):
    server,rec,sid,plan,_=recorded
    rec.annotate(sid,plan["steps"][0]["post_event_id"],{"state":"B","verification":"UNKNOWN","observation":"uncertain"})
    with pytest.raises(WorkflowError,match="disputes"): WorkflowBuilder(server.store).build(sid,plan)


def test_candidate_failed_and_unsupported(recorded):
    server,rec,sid,plan,platform=recorded
    other=rec.start("other","other","dev")["session_id"]
    r=call(server,"key",device="dev",key="4",session_id=other)
    assert not r["ok"]
    b=WorkflowBuilder(server.store)
    c=b.candidates(other,limit=1)["items"][0]
    assert c["status"]=="failed" and c["supported"] is False
    assert b.candidates(sid)["items"][0]["supported"] is True
    assert b.candidates(sid,after=999)["items"]==[]


def test_bundle_tamper(recorded):
    server,rec,sid,plan,_=recorded
    b=WorkflowBuilder(server.store)
    item=b.build(sid,plan)
    wid=item["workflow_id"]
    path=Path(item["bundle_path"])/item["definition"]["steps"][0]["action"]["template"]["path"]
    path.write_bytes(b"corrupt")
    with pytest.raises(WorkflowError,match="tampered"): b.validate(wid)


def test_source_frame_tamper(recorded):
    server,rec,sid,plan,_=recorded
    b=WorkflowBuilder(server.store)
    item=b.build(sid,plan)
    fid=item["definition"]["steps"][0]["provenance"]["source_frames"][0]
    path=server.store.resolve_image_path(server.store.get_frame(fid).image_path)
    path.write_bytes(path.read_bytes()+b"extra")
    with pytest.raises(WorkflowError,match="changed"): b.validate(item["workflow_id"])


def test_mcp_cli_process_restart(recorded,tmp_path):
    server,rec,sid,plan,_=recorded
    r=call(server,"workflow_build",session_id=sid,plan=plan)
    assert r["ok"],r
    wid=r["result"]["workflow_id"]
    cli=[sys.executable,"-m","vision_app","--store-dir",str(server.store.store_dir),"workflow","validate","--workflow",wid]
    proc=subprocess.run(cli,capture_output=True,text=True,check=True)
    assert json.loads(proc.stdout)["result"]["status"]=="offline_pass"
    request={"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"vision_workflow_inspect","arguments":{"workflow_id":wid}}}
    proc=subprocess.run([sys.executable,"-m","vision_app.mcp_server"],input=json.dumps(request)+"\n",
                        capture_output=True,text=True,env={**os.environ,"VISION_STORE_DIR":str(server.store.store_dir)},check=True)
    out=json.loads(json.loads(proc.stdout)["result"]["content"][0]["text"])
    assert out["result"]["definition"]["workflow_id"]==wid
    names={t["name"] for t in server.handle_request({"jsonrpc":"2.0","id":1,"method":"tools/list"})["result"]["tools"]}
    assert {"vision_workflow_build","vision_workflow_validate","vision_record_start","vision_snapshot"}<=names

def test_unaccounted_action_rejected(recorded):
    server,rec,sid,plan,_=recorded
    with rec.db() as db:
        # Simulate an interrupted action in the recorded path, preserving unique sequences.
        db.execute("UPDATE events SET sequence=sequence+100 WHERE session_id=? AND sequence>=4",(sid,))
        db.execute("UPDATE events SET sequence=sequence-99 WHERE session_id=? AND sequence>=104",(sid,))
        db.execute("INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                   ("evt_unknown",sid,4,0,None,"key","dev","pending","{}",None,None,
                    json.dumps({"frames":[],"assets":[],"references":[]})))
    b=WorkflowBuilder(server.store)
    with pytest.raises(WorkflowError,match="Unaccounted action"): b.build(sid,plan)
    p=copy.deepcopy(plan)
    p["excluded_actions"]=[{"event_id":"evt_unknown","reason":"unknown outcome"}]
    with pytest.raises(WorkflowError,match="Unaccounted action"): b.build(sid,p)


def test_marker_ambiguity_rejected(recorded):
    server,rec,sid,plan,_=recorded
    import cv2
    pre=rec.event(sid,plan["steps"][0]["pre_event_id"])
    fid=pre["result"]["frame"]["frame_id"]
    img=server.store.load_image(fid)
    img[40:68,2:35]=img[2:30,2:35]
    path=server.store.resolve_image_path(server.store.get_frame(fid).image_path)
    assert cv2.imwrite(str(path),img)
    with pytest.raises(WorkflowError,match="State guard"): WorkflowBuilder(server.store).build(sid,plan)


def test_active_source_rejected(recorded):
    server,rec,sid,plan,_=recorded
    with rec.db() as db: db.execute("UPDATE sessions SET status='active' WHERE session_id=?",(sid,))
    with pytest.raises(WorkflowError,match="stopped"): WorkflowBuilder(server.store).build(sid,plan)


def test_annotation_provenance_tamper(recorded):
    server,rec,sid,plan,_=recorded
    b=WorkflowBuilder(server.store)
    item=b.build(sid,plan)
    aid=plan["steps"][0]["annotation_id"]
    with rec.db() as db:
        db.execute("UPDATE annotations SET annotation=? WHERE annotation_id=?",
                   (json.dumps({"state":"B","observation":"different observation","verification":"PASS"}),aid))
    with pytest.raises(WorkflowError,match="changed"): b.validate(item["workflow_id"])


def test_annotation_during_validation_rejects_and_preserves_history(recorded, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from vision_app.metadata import metadata_held
    from vision_app.validation_context import EvidenceChanged, validation_scope

    server, rec, sid, plan, _ = recorded
    builder = WorkflowBuilder(server.store)
    item = builder.build(sid, plan)
    wid = item["workflow_id"]
    original = builder._validate_uncached
    def disputed(workflow_id):
        result = original(workflow_id)
        assert not metadata_held()
        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(rec.annotate, sid, plan["steps"][0]["post_event_id"],
                        {"verification": "FAIL", "observation": "Disputed"}).result(timeout=5)
        return result

    with validation_scope(server.store):
        monkeypatch.setattr(builder, "_validate_uncached", disputed)
        with pytest.raises(EvidenceChanged):
            builder.validate(wid)
        monkeypatch.setattr(builder, "_validate_uncached", original)
        with pytest.raises(EvidenceChanged):
            builder.validate(wid)
    assert builder.inspect(wid) == item


def test_annotation_after_staging_rejects_publication(recorded, monkeypatch):
    import vision_app.workflow as workflow
    from vision_app.metadata import metadata_held
    from vision_app.validation_context import EvidenceChanged

    server, rec, sid, plan, _ = recorded
    builder = WorkflowBuilder(server.store)
    write = workflow._atomic_write_json

    def annotate_after_seal(path, data):
        write(path, data)
        if path.name == "source-seal.json":
            assert not metadata_held()
            rec.annotate(sid, plan["steps"][0]["post_event_id"], {"observation": "New evidence"})

    monkeypatch.setattr(workflow, "_atomic_write_json", annotate_after_seal)
    with pytest.raises(EvidenceChanged):
        builder.build(sid, plan)
    assert list(builder.root.iterdir()) == []


def test_pinned_frame_survives_cleanup_but_protection_revision_rejects_aba(recorded, monkeypatch):
    from vision_app.validation_context import EvidenceChanged

    server, rec, sid, plan, _ = recorded
    store = server.store
    builder = WorkflowBuilder(store)
    compile_plan = builder._compile

    def protection_changed(session_id, candidate):
        definition, blobs = compile_plan(session_id, candidate)
        fid = next(iter(definition["source"]["frame_sha256"]))
        store.set_protected(fid, False)
        assert fid not in store.cleanup(now=10**12)
        store.set_protected(fid, True)
        assert store.get_frame(fid).protected
        return definition, blobs

    monkeypatch.setattr(builder, "_compile", protection_changed)
    with pytest.raises(EvidenceChanged):
        builder.build(sid, plan)
    assert builder.list()["items"] == []
    assert store._lifetimes()["pins"] == {}


def test_concurrent_identical_publication_returns_same_bundle(recorded, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    import vision_app.workflow as workflow
    from vision_app.metadata import metadata_held

    server, rec, sid, plan, _ = recorded
    ready = Barrier(2, timeout=15)
    write = workflow._atomic_write_json

    def stage_together(path, data):
        write(path, data)
        if path.name == "source-seal.json":
            assert not metadata_held()
            ready.wait()

    monkeypatch.setattr(workflow, "_atomic_write_json", stage_together)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(WorkflowBuilder(server.store).build, sid, copy.deepcopy(plan))
                   for _ in range(2)]
        first, second = [future.result(timeout=30) for future in futures]

    assert first == second
    builder = WorkflowBuilder(server.store)
    assert builder.validate(first["workflow_id"])["status"] == "offline_pass"
    assert [p.name for p in builder.root.iterdir()] == [first["workflow_id"]]
    assert server.store._lifetimes()["pins"] == {}
