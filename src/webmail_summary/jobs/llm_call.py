"""LLM call helpers shared by the sync and resummarize jobs.

Both jobs used to carry their own copies of the cloud pacing delay, the
per-tier hard timeout, the "elapsed" heartbeat, the local-server stop on
timeout and the threaded call with a deadline. They live here now so the two
paths cannot drift apart again.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from webmail_summary.archive.html_rewrite import ExternalAsset
from webmail_summary.archive.mime_parts import SavedAttachment
from webmail_summary.index.mail_repo import list_attachments, list_external_assets
from webmail_summary.llm.base import LlmImageInput, LlmResult

log = logging.getLogger(__name__)

# Cadence of the "(경과 mm:ss)" progress refresh while an LLM call runs.
# tasks_sync used Event.wait(5.0) (95cebac) and its chunk heartbeat also
# ticks every 5 s (4871ae8); tasks_resummarize used time.sleep(2.0)
# (124288b). No commit gives a reason for the 2 s value, so every heartbeat
# now shares 5 s and waits on an Event, which also lets it stop at once.
HEARTBEAT_INTERVAL_S = 5.0

# How long a timed-out call waits for the local llama.cpp server to stop.
LOCAL_SERVER_STOP_WAIT_S = 2.5

# Hard deadline per summary call, by provider tier.
_TIMEOUT_BY_TIER_S = {"cloud": 420.0, "fast": 240.0}
_DEFAULT_TIMEOUT_S = 360.0


def cloud_base_delay_seconds(cloud_provider: str, model: str) -> float:
    """Pause before a cloud call so low-RPM tiers are not hit in a burst."""
    provider = str(cloud_provider or "").strip().lower()
    model_name = str(model or "").strip().lower()

    if provider in {"openai", "anthropic", "openrouter"}:
        return 0.3
    if provider in {"google", "upstage"}:
        return 0.5
    if "gemini" in model_name:
        return 0.5
    return 0.4


def llm_timeout_seconds(provider) -> float:
    tier = getattr(provider, "tier", "standard")
    return _TIMEOUT_BY_TIER_S.get(tier, _DEFAULT_TIMEOUT_S)


def format_elapsed(seconds: float) -> str:
    """Return ``MM:SS`` for the progress messages."""
    s = max(0.0, float(seconds))
    return f"{int(s // 60):02d}:{int(s % 60):02d}"


def fallback_result(summary: str) -> LlmResult:
    """Placeholder result used when a call fails, times out or is cancelled."""
    return LlmResult(summary=summary, tags=[], backlinks=[], personal=False)


class Heartbeat:
    """Daemon thread that calls ``on_tick(elapsed_s)`` every ``interval_s``
    (``HEARTBEAT_INTERVAL_S`` when not given).

    It stops when :meth:`stop` is called or, if given, when ``cancel`` is
    set. A failing tick is logged and the heartbeat keeps going.
    """

    def __init__(
        self,
        on_tick: Callable[[float], None],
        *,
        interval_s: float | None = None,
        cancel: threading.Event | None = None,
        name: str = "llm-heartbeat",
    ) -> None:
        self._on_tick = on_tick
        self._interval_s = float(
            HEARTBEAT_INTERVAL_S if interval_s is None else interval_s
        )
        self._cancel = cancel
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name=name)

    def _run(self) -> None:
        started = time.monotonic()
        while not self._stop.wait(self._interval_s):
            if self._cancel is not None and self._cancel.is_set():
                return
            try:
                self._on_tick(max(0.0, time.monotonic() - started))
            except Exception:
                log.debug("heartbeat tick failed", exc_info=True)

    def start(self) -> Heartbeat:
        self._thread.start()
        return self

    def stop(self, *, join_timeout: float = 1.0) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=join_timeout)


def stop_local_server_async(*, wait_s: float = LOCAL_SERVER_STOP_WAIT_S) -> None:
    """Force-stop the local llama.cpp server without blocking for long.

    A hung server is the usual reason for a timeout; stopping it lets the
    next call start a fresh one.
    """
    stop_done = threading.Event()

    def _stop() -> None:
        try:
            from webmail_summary.llm.llamacpp_server import stop_server

            stop_server(force=True)
        except Exception:
            log.debug("stop_server(force=True) failed", exc_info=True)
        finally:
            stop_done.set()

    try:
        threading.Thread(target=_stop, daemon=True, name="llm-stop-server").start()
    except Exception:
        log.debug("could not start the stop_server thread", exc_info=True)
        return
    stop_done.wait(wait_s)


@dataclass(frozen=True)
class LlmCallOutcome:
    result: LlmResult | None
    error: Exception | None
    timed_out: bool


def call_with_deadline(
    fn: Callable[[], LlmResult],
    *,
    timeout_s: float,
    heartbeat: Heartbeat | None = None,
    on_timeout: Callable[[], None] | None = None,
) -> LlmCallOutcome:
    """Run ``fn`` in a daemon thread and wait at most ``timeout_s``.

    On timeout: ``on_timeout`` runs first (callers log the event there), the
    heartbeat stops and the local server is force-stopped. The worker thread
    is abandoned; Python cannot interrupt it.
    """
    done = threading.Event()
    results: list[LlmResult] = []
    errors: list[Exception] = []

    def _target() -> None:
        try:
            results.append(fn())
        except Exception as ex:
            errors.append(ex)
        finally:
            done.set()

    if heartbeat is not None:
        heartbeat.start()
    worker = threading.Thread(target=_target, daemon=True, name="llm-call")
    worker.start()

    if not done.wait(timeout_s):
        if on_timeout is not None:
            on_timeout()
        if heartbeat is not None:
            heartbeat.stop()
        stop_local_server_async()
        worker.join(timeout=0.2)
        return LlmCallOutcome(result=None, error=None, timed_out=True)

    if heartbeat is not None:
        heartbeat.stop()
    worker.join(timeout=0.2)
    return LlmCallOutcome(
        result=results[0] if results else None,
        error=errors[0] if errors else None,
        timed_out=False,
    )


# --- multimodal inputs -------------------------------------------------------

_SUPPORTED_MM_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
_MIN_MM_IMAGE_BYTES = 1024


def wants_multimodal_inputs(provider, settings) -> bool:
    """True when the provider takes images and the user turned them on."""
    supports = getattr(provider, "supports_multimodal_inputs", None)
    if not callable(supports):
        return False
    return bool(supports()) and bool(
        getattr(settings, "cloud_multimodal_enabled", False)
    )


def load_stored_multimodal_inputs(
    conn, *, message_fk: int, base_dir: Path
) -> list[LlmImageInput]:
    """Select images for a message that is already archived.

    Sync selects from the fresh archive result; resummarize only has the
    attachment and external asset rows saved during that sync.
    """
    attachments = [
        SavedAttachment(
            filename=str(r["filename"]),
            rel_path=str(r["rel_path"]),
            mime_type=r["mime_type"],
            size_bytes=int(r["size_bytes"] or 0),
            content_id=r["content_id"],
            is_inline=bool(r["is_inline"]),
        )
        for r in list_attachments(conn, message_fk=message_fk)
    ]
    external_assets = [
        ExternalAsset(
            original_url=str(r["original_url"]),
            rel_path=r["rel_path"],
            status=str(r["status"] or ""),
            mime_type=r["mime_type"],
            size_bytes=r["size_bytes"],
        )
        for r in list_external_assets(conn, message_fk=message_fk)
    ]
    return select_multimodal_inputs(
        base_dir=base_dir, attachments=attachments, external_assets=external_assets
    )


def _is_supported_mm_image(*, path: Path, mime_type: str | None) -> bool:
    mime = str(mime_type or "").strip().lower()
    if mime.startswith("image/") and mime not in {"image/svg+xml"}:
        return True
    return path.suffix.lower() in _SUPPORTED_MM_EXTS


def _image_dimensions(path: Path) -> tuple[int, int] | None:
    try:
        with Image.open(path) as img:
            w, h = img.size
            return int(w), int(h)
    except Exception:
        return None


def _should_exclude_mm_image(
    *,
    path: Path,
    mime_type: str | None,
    source: str,
    dims: tuple[int, int] | None,
) -> bool:
    name = path.name.lower()
    if any(k in name for k in ["logo", "icon", "favicon", "avatar", "sprite", "badge"]):
        return True

    if dims:
        width, height = dims
        if width <= 220 or height <= 120:
            return True
        if width >= 600 and height <= 140:
            return True
        if height > 0:
            aspect = width / height
            if width >= 600 and aspect >= 5.5 and height <= 180:
                return True
            if source == "inline_attachment" and aspect >= 4.0 and height <= 160:
                return True

    mime = str(mime_type or "").strip().lower()
    if mime == "image/gif" and dims and dims[1] <= 180:
        return True

    return False


def select_multimodal_inputs(
    *,
    base_dir: Path,
    attachments: list[SavedAttachment],
    external_assets: list[ExternalAsset],
    max_images: int = 3,
    max_total_bytes: int = 4 * 1024 * 1024,
) -> list[LlmImageInput]:
    wide_candidates: list[tuple[int, Path, str | None, str]] = []
    candidates: list[tuple[int, Path, str | None, str]] = []

    for a in attachments or []:
        p = (base_dir / str(a.rel_path or "")).resolve()
        if not p.is_file() or not _is_supported_mm_image(path=p, mime_type=a.mime_type):
            continue
        size = int(a.size_bytes or 0)
        source = "inline_attachment" if bool(a.is_inline) else "attachment"
        dims = _image_dimensions(p)
        if _should_exclude_mm_image(
            path=p, mime_type=a.mime_type, source=source, dims=dims
        ):
            continue
        item = (size, p, a.mime_type, source)
        if dims and dims[0] > 600:
            wide_candidates.append(item)
        else:
            if size <= _MIN_MM_IMAGE_BYTES:
                continue
            candidates.append(item)

    for a in external_assets or []:
        if str(a.status or "").strip().lower() != "downloaded":
            continue
        rel = str(a.rel_path or "").strip()
        if not rel:
            continue
        p = (base_dir / rel).resolve()
        if not p.is_file() or not _is_supported_mm_image(path=p, mime_type=a.mime_type):
            continue
        size = int(a.size_bytes or (p.stat().st_size if p.exists() else 0) or 0)
        dims = _image_dimensions(p)
        if _should_exclude_mm_image(
            path=p,
            mime_type=a.mime_type,
            source="external_asset",
            dims=dims,
        ):
            continue
        item = (size, p, a.mime_type, "external_asset")
        if dims and dims[0] > 600:
            wide_candidates.append(item)
        else:
            if size <= _MIN_MM_IMAGE_BYTES:
                continue
            candidates.append(item)

    wide_candidates.sort(key=lambda x: x[0], reverse=True)
    candidates.sort(key=lambda x: x[0], reverse=True)
    out: list[LlmImageInput] = []
    seen: set[str] = set()

    for _size, p, mime, source in wide_candidates:
        rp = str(p)
        if rp in seen:
            continue
        out.append(LlmImageInput(path=rp, mime_type=mime, detail="low", source=source))
        seen.add(rp)

    total = sum(p.stat().st_size for p in [Path(x.path) for x in out] if p.exists())

    for size, p, mime, source in candidates:
        rp = str(p)
        if rp in seen:
            continue
        if len(out) >= int(max_images):
            break
        if total + int(size) > int(max_total_bytes):
            continue
        out.append(LlmImageInput(path=rp, mime_type=mime, detail="low", source=source))
        seen.add(rp)
        total += int(size)
    return out
