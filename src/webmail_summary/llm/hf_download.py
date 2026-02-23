from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import requests


@dataclass(frozen=True)
class DownloadProgress:
    downloaded: int
    total: int | None


def hf_resolve_url(repo_id: str, filename: str) -> str:
    # Public download URL (redirects to CDN)
    return f"https://huggingface.co/{repo_id}/resolve/main/{filename}"


def download_with_resume(
    *,
    url: str,
    out_path: Path,
    chunk_size: int = 1024 * 1024,
    timeout_s: int = 300,
    on_progress=None,
) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    existing = out_path.stat().st_size if out_path.exists() else 0

    headers = {"User-Agent": "WebmailSummary/1.0"}
    mode = "wb"
    if existing > 0:
        headers["Range"] = f"bytes={existing}-"
        mode = "ab"

    with requests.get(
        url, headers=headers, stream=True, timeout=timeout_s, allow_redirects=True
    ) as r:
        # If server ignores Range, restart.
        if existing > 0 and r.status_code == 200:
            existing = 0
            mode = "wb"

        # If Range is not satisfiable, we likely already have the full file.
        if existing > 0 and r.status_code == 416:
            if on_progress:
                on_progress(DownloadProgress(downloaded=existing, total=existing))
            return out_path

        r.raise_for_status()
        total = None

        # Prefer Content-Range for accurate full size.
        cr = r.headers.get("Content-Range")
        if cr:
            # Example: bytes 123-456/789
            try:
                slash = cr.rsplit("/", 1)[-1].strip()
                if slash.isdigit():
                    total = int(slash)
            except Exception:
                total = None

        if total is None:
            cl = r.headers.get("Content-Length")
            if cl and cl.isdigit():
                total = int(cl) + existing

        downloaded = existing
        if on_progress:
            on_progress(DownloadProgress(downloaded=downloaded, total=total))

        with open(out_path, mode) as f:
            for chunk in r.iter_content(chunk_size=chunk_size):
                if not chunk:
                    continue
                f.write(chunk)
                downloaded += len(chunk)
                if on_progress:
                    on_progress(DownloadProgress(downloaded=downloaded, total=total))

    return out_path
