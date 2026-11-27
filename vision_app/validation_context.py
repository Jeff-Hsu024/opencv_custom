"""Pinned source dependencies and short publication compare-and-swap."""
from contextlib import contextmanager, ExitStack
from contextvars import ContextVar
from copy import deepcopy
import json

from vision_app.assets import RefRegistry
from vision_app.metadata import canonical_store, metadata_transaction
from vision_app.workflow import WorkflowError, canonical, digest, require

_context = ContextVar("task_validation_context", default=None)


class EvidenceChanged(WorkflowError):
    code = "EVIDENCE_CHANGED"


@contextmanager
def validation_scope(store):
    token = _context.set((canonical_store(store), {}))
    try:
        yield
    finally:
        _context.reset(token)


def _identity(path):
    try:
        stat = path.stat()
    except FileNotFoundError:
        return None
    return (str(path.resolve()), path.is_symlink(), stat.st_dev, stat.st_ino,
            stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)


class EvidenceSnapshot:
    def __init__(self, builder, sid, plan, bundle, pins):
        self.builder = builder
        self.sid = sid
        self.bundle = bundle
        self.revision = builder.rec.evidence_revision(sid)
        self.session = builder.rec.status(sid)
        self.events, self.annotations = builder._events(sid)
        self.seal_path = bundle / "source-seal.json" if bundle is not None else None

        selected = set()
        for section in ("states", "steps"):
            for entry in plan.get(section, []) if isinstance(plan.get(section), list) else []:
                if isinstance(entry, dict):
                    selected.update(value for key, value in entry.items()
                                    if key.endswith("event_id") and isinstance(value, str))

        frames, refs, retained = set(), set(), set()
        for eid in selected & self.events.keys():
            evidence = self.events[eid]["evidence"]
            frames.update(evidence["frames"])
            refs.update(evidence["references"])
            retained.update(asset["retained_path"] for asset in evidence["assets"])

        store = builder.store
        registry = RefRegistry(store.store_dir)
        for rid in refs:
            frames.add(registry.get(rid).frame_id)
        index, revisions = store._indexed_evidence()
        self.frames = {fid: index[fid] for fid in sorted(frames) if fid in index}
        self.frame_revisions = {fid: revisions.get(fid, 0) for fid in self.frames}
        if self.frames:
            pins.enter_context(store.pin_frames(self.frames))
        self.source_paths = [store.store_dir / f.image_path for f in self.frames.values()]
        self.source_paths.extend(registry._ref_path(rid) for rid in sorted(refs))
        root = (store.store_dir / "recorded_assets").resolve()
        for relative in sorted(retained):
            path = store.store_dir / relative
            require(path.resolve().parent == root, "Invalid retained asset path")
            self.source_paths.append(path)
        self.source_identities = [_identity(path) for path in self.source_paths]
        self.bundle_identities = self._bundle_identities()

    def _bundle_identities(self):
        if self.bundle is None:
            return {}
        templates = self.bundle / "templates"
        paths = [self.bundle, templates, self.bundle / "definition.json",
                 self.bundle / "plan.json", self.seal_path]
        if templates.is_dir():
            paths.extend(sorted(templates.iterdir()))
        return {path: _identity(path) for path in paths}

    def _hashes(self, paths):
        root = self.builder.store.store_dir
        return {path.relative_to(root).as_posix(): digest(path.read_bytes())
                for path in paths if path.is_file()}

    def seals(self):
        source = digest(canonical({
            "revision": self.revision, "session": self.session, "events": self.events,
            "annotations": self.annotations,
            "frames": {fid: frame.to_dict() for fid, frame in self.frames.items()},
            "frame_revisions": self.frame_revisions,
            "files": self._hashes(self.source_paths),
        }))
        bundle = digest(canonical(self._hashes(self.bundle_identities)))
        return source, bundle

    def compare(self):
        """Call under metadata immediately before any dependent write."""
        builder = self.builder
        if builder.rec.evidence_revision(self.sid) != self.revision:
            raise EvidenceChanged("Source session evidence changed")
        index, revisions = builder.store._indexed_evidence()
        if (any(index.get(fid) != frame for fid, frame in self.frames.items())
                or any(revisions.get(fid, 0) != rev for fid, rev in self.frame_revisions.items())
                or [_identity(path) for path in self.source_paths] != self.source_identities
                or self._bundle_identities() != self.bundle_identities):
            raise EvidenceChanged("Source or workflow dependency changed")

    @contextmanager
    def commit(self, seals):
        try:
            current = self.seals()
        except OSError as exc:
            raise EvidenceChanged("Evidence changed before commit") from exc
        with metadata_transaction(self.builder.store):
            self.compare()
            if current != seals:
                raise EvidenceChanged("Evidence seal changed before commit")
            yield


@contextmanager
def evidence_snapshot(builder, sid, plan, *, wid=None):
    with ExitStack() as pins:
        with metadata_transaction(builder.store):
            bundle = builder._directory(wid) if wid is not None else None
            if bundle is not None:
                plan = json.loads((bundle / "plan.json").read_text(encoding="utf-8"))
                sid = builder.inspect(wid)["definition"]["source"]["session_id"]
            snapshot = EvidenceSnapshot(builder, sid, plan if isinstance(plan, dict) else {}, bundle, pins)
        yield snapshot


def validate_cached(builder, wid, validate):
    ctx = _context.get()
    cache = ctx[1] if ctx is not None and ctx[0] == canonical_store(builder.store) else {}
    with evidence_snapshot(builder, None, None, wid=wid) as snapshot:
        before = snapshot.seals()
        saved = cache.get(wid)
        if saved is not None and saved[0] == before:
            with snapshot.commit(before):
                return deepcopy(saved[1])
        cache.pop(wid, None)
        expected = (json.loads(snapshot.seal_path.read_text(encoding="utf-8"))
                    if snapshot.seal_path.is_file() else None)
        source_changed = expected is not None and expected != {"source_seal": before[0]}
        try:
            result = validate(wid)
        except Exception as exc:
            with snapshot.commit(before):
                if source_changed:
                    raise EvidenceChanged(str(exc)) from exc
                raise
        with snapshot.commit(before):
            if source_changed:
                raise EvidenceChanged("Published source evidence changed")
            cache[wid] = (before, deepcopy(result))
        return result
