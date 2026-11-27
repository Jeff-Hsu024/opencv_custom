from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager
import json
from pathlib import Path
import queue
import sqlite3
import subprocess
import sys
import threading
import time

import pytest

from vision_app.coordinator import Claim, ClaimError, RequestLedger, child_task_id, task_run_id
from vision_app.metadata import metadata_transaction


BATCH = "batch_" + "a" * 32


def task(device="A"):
    return Claim(child_task_id(BATCH, device), "portable_task", {"device": device},
                 {"status": "in_progress", "duplicate_request": False}, device)


def run(child):
    return Claim(task_run_id(child.id, child.device), "portable_run", child.request,
                 child.receipt, child.device, owner_id=child.id)


def batch():
    return Claim(BATCH, "batch", {"devices": ["A", "B"]}, {"status": "in_progress"})


@contextmanager
def worker(root, body, *args):
    script = (
        "import sys\n"
        "from vision_app.coordinator import RequestLedger, Claim\n"
        "ledger = RequestLedger(sys.argv[1])\n"
        + body
    )
    with subprocess.Popen([sys.executable, "-u", "-c", script, str(root), *args],
                          stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True) as process:
        ready = queue.Queue()
        threading.Thread(target=lambda: ready.put(process.stdout.readline()), daemon=True).start()
        try:
            assert ready.get(timeout=15).strip() == "ready"
            yield process
        finally:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=15)


def test_os_device_contention_kill_and_permanent_hashed_file(tmp_path):
    ledger = RequestLedger(tmp_path)
    with worker(tmp_path, """
with ledger.device_owner(sys.argv[2]) as owner:
    assert owner
    print("ready")
    sys.stdin.readline()
""", "../A") as process:
        files = list((tmp_path / "metadata_locks").iterdir())
        assert len(files) == 1
        assert len(files[0].stem) == 64
        int(files[0].stem, 16)
        stat = files[0].stat()
        alias = RequestLedger(tmp_path / "unused" / "..")
        start = time.monotonic()
        with alias.device_owner("../A", timeout=.1) as busy:
            assert busy is None
        assert .08 <= time.monotonic() - start < 2
        with ledger.device_owner("../a", timeout=0) as independent:
            assert independent
        process.kill()
        process.wait(timeout=15)
        with alias.device_owner("../A", timeout=1) as reopened:
            assert reopened
        assert files[0].stat().st_ino == stat.st_ino
        assert files[0].stat().st_ctime_ns == stat.st_ctime_ns


def test_thread_order_and_nested_device_reuse(tmp_path):
    ledger = RequestLedger(tmp_path)
    with ledger.request_owner(BATCH, parent=True) as parent:
        assert parent
        with ledger.request_owner(task().id) as child:
            assert child
            with ledger.device_owner("A") as device:
                assert device
                with RequestLedger(tmp_path).device_owner("A", owner=device) as nested:
                    assert nested is device
                with pytest.raises(RuntimeError), ledger.device_owner("B"):
                    pass
                with pytest.raises(RuntimeError), ledger.request_owner(BATCH, parent=True):
                    pass
                with metadata_transaction(tmp_path):
                    with pytest.raises(RuntimeError), ledger.device_owner("B", timeout=0):
                        pass
                with ThreadPoolExecutor(1) as pool:
                    def check():
                        with ledger.device_owner("A", timeout=0) as busy:
                            assert busy is None
                        with ledger.device_owner("B", timeout=0) as independent:
                            assert independent
                        with pytest.raises(RuntimeError), ledger.device_owner("A", owner=device):
                            pass
                    pool.submit(check).result(timeout=3)
            with pytest.raises(RuntimeError), ledger.device_owner("A", owner=device):
                pass
    with metadata_transaction(tmp_path):
        with pytest.raises(RuntimeError), ledger.request_owner(BATCH, parent=True):
            pass
        with pytest.raises(RuntimeError), ledger.device_owner("A"):
            pass


def test_duplicate_is_first_and_terminal_receipt_immutable(tmp_path):
    ledger = RequestLedger(tmp_path)
    claim = task()
    with ledger.request_owner(claim.id) as owner:
        ledger.admit(owner, claim)
        assert ledger.inspect(claim.id, lambda *_: pytest.fail("Reconciled local live owner")) == claim.receipt
        ledger.record(owner, claim.id, {"status": "completed"}, terminal=True)
        with pytest.raises(RuntimeError):
            ledger.record(owner, claim.id, claim.receipt)
        assert ledger.admit(
            owner, claim, recheck=lambda _: pytest.fail("Duplicate ran current validation")
        ) == {"status": "completed", "duplicate_request": True}
    assert ledger.duplicate(claim.id, claim.kind, {**claim.request, "return_image": True}) == {
        "status": "completed", "duplicate_request": True
    }
    assert ledger.inspect(claim.id) == {"status": "completed"}
    with pytest.raises(ClaimError, match="REQUEST_ID_CONFLICT"):
        ledger.duplicate(claim.id, claim.kind, {"device": "B"})


def test_batch_collision_rolls_back_entire_reservation(tmp_path):
    ledger = RequestLedger(tmp_path)
    a, b = task("A"), task("B")
    with ledger.request_owner(b.id) as owner:
        ledger.admit(owner, b)
    with ledger.request_owner(BATCH, parent=True) as owner:
        with pytest.raises(ClaimError, match="REQUEST_ID_CONFLICT"):
            ledger.admit(owner, batch(), reservations=[a, run(a), b, run(b)], batch_pins={})
    for missing in (BATCH, a.id, run(a).id, run(b).id):
        with pytest.raises(ClaimError, match="NOT_FOUND"):
            ledger.inspect(missing)
    with closing(sqlite3.connect(tmp_path / "coordinator.sqlite")) as db:
        assert db.execute("SELECT COUNT(*) FROM batch_admission").fetchone() == (0,)


def test_surviving_child_and_abandoned_owner(tmp_path):
    ledger = RequestLedger(tmp_path)
    a, b = task("A"), task("B")
    with worker(tmp_path, """
from vision_app.test.test_coordinator import batch, task, run
a, b = task("A"), task("B")
with ledger.request_owner(batch().id, parent=True) as owner:
    ledger.admit(owner, batch(), reservations=[a, run(a), b, run(b)], batch_pins={"generation": 2})
    print("ready")
    sys.stdin.readline()
""") as parent:
        assert ledger.inspect(BATCH, lambda *_: pytest.fail("Reconciled live parent")) == batch().receipt
        for claim in (a, run(a)):
            with pytest.raises(ClaimError, match="ID_RESERVED"):
                ledger.duplicate(claim.id, claim.kind, claim.request)
            with pytest.raises(ClaimError, match="REQUEST_ID_CONFLICT"):
                ledger.duplicate(claim.id, claim.kind, {"device": "changed"})
        with worker(tmp_path, """
task_id, batch_id, run_id = sys.argv[2:]
with ledger.request_owner(task_id) as owner:
    assert ledger.start_reserved(owner, batch_id)
    ledger.record(owner, run_id, {"status": "in_progress", "action_outcome": "unknown"})
    print("ready")
    sys.stdin.readline()
""", a.id, BATCH, run(a).id) as child:
            assert ledger.duplicate(a.id, a.kind, a.request) == {**a.receipt, "duplicate_request": True}
            parent.kill()
            parent.wait(timeout=15)

            def close(owner, receipt):
                ledger.close_admission(owner, lambda _: {"status": "not_attempted"})
                assert ledger.inspect(a.id, lambda *_: pytest.fail("Reconciled live child")) == a.receipt
                return None

            assert ledger.inspect(BATCH, close) == batch().receipt
            assert ledger.inspect(b.id) == {"status": "not_attempted"}
            with ledger.request_owner(b.id) as owner:
                assert not ledger.start_reserved(owner, BATCH)
            assert ledger.inspect(run(a).id, lambda *_: pytest.fail("Reconciled live nested run")) == {
                "status": "in_progress", "action_outcome": "unknown"
            }
            child.kill()
            child.wait(timeout=15)

            def finalize(owner, receipt):
                for claim in (run(a), a):
                    ledger.inspect(claim.id, lambda _, current: {**current, "status": "interrupted"})
                return {"status": "interrupted"}

            assert ledger.inspect(BATCH, finalize) == {"status": "interrupted"}
            assert ledger.inspect(run(a).id)["action_outcome"] == "unknown"
            assert ledger.duplicate(BATCH, "batch", batch().request)["duplicate_request"]
    with closing(sqlite3.connect(tmp_path / "coordinator.sqlite")) as db:
        assert db.execute("SELECT phase FROM batch_admission").fetchone() == ("terminal",)
        assert db.execute("PRAGMA integrity_check").fetchone() == ("ok",)


def test_standalone_nested_run_uses_task_owner(tmp_path):
    ledger = RequestLedger(tmp_path)
    claim = task()
    child = run(claim)
    with ledger.request_owner(claim.id) as owner:
        ledger.admit(owner, claim, reservations=[child])
        assert ledger.start_nested(owner, child.id)
        assert not ledger.start_nested(owner, child.id)
        assert ledger.inspect(child.id, lambda *_: pytest.fail("Reconciled live nested owner")) == child.receipt
        ledger.record(owner, child.id, {"status": "completed"}, terminal=True)
        ledger.record(owner, claim.id, {"status": "completed"}, terminal=True)
    assert ledger.inspect(child.id, lambda *_: pytest.fail("Reconciled terminal run")) == {"status": "completed"}


def test_frozen_child_ids():
    path = Path(__file__).resolve().parents[2] / "specs/agent-vision-phase9/c00/ID_EXAMPLES.json"
    for vector in json.loads(path.read_text(encoding="utf-8")):
        task_id = child_task_id(vector["batch_id"], vector["device"])
        assert task_id == vector["expected"]["task_id"]
        assert task_run_id(task_id, vector["device"]) == vector["expected"]["run_id"]
