from __future__ import annotations

from typing import Iterable

import psutil


def _cmdline_contains(cmdline: Iterable[str] | None, needle: str) -> bool:
    if not cmdline:
        return False
    n = str(needle)
    try:
        return any(n in str(part) for part in cmdline)
    except Exception:
        return False


def find_sync_worker_pids(*, job_id: str) -> list[int]:
    """Find running worker_sync processes for a given job_id."""

    jid = str(job_id)
    out: list[int] = []
    for p in psutil.process_iter(attrs=["pid", "cmdline"]):
        try:
            cmd = p.info.get("cmdline")
            if not _cmdline_contains(cmd, "webmail_summary.jobs.worker_sync"):
                continue
            if not _cmdline_contains(cmd, "--job-id"):
                continue
            if not _cmdline_contains(cmd, jid):
                continue
            out.append(int(p.info.get("pid") or p.pid))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        except Exception:
            continue
    return out


def is_sync_worker_running(*, job_id: str) -> bool:
    return bool(find_sync_worker_pids(job_id=job_id))


def kill_sync_worker(*, job_id: str, timeout_s: float = 1.5) -> bool:
    """Best-effort: kill worker_sync processes (terminate then kill)."""

    killed_any = False
    for pid in find_sync_worker_pids(job_id=job_id):
        try:
            p = psutil.Process(int(pid))
        except Exception:
            continue

        try:
            p.terminate()
            try:
                p.wait(timeout=timeout_s)
            except Exception:
                pass
            if p.is_running():
                try:
                    p.kill()
                    p.wait(timeout=timeout_s)
                except Exception:
                    pass
            killed_any = True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        except Exception:
            continue
    return killed_any
