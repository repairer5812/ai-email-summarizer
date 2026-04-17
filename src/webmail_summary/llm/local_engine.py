from __future__ import annotations

import io
import platform
from typing import Callable

import zipfile
import tarfile
from dataclasses import dataclass
from pathlib import Path
import re

import requests

from webmail_summary.util.app_data import get_engines_dir


class EngineInstallError(RuntimeError):
    pass


# Minimum llama.cpp build number required.
# b8637+ is needed for Gemma 4 (gemma4 architecture) support.
_MIN_BUILD_NUMBER = 8637


def _parse_build_number(tag: str) -> int:
    """Extract the numeric build number from a tag like 'b8083'."""
    m = re.search(r"b(\d+)", str(tag or ""))
    return int(m.group(1)) if m else 0


@dataclass(frozen=True)
class LlamaCppInstall:
    version_tag: str
    bin_dir: Path
    llama_cli_path: Path


def _safe_extract_tar_gz(*, fileobj: io.BytesIO, dest_dir: Path) -> None:
    dest_root = dest_dir.resolve()
    with tarfile.open(fileobj=fileobj, mode="r:gz") as tf:
        for member in tf.getmembers():
            name = str(member.name or "")
            if not name or Path(name).is_absolute():
                raise EngineInstallError(f"Unsafe llama.cpp archive member: {name!r}")
            target = (dest_dir / name).resolve()
            try:
                target.relative_to(dest_root)
            except ValueError as e:
                raise EngineInstallError(
                    f"Unsafe llama.cpp archive member: {name!r}"
                ) from e
        tf.extractall(dest_dir)


def _normalized_arch() -> str:
    m = (platform.machine() or "").strip().lower()
    if m in {"x86_64", "amd64", "x64"}:
        return "x64"
    if m in {"arm64", "aarch64"}:
        return "arm64"
    return m or "unknown"


def _pick_release_assets(assets: list[dict]) -> list[dict]:
    sys_name = (platform.system() or "").strip().lower()
    arch = _normalized_arch()

    def _archive_kind(name: str) -> str | None:
        n = (name or "").strip().lower()
        if n.endswith(".zip"):
            return "zip"
        if n.endswith(".tar.gz") or n.endswith(".tgz"):
            return "tar.gz"
        return None

    def score(a: dict) -> int:
        name = str(a.get("name") or "")
        n = name.lower()
        kind = _archive_kind(name)
        if kind is None:
            return -10_000

        if sys_name == "windows":
            if "win" not in n:
                return -10_000
            if arch == "x64" and ("x64" not in n and "x86_64" not in n):
                return -10_000
            if arch == "arm64" and "arm64" not in n:
                return -10_000
        elif sys_name == "darwin":
            if not any(x in n for x in ["mac", "darwin", "osx"]):
                return -10_000
            if arch == "x64" and not any(x in n for x in ["x64", "x86_64", "intel"]):
                return -10_000
            if arch == "arm64" and not any(x in n for x in ["arm64", "apple-silicon"]):
                return -10_000
        else:
            if "linux" not in n:
                return -10_000
            if arch == "x64" and ("x64" not in n and "x86_64" not in n):
                return -10_000
            if arch == "arm64" and "arm64" not in n:
                return -10_000

        s = 0
        # Strongly prefer the actual llama binary bundle.
        if n.startswith("llama-") and "bin-" in n:
            s += 5_000

        # Prefer packaging appropriate for the platform.
        if sys_name == "windows":
            if kind == "zip":
                s += 120
        else:
            # Newer llama.cpp releases frequently ship macOS/Linux as tar.gz.
            if kind == "tar.gz":
                s += 120
        if "cpu" in n:
            s += 2_000
        if sys_name == "windows" and "bin-win-cpu" in n:
            s += 500
        if sys_name == "darwin" and any(
            x in n for x in ["bin-macos", "bin-darwin", "bin-osx"]
        ):
            s += 500
        if sys_name not in {"windows", "darwin"} and "bin-linux" in n:
            s += 500

        # De-prioritize helper bundles that may not include executables.
        if n.startswith("cudart-"):
            s -= 2_000

        # Small preferences.
        if "avx2" in n:
            s += 50
        return s

    ranked = sorted(list(assets), key=score, reverse=True)
    return [a for a in ranked if score(a) > -10_000]


def ensure_llama_cpp_installed(
    *,
    timeout_s: int = 180,
    min_build: int = 0,
    on_progress: "Callable[[int, int, str], None] | None" = None,
) -> LlamaCppInstall:
    # Install under app-data/WebmailSummary/engines/llama.cpp/<tag>/
    engines = get_engines_dir() / "llama.cpp"
    engines.mkdir(parents=True, exist_ok=True)

    # Download latest release info first to compare versions.
    api = "https://api.github.com/repos/ggml-org/llama.cpp/releases/latest"
    latest_tag: str | None = None
    data: dict | None = None
    try:
        r = requests.get(api, timeout=(3.05, float(timeout_s)))
        r.raise_for_status()
        data = r.json()
        latest_tag = str(data.get("tag_name") or "").strip() or None
    except Exception:
        data = None
        latest_tag = None

    existing = find_llama_cpp_installed(min_build=min_build)
    if existing is not None:
        # If already at the latest tag, skip.
        if latest_tag is None or existing.version_tag == latest_tag:
            return existing
        # If latest is newer, upgrade.
        existing_build = _parse_build_number(existing.version_tag)
        latest_build = _parse_build_number(latest_tag)
        if latest_build <= existing_build:
            return existing
        # Fall through to download the newer engine.

    if data is None:
        # Network failed and we have no existing engine at all.
        if existing is not None:
            return existing
        raise EngineInstallError("Failed to fetch llama.cpp release metadata")

    tag = str(data.get("tag_name") or "latest").strip() or "latest"
    assets = data.get("assets") or []
    candidates = _pick_release_assets(list(assets))
    if not candidates:
        platform_name = (platform.system() or "unknown").strip() or "unknown"
        arch = _normalized_arch()
        names = [str(a.get("name") or "").strip() for a in list(assets)[:30]]
        names = [n for n in names if n]
        hint = ("; assets: " + ", ".join(names)) if names else ""
        raise EngineInstallError(
            f"No suitable {platform_name} {arch} archive asset found in llama.cpp release{hint}"
        )

    tag_dir = engines / tag
    tag_dir.mkdir(parents=True, exist_ok=True)

    last_err: str | None = None
    for a in candidates[:5]:
        name = str(a.get("name") or "").strip() or "asset.zip"
        url = str(a.get("browser_download_url") or "")
        if not url:
            last_err = f"asset has no download url: {name}"
            continue

        nlow = name.lower()
        if nlow.endswith(".zip"):
            kind = "zip"
        elif nlow.endswith(".tar.gz") or nlow.endswith(".tgz"):
            kind = "tar.gz"
        else:
            last_err = f"unsupported archive type: {name}"
            continue

        stem = re.sub(r"[^A-Za-z0-9._-]+", "_", name)
        extract_name = stem
        if extract_name.lower().endswith(".zip"):
            extract_name = extract_name[: -len(".zip")]
        elif extract_name.lower().endswith(".tar.gz"):
            extract_name = extract_name[: -len(".tar.gz")]
        elif extract_name.lower().endswith(".tgz"):
            extract_name = extract_name[: -len(".tgz")]
        extract_dir = tag_dir / extract_name
        extract_dir.mkdir(parents=True, exist_ok=True)

        # Download archive into memory (avoid partial extract) with a cap (~tens of MB)
        try:
            rr = requests.get(url, stream=True, timeout=(3.05, float(timeout_s)))
            rr.raise_for_status()
            content_length = int(rr.headers.get("content-length") or 0)
            buf = io.BytesIO()
            total = 0
            for chunk in rr.iter_content(chunk_size=1024 * 256):
                if not chunk:
                    continue
                total += len(chunk)
                if total > 1024 * 1024 * 900:
                    raise EngineInstallError("engine archive unexpectedly large")
                buf.write(chunk)
                if on_progress and content_length > 0:
                    on_progress(total, content_length, f"engine download ({name})")
        except Exception as e:
            last_err = f"Failed to download llama.cpp archive ({name}): {e}"
            continue

        buf.seek(0)
        try:
            if kind == "zip":
                with zipfile.ZipFile(buf) as z:
                    z.extractall(extract_dir)
            else:
                _safe_extract_tar_gz(fileobj=buf, dest_dir=extract_dir)
        except Exception as e:
            last_err = f"Failed to extract llama.cpp archive ({name}): {e}"
            continue

        cli = _find_llama_cli(extract_dir)
        if cli is None:
            last_err = f"No llama CLI exe found after extraction ({name})"
            continue

        # Clean up outdated engine directories.
        _cleanup_old_engines(engines, keep_tag=tag)

        return LlamaCppInstall(version_tag=tag, bin_dir=cli.parent, llama_cli_path=cli)

    raise EngineInstallError(last_err or "Failed to install llama.cpp")


def _cleanup_old_engines(engines_dir: Path, *, keep_tag: str) -> None:
    """Remove old llama.cpp engine directories, keeping only *keep_tag*."""
    try:
        for d in engines_dir.iterdir():
            if not d.is_dir() or d.name == keep_tag:
                continue
            import shutil

            shutil.rmtree(d, ignore_errors=True)
    except Exception:
        pass


def find_llama_cpp_installed(*, min_build: int = 0) -> LlamaCppInstall | None:
    """Find an installed llama.cpp engine.

    *min_build* defaults to 0 (accept any version).  Callers that need a
    newer engine (e.g. for Gemma 4 support) should pass ``_MIN_BUILD_NUMBER``.
    """
    engines = get_engines_dir() / "llama.cpp"
    if not engines.exists():
        return None

    candidates = sorted([p for p in engines.iterdir() if p.is_dir()], reverse=True)
    for c in candidates:
        cli = _find_llama_cli(c)
        if cli is None:
            continue
        build = _parse_build_number(c.name)
        if min_build > 0 and build > 0 and build < min_build:
            continue  # skip outdated engines
        return LlamaCppInstall(version_tag=c.name, bin_dir=c, llama_cli_path=cli)
    return None


def _find_llama_cli(root: Path) -> Path | None:
    # Common names across releases
    for name in [
        "llama-cli.exe",
        "llama.exe",
        "main.exe",
        "llama-cli",
        "llama",
        "llama-gemma3-cli.exe",
        "llama-gemma3-cli",
    ]:
        for p in root.rglob(name):
            if p.is_file():
                return p
    return None
