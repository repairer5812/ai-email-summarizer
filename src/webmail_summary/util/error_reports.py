from __future__ import annotations

from importlib import resources as importlib_resources
import platform
from pathlib import Path
import re
import sys
import time
import traceback
from typing import Mapping, Sequence

from webmail_summary.util.app_data import get_app_data_dir

_TEXT_TAIL_SUFFIXES = {".log", ".txt", ".json", ".md"}
_REDACT_KEYS = ("password", "token", "secret", "api_key", "apikey")


def get_error_reports_dir() -> Path:
    desktop = Path.home() / "Desktop"
    documents = Path.home() / "Documents"
    if desktop.exists():
        base = desktop / "WebmailSummary Error Reports"
    elif documents.exists():
        base = documents / "WebmailSummary Error Reports"
    else:
        base = get_app_data_dir() / "error-reports"
    base.mkdir(parents=True, exist_ok=True)
    return base


def mask_email_address(value: str) -> str:
    text = str(value or "").strip()
    if not text or "@" not in text:
        return text
    local, domain = text.split("@", 1)
    local = local.strip()
    domain = domain.strip()
    if not local:
        return f"***@{domain}"
    if len(local) == 1:
        return f"{local}***@{domain}"
    return f"{local[0]}***{local[-1]}@{domain}"


def _app_version() -> str:
    try:
        return (
            importlib_resources.files("webmail_summary")
            .joinpath("_version.txt")
            .read_text(encoding="utf-8", errors="replace")
            .strip()
        )
    except Exception:
        return ""


def _slug(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "").strip()).strip("-._")
    return text[:60] or "error"


def _format_detail_value(key: str, value: object) -> str:
    lowered = str(key or "").strip().lower()
    if any(marker in lowered for marker in _REDACT_KEYS):
        return "(redacted)"
    text = " ".join(str(value or "").strip().split())
    return text[:400] if text else "-"


def _read_text_tail(path: Path, *, max_lines: int = 80, max_chars: int = 5000) -> str:
    try:
        if path.suffix.lower() not in _TEXT_TAIL_SUFFIXES:
            return ""
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""
    lines = text.splitlines()
    tail = "\n".join(lines[-max_lines:])
    if len(tail) > max_chars:
        tail = tail[-max_chars:]
    return tail.strip()


def write_error_report(
    *,
    category: str,
    title: str,
    summary: str,
    exception: BaseException | None = None,
    details: Mapping[str, object] | None = None,
    related_paths: Sequence[str | Path] | None = None,
) -> Path:
    report_dir = get_error_reports_dir()
    ts = time.strftime("%Y%m%d-%H%M%S")
    report_path = report_dir / f"{ts}_{_slug(category or title)}.txt"

    lines: list[str] = [
        "Webmail Summary Error Report",
        "",
        f"Generated at: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"App version: {_app_version() or '(unknown)'}",
        f"Category: {category or '-'}",
        f"Title: {title or '-'}",
        f"Summary: {' '.join(str(summary or '').split()) or '-'}",
        "",
        "Environment",
        f"- OS: {platform.platform()}",
        f"- Python: {sys.version.split()[0]}",
        f"- Frozen: {bool(getattr(sys, 'frozen', False))}",
        "",
    ]

    if details:
        lines.append("Details")
        for key, value in details.items():
            lines.append(f"- {key}: {_format_detail_value(key, value)}")
        lines.append("")

    if exception is not None:
        lines.append("Exception")
        lines.append(f"{type(exception).__name__}: {' '.join(str(exception).split())}")
        lines.append("")
        lines.append("Traceback")
        lines.extend(
            line.rstrip("\n")
            for line in traceback.format_exception(
                type(exception), exception, exception.__traceback__
            )
        )
        lines.append("")

    if related_paths:
        lines.append("Related files")
        normalized_paths: list[Path] = []
        for raw in related_paths:
            path = Path(str(raw))
            normalized_paths.append(path)
            lines.append(f"- {path}")
        lines.append("")
        for path in normalized_paths:
            tail = _read_text_tail(path)
            if not tail:
                continue
            lines.append(f"===== Tail: {path.name} =====")
            lines.append(tail)
            lines.append("")

    report_path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    return report_path


__all__ = [
    "get_error_reports_dir",
    "mask_email_address",
    "write_error_report",
]
