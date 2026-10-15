"""OS-owned migration lock, released even if a startup process crashes."""

from contextlib import contextmanager
import errno
import os
from pathlib import Path
import time


@contextmanager
def migration_lock(database: Path, *, timeout: float = 45.0):
    # Never unlink this file: waiters must keep locking the same inode.
    path = Path(f"{database}.migration.lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    with os.fdopen(os.open(path, os.O_CREAT | os.O_RDWR, 0o600), "r+b") as handle:
        if os.fstat(handle.fileno()).st_size == 0:
            handle.write(b"\0")
            handle.flush()
        if os.name == "nt":
            import msvcrt

            def acquire():
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)

            def release():
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            def acquire():
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

            def release():
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

        deadline = time.monotonic() + timeout
        while True:
            try:
                acquire()
                break
            except OSError as error:
                if error.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                    raise
                if time.monotonic() >= deadline:
                    raise TimeoutError("数据库正在由另一个 MathTutor 进程初始化，请关闭重复窗口后重试。") from error
                time.sleep(0.05)
        try:
            yield
        finally:
            release()
