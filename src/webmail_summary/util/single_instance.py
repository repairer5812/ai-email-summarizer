from __future__ import annotations

import os
from pathlib import Path

if os.name == "nt":
    import msvcrt
else:
    import fcntl


class SingleInstanceLock:
    def __init__(self, lock_path: Path) -> None:
        self._lock_path = Path(lock_path)
        self._fh = None

    def acquire(self) -> bool:
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(self._lock_path, "a+b")
        fh.seek(0, os.SEEK_END)
        if fh.tell() == 0:
            fh.write(b"0")
            fh.flush()
        fh.seek(0)

        try:
            if os.name == "nt":
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            fh.close()
            return False

        self._fh = fh
        return True

    def release(self) -> None:
        fh = self._fh
        if fh is None:
            return
        self._fh = None
        try:
            if os.name == "nt":
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        try:
            fh.close()
        except Exception:
            pass
