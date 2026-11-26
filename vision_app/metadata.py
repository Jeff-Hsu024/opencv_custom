"""Short shared metadata transactions and OS-backed lifetime locks.

Lock files are permanent: unlinking a usable lock file breaks exclusion.
Callers acquire lifetime owners before metadata, and only probe them without
waiting while inside metadata. No device I/O belongs in these transactions.
"""
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import threading

_guard = threading.Lock()
_threads = {}
_local = threading.local()


class FileLock:
    def __init__(self, store_dir, namespace, key):
        root = Path(store_dir).resolve()
        digest = hashlib.sha256((os.path.normcase(str(root)) + "\0" + namespace + "\0" + key).encode()).hexdigest()
        self.path = root / "metadata_locks" / (digest + ".lock")
        with _guard:
            self.thread_lock = _threads.setdefault(os.path.normcase(str(self.path)), threading.Lock())
        self.handle = None

    def acquire(self, blocking=True):
        if not self.thread_lock.acquire(blocking=blocking):
            return False
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.handle = open(self.path, "a+b")
            if os.name == "nt":
                import msvcrt
                if self.path.stat().st_size == 0:
                    self.handle.write(b"\0")
                    self.handle.flush()
                # LK_LOCK has a fixed retry limit; explicitly retry for blocking users.
                while True:
                    self.handle.seek(0)
                    try:
                        msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
                        break
                    except OSError:
                        if not blocking:
                            self.handle.close()
                            self.handle = None
                            self.thread_lock.release()
                            return False
                        import time
                        time.sleep(.01)
            else:
                import fcntl
                try:
                    fcntl.flock(self.handle, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
                except BlockingIOError:
                    self.handle.close()
                    self.handle = None
                    self.thread_lock.release()
                    return False
            return True
        except BaseException:
            if self.handle is not None:
                self.handle.close()
                self.handle = None
            self.thread_lock.release()
            raise

    def release(self):
        try:
            if os.name == "nt":
                import msvcrt
                self.handle.seek(0)
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle, fcntl.LOCK_UN)
        finally:
            self.handle.close()
            self.handle = None
            self.thread_lock.release()


@contextmanager
def metadata_transaction(store):
    """Serialize cooperating JSON/sidecar writers across processes and threads."""
    root = Path(os.path.normcase(str(Path(getattr(store, "store_dir", store)).resolve())))
    held = getattr(_local, "metadata", set())
    if root in held:
        yield
        return
    lock = FileLock(root, "metadata", "shared")
    lock.acquire()
    _local.metadata = held | {root}
    try:
        yield
    finally:
        _local.metadata = held
        lock.release()
