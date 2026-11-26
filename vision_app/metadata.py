"""Short shared metadata transactions and OS-backed lifetime locks.

Lock files are permanent: unlinking a usable lock file breaks exclusion.
Callers acquire lifetime owners before metadata, and only probe them without
waiting while inside metadata. No device I/O belongs in these transactions.
"""
from contextlib import contextmanager
import hashlib
import errno
import os
from pathlib import Path
import threading
import time

_guard = threading.Lock()
_threads = {}
_local = threading.local()


def canonical_store(store):
    return Path(os.path.normcase(str(Path(getattr(store, "store_dir", store)).resolve())))


def metadata_held():
    return bool(getattr(_local, "metadata", ()))


class FileLock:
    def __init__(self, store_dir, namespace, key):
        root = canonical_store(store_dir)
        digest = hashlib.sha256((str(root) + "\0" + namespace + "\0" + key).encode()).hexdigest()
        self.path = root / "metadata_locks" / (digest + ".lock")
        with _guard:
            self.thread_lock = _threads.setdefault(os.path.normcase(str(self.path)), threading.Lock())
        self.handle = None

    def acquire(self, blocking=True, *, timeout=None):
        deadline = None if timeout is None else time.monotonic() + timeout
        if not blocking or timeout == 0:
            acquired = self.thread_lock.acquire(blocking=False)
        elif timeout is None:
            acquired = self.thread_lock.acquire()
        else:
            acquired = self.thread_lock.acquire(timeout=timeout)
        if not acquired:
            return False
        locked = False
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.handle = open(self.path, "a+b")
            while True:
                if self._try_lock():
                    locked = True
                    return True
                remaining = .01 if deadline is None else deadline - time.monotonic()
                if not blocking or remaining <= 0:
                    return False
                time.sleep(min(.01, remaining))
        finally:
            if not locked:
                if self.handle is not None:
                    self.handle.close()
                    self.handle = None
                self.thread_lock.release()

    def _try_lock(self):
        try:
            if os.name == "nt":
                import msvcrt
                # Windows permits byte-range locks beyond EOF.
                self.handle.seek(0)
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            if error.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                raise
            return False
        return True

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
    root = canonical_store(store)
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
