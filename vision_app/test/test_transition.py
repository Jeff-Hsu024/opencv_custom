import json
import pytest
from test_workflow import Platform,call
from vision_app.mcp_server import VisionMcpServer,_tool_definitions
from vision_app.recorder import Recorder,ANNOTATION_FIELDS
from vision_app.transition import TransitionService
from vision_app.workflow import WorkflowBuilder
from vision_app.cli import run_cli

T="trans_"+"a"*32

@pytest.fixture
def env(tmp_path):
    p=Platform();s=VisionMcpServer(tmp_path,platform_factory=lambda _:p)
    r=Recorder(s.store);sid=r.start("test","navigation","dev")["session_id"]
    pre=call(s,"snapshot",device="dev",session_id=sid)
    call(s,"assets_register",name="button",frame_id=pre["frame"]["frame_id"],region=[80,60,100,80],session_id=sid)
    args=dict(device="dev",session_id=sid,transition_id=T,target="button",postcondition={"mode":"changed","timeout":5},return_image=False)
    return p,s,r,sid,args

def test_annotation_contract(env,capsys):
    p,s,r,sid,args=env
    schema=next(t for t in _tool_definitions() if t["name"]=="vision_record_checkpoint")["inputSchema"]["properties"]["annotation"]
    assert set(schema["properties"])==ANNOTATION_FIELDS and schema["additionalProperties"] is False
    eid=r.events(sid)["items"][0]["event_id"]
    bad=call(s,"record_checkpoint",session_id=sid,event_id=eid,annotation={"known_assets":["sensitivevalue"]})
    assert bad["error"]["code"]=="INVALID_ANNOTATION" and bad["error"]["details"]["unknown_fields"]==["known_assets"]
    assert "sensitivevalue" not in json.dumps(bad) and not r.annotations(sid)["items"]
    code=run_cli(["--store-dir",str(s.store.store_dir),"record","annotate","--session",sid,"--event",eid,"--annotation",'{"known_assets":[]}'])
    assert code==3 and json.loads(capsys.readouterr().out)["error"]["code"]=="INVALID_ANNOTATION"

def test_transition_buildable_and_idempotent(env):
    p,s,r,sid,args=env
    a=call(s,"transition",**args)["result"]
    assert a["status"]=="observed" and a["semantic_verification"]=="UNKNOWN"
    assert a["action_outcome"]=="executed_unverified" and len(p.actions)==1
    es=a["events"]
    assert [r.event(sid,es[k])["operation"] for k in ("pre","find","action","wait","post")]==["snapshot","find","click","wait","snapshot"]
    assert call(s,"transition",**args)["result"]["duplicate_request"] and len(p.actions)==1
    bad=call(s,"transition",**{**args,"threshold":.99})
    assert bad["error"]["code"]=="INVALID_TRANSITION"
    ann=r.annotate(sid,es["post"],{"state":"B","observation":"B visible","verification":"PASS"})
    r.transition(sid,"stop")
    plan={"name":"transition","goal":"navigate","states":[{"id":"a","label":"A","event_id":es["pre"],"region":[2,2,35,30],"threshold":.98},{"id":"b","label":"B","event_id":es["post"],"region":[2,2,35,30],"threshold":.98}],"steps":[{"from":"a","to":"b","pre_event_id":es["pre"],"find_event_id":es["find"],"action_event_id":es["action"],"wait_event_id":es["wait"],"post_event_id":es["post"],"annotation_id":ann["annotation_id"]}],"excluded_actions":[]}
    item=WorkflowBuilder(s.store).build(sid,plan)
    assert item["definition"]["validation"]["status"]=="offline_pass"
    assert WorkflowBuilder(s.store).validate(item["workflow_id"])["status"]=="offline_pass"

def test_no_match(env):
    p,s,r,sid,args=env;p.state=1
    res=call(s,"transition",**args)["result"]
    assert res["status"]=="needs_agent" and res["reason"]["code"]=="TARGET_NOT_UNIQUE" and res["action_outcome"]=="not_attempted"
    assert len(p.actions)==0

def test_ambiguous(env):
    p,s,r,sid,args=env;p.images[0][60:80,110:130]=p.images[0][60:80,80:100]
    res=call(s,"transition",**args)["result"]
    assert res["status"]=="needs_agent" and res["match_count"]==2 and not p.actions

def test_crash_pending(env):
    p,s,r,sid,args=env
    def click(x,y):
        p.actions.append((x,y));raise KeyboardInterrupt()
    p.click=click
    with pytest.raises(KeyboardInterrupt):call(s,"transition",**args)
    res=call(s,"transition",**args)["result"]
    assert res["status"]=="interrupted" and res["action_outcome"]=="unknown" and res["events"]["action"] and len(p.actions)==1
    assert r.event(sid,res["events"]["action"])["status"]=="pending"

def test_image_content(env):
    p,s,r,sid,args=env
    result=s.call_tool("vision_transition",{**args,"return_image":True})
    assert [c["type"] for c in result["content"]]==["image","text"]
    text=json.loads(result["content"][1]["text"])
    assert text["result"]["status"]=="observed" and "base64" not in result["content"][1]["text"]

def test_cli_parity(env,capsys):
    p,s,r,sid,args=env
    code=run_cli(["--store-dir",str(s.store.store_dir),"--session",sid,"transition","execute","--transition-id",T,"--device","dev","--target","button","--postcondition",'{"mode":"changed","timeout":5}',"--return-image","false"],service=s.obs)
    assert code==0
    res=json.loads(capsys.readouterr().out)["result"]
    assert res["status"]=="observed" and len(p.actions)==1
    assert call(s,"transition_inspect",transition_id=T)["result"]["events"]==res["events"]
