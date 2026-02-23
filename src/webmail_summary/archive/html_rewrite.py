from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from typing import Any, cast

from bs4 import BeautifulSoup
from bs4.element import Tag

from webmail_summary.util.net import DownloadBlocked, stream_download


@dataclass(frozen=True)
class ExternalAsset:
    original_url: str
    rel_path: str | None
    status: str
    mime_type: str | None
    size_bytes: int | None


def _hash_url(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8", errors="replace")).hexdigest()[:16]


def _guess_ext(content_type: str | None, url: str) -> str:
    # Keep it simple. Prefer URL suffix if any.
    p = urlparse(url)
    name = Path(p.path).name
    suf = Path(name).suffix
    if suf and len(suf) <= 6:
        return suf
    if content_type and "png" in content_type:
        return ".png"
    if content_type and "jpeg" in content_type:
        return ".jpg"
    if content_type and "gif" in content_type:
        return ".gif"
    if content_type and "webp" in content_type:
        return ".webp"
    if content_type and "svg" in content_type:
        return ".svg"
    if content_type and "css" in content_type:
        return ".css"
    if content_type and "javascript" in content_type:
        return ".js"
    if content_type and "mp4" in content_type:
        return ".mp4"
    return ".bin"


def rewrite_html_and_download_assets(
    *,
    html: str,
    external_dir: Path,
    cid_map: dict[str, str],
    max_total_bytes: int,
    timeout_s: int = 20,
    max_assets: int = 120,
    max_total_seconds: int = 90,
    user_agent: str = "WebmailSummary/1.0",
) -> tuple[str, list[ExternalAsset]]:
    external_dir.mkdir(parents=True, exist_ok=True)
    soup = BeautifulSoup(html, "html.parser")
    assets: list[ExternalAsset] = []

    started = time.time()
    deadline = time.monotonic() + float(max_total_seconds)

    remaining = max_total_bytes

    def download(url: str) -> ExternalAsset:
        nonlocal remaining
        if len(assets) >= int(max_assets):
            return ExternalAsset(
                original_url=url,
                rel_path=None,
                status="skipped_assets_limit",
                mime_type=None,
                size_bytes=None,
            )

        if (time.time() - started) > float(max_total_seconds):
            return ExternalAsset(
                original_url=url,
                rel_path=None,
                status="skipped_time_budget",
                mime_type=None,
                size_bytes=None,
            )
        if remaining <= 0:
            return ExternalAsset(
                original_url=url,
                rel_path=None,
                status="skipped_limit",
                mime_type=None,
                size_bytes=None,
            )

        try:
            chunks = []
            written = 0
            for chunk in stream_download(
                url=url,
                timeout_s=timeout_s,
                max_bytes=remaining,
                user_agent=user_agent,
                deadline_monotonic=deadline,
            ):
                chunks.append(chunk)
                written += len(chunk)
            remaining -= written
            blob = b"".join(chunks)

            # Best-effort content-type from magic bytes isn't worth it; just use extension heuristics.
            ext = _guess_ext(None, url)
            fname = f"{_hash_url(url)}{ext}"
            out_path = external_dir / fname
            out_path.write_bytes(blob)
            rel = f"external/{fname}"
            return ExternalAsset(
                original_url=url,
                rel_path=rel,
                status="downloaded",
                mime_type=None,
                size_bytes=written,
            )
        except DownloadBlocked as e:
            return ExternalAsset(
                original_url=url,
                rel_path=None,
                status=f"blocked:{e}",
                mime_type=None,
                size_bytes=None,
            )
        except Exception as e:
            return ExternalAsset(
                original_url=url,
                rel_path=None,
                status=f"error:{e}",
                mime_type=None,
                size_bytes=None,
            )

    # Rewrite src/href URLs
    for el in soup.find_all(True):
        if not isinstance(el, Tag):
            continue
        tag = el
        for attr in ("src", "href", "poster"):
            if attr not in tag.attrs:
                continue
            v = str(tag.get(attr) or "")
            if not v:
                continue
            if v.startswith("cid:"):
                cid = v[4:].strip().strip("<>")
                mapped = cid_map.get(cid)
                if mapped:
                    tag[attr] = mapped
                continue
            if v.startswith("http://") or v.startswith("https://"):
                asset = download(v)
                assets.append(asset)
                if asset.rel_path:
                    tag[attr] = asset.rel_path

    # Rewrite url(...) inside style attributes and <style> blocks
    url_re = re.compile(r"url\(([^)]+)\)")

    def rewrite_css(css_text: str) -> str:
        def repl(m: re.Match[str]) -> str:
            raw = m.group(1).strip().strip("\"'")
            if raw.startswith("cid:"):
                cid = raw[4:].strip().strip("<>")
                mapped = cid_map.get(cid)
                if mapped:
                    return f"url({mapped})"
                return m.group(0)
            if raw.startswith("http://") or raw.startswith("https://"):
                asset = download(raw)
                assets.append(asset)
                if asset.rel_path:
                    return f"url({asset.rel_path})"
            return m.group(0)

        return url_re.sub(repl, css_text)

    for el in soup.find_all(style=True):
        if isinstance(el, Tag) and "style" in el.attrs:
            el["style"] = rewrite_css(str(el.attrs.get("style") or ""))
    for el in soup.find_all("style"):
        if not isinstance(el, Tag):
            continue
        s = el.string
        if s is None:
            continue
        # NavigableString has replace_with; treat dynamically.
        ns = cast(Any, s)
        ns.replace_with(rewrite_css(str(s)))

    return str(soup), assets
