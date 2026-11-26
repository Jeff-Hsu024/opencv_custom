"""Task-local memoization of offline validation, guarded by complete dependency seals.

No device observations, profile probes, actions or lifecycle decisions are cached.
The context is created only inside the Orchestrator workspace lock.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
import json

from vision_app.assets import RefRegistry

_context=ContextVar("task_validation_context",default=None)


@contextmanager
def validation_scope(store):
    token=_context.set((str(store.store_dir.resolve()),{}))
    try:
        yield
    finally:
        _context.reset(token)


def _seal(builder,wid):
    from vision_app.workflow import canonical,digest
    directory=builder._directory(wid)
    def file(path):
        return {"sha256":digest(path.read_bytes()),"symlink":path.is_symlink(),
                "resolved":str(path.resolve()),"is_file":path.is_file()}
    definition=directory/"definition.json"
    d=json.loads(definition.read_text(encoding="utf-8"))
    source=d["source"];sid=source["session_id"]
    session=builder.rec.status(sid)
    events,anns=builder._events(sid) # all rows, including later disputes/excluded/unsupported actions
    index=builder.store._load_index()
    frames={}
    for fid in source["frame_sha256"]:
        f=index[fid]
        frames[fid]={"record":f.to_dict(),"image":file(builder.store.resolve_image_path(f.image_path))}
    refs={}
    registry=RefRegistry(builder.store.store_dir)
    for rid in source["ref_sha256"]:
        ref=registry.get(rid)
        # Reference validation also uses the associated frame metadata.
        refs[rid]={"file":file(registry._ref_path(rid)),"frame":index[ref.frame_id].to_dict()}
    revisions={}
    for step in d["steps"]:
        event=events[step["provenance"]["find_event_id"]]
        for asset in event["evidence"]["assets"]:
            if asset["name"]==step["provenance"]["source_asset_name"]:
                p=builder.store.store_dir/asset["retained_path"]
                if not p.resolve().is_relative_to((builder.store.store_dir/"recorded_assets").resolve()):
                    raise ValueError("Asset path outside retained store")
                revisions[asset["retained_path"]]=file(p)
    templates=directory/"templates"
    payload={"definition":file(definition),"plan":file(directory/"plan.json"),"session":session,
             "events":events,"annotations":anns,"frames":frames,"refs":refs,"revisions":revisions,
             "templates_path":str(templates.resolve()),"templates_symlink":templates.is_symlink(),
             "templates":{p.name:file(p) for p in sorted(templates.iterdir())}}
    return digest(canonical(payload))


def validate_cached(builder,wid,validate):
    ctx=_context.get()
    if ctx is None or ctx[0]!=str(builder.store.store_dir.resolve()):
        return validate(wid)
    cache=ctx[1]
    try:
        before=_seal(builder,wid)
    except Exception:
        # A seal that cannot be established is NEVER a cache hit.
        return validate(wid)
    saved=cache.get(wid)
    if saved is not None and saved[0]==before:
        return deepcopy(saved[1])
    result=validate(wid)
    try:
        after=_seal(builder,wid)
    except Exception as exc:
        cache.pop(wid,None)
        from vision_app.workflow import WorkflowError
        raise WorkflowError("Evidence seal changed during validation") from exc
    if before!=after:
        cache.pop(wid,None)
        from vision_app.workflow import WorkflowError
        raise WorkflowError("Evidence changed during validation")
    cache[wid]=(after,deepcopy(result))
    return result
