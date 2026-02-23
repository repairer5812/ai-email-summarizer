from __future__ import annotations

import ipaddress
import socket
import concurrent.futures
import time
from dataclasses import dataclass
from typing import Iterator
from urllib.parse import urlparse

import requests


class DownloadBlocked(Exception):
    pass


@dataclass(frozen=True)
class DownloadResult:
    url: str
    status_code: int
    content_type: str | None
    bytes_written: int


def _is_private_ip(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
        return (
            addr.is_private
            or addr.is_loopback
            or addr.is_link_local
            or addr.is_multicast
            or addr.is_reserved
        )
    except Exception:
        return True


def _validate_public_host(url: str) -> None:
    p = urlparse(url)
    host = p.hostname
    if not host:
        raise DownloadBlocked("missing hostname")

    # Block obvious local names
    if host.lower() in {"localhost"}:
        raise DownloadBlocked("localhost blocked")

    # If host is an IP literal, validate directly.
    try:
        socket.inet_pton(socket.AF_INET, host)
        if _is_private_ip(host):
            raise DownloadBlocked("private ip blocked")
        return
    except OSError:
        pass
    try:
        socket.inet_pton(socket.AF_INET6, host)
        if _is_private_ip(host):
            raise DownloadBlocked("private ip blocked")
        return
    except OSError:
        pass

    # Resolve host to A/AAAA and block if any private.
    # Note: getaddrinfo can hang for a long time on some Windows DNS setups.
    # Run it in a worker with a hard timeout.
    def _resolve() -> list[tuple]:
        return list(socket.getaddrinfo(host, None))

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            fut = ex.submit(_resolve)
            infos = fut.result(timeout=3.0)
    except concurrent.futures.TimeoutError:
        raise DownloadBlocked("dns resolve timeout")
    except Exception:
        raise DownloadBlocked("dns resolve failed")
    for _family, _socktype, _proto, _canonname, sockaddr in infos:
        ip: str = str(sockaddr[0])
        if _is_private_ip(ip):
            raise DownloadBlocked("private ip blocked")


def stream_download(
    *,
    url: str,
    timeout_s: int,
    max_bytes: int,
    user_agent: str,
    deadline_monotonic: float | None = None,
) -> Iterator[bytes]:
    p = urlparse(url)
    if p.scheme not in {"http", "https"}:
        raise DownloadBlocked(f"scheme not allowed: {p.scheme}")

    if deadline_monotonic is not None and time.monotonic() > float(deadline_monotonic):
        raise DownloadBlocked("time budget exceeded")

    _validate_public_host(url)

    headers = {"User-Agent": user_agent}
    # Use a shorter connect timeout to avoid long stalls.
    connect_timeout = min(10.0, float(timeout_s))
    with requests.get(
        url,
        headers=headers,
        stream=True,
        timeout=(connect_timeout, float(timeout_s)),
    ) as r:
        r.raise_for_status()
        total = 0
        for chunk in r.iter_content(chunk_size=1024 * 128):
            if deadline_monotonic is not None and time.monotonic() > float(
                deadline_monotonic
            ):
                raise DownloadBlocked("time budget exceeded")
            if not chunk:
                continue
            total += len(chunk)
            if total > max_bytes:
                raise DownloadBlocked("download exceeds max_bytes")
            yield chunk
