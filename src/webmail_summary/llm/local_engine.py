from __future__ import annotations

import io

import zipfile
from dataclasses import dataclass
from pathlib import Path
import re

import requests

from webmail_summary.util.app_data import get_engines_dir


class EngineInstallError(RuntimeError):
    pass


@dataclass(frozen=True)
class LlamaCppInstall:
    version_tag: str
    bin_dir: Path
    llama_cli_path: Path


def _pick_windows_assets(assets: list[dict]) -> list[dict]:
    def score(a: dict) -> int:
        name = str(a.get("name") or "")
        n = name.lower()
        if not name.endswith(".zip"):
            return -10_000
        if "win" not in n:
            return -10_000
        if "arm64" in n:
            return -10_000
        if "x64" not in n and "x86_64" not in n:
            return -10_000

        s = 0
        # Strongly prefer the actual llama binary bundle.
        if n.startswith("llama-") and "bin-win" in n:
            s += 5_000
        if "bin-win-cpu-x64" in n:
            s += 2_000
        if "cpu" in n:
            s += 200

        # De-prioritize helper bundles that may not include executables.
        if n.startswith("cudart-"):
            s -= 2_000

        # Small preferences.
        if "avx2" in n:
            s += 50
        return s

    ranked = sorted(list(assets), key=score, reverse=True)
    return [a for a in ranked if score(a) > -10_000]


def ensure_llama_cpp_installed(*, timeout_s: int = 60) -> LlamaCppInstall:
    # Install under %LOCALAPPDATA%\WebmailSummary\engines\llama.cpp\<tag>\
    engines = get_engines_dir() / "llama.cpp"
    engines.mkdir(parents=True, exist_ok=True)

    existing = find_llama_cpp_installed()
    if existing is not None:
        return existing

    # Download latest release info
    api = "https://api.github.com/repos/ggml-org/llama.cpp/releases/latest"
    try:
        r = requests.get(api, timeout=timeout_s)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        raise EngineInstallError(f"Failed to fetch llama.cpp release metadata: {e}")

    tag = str(data.get("tag_name") or "latest").strip() or "latest"
    assets = data.get("assets") or []
    candidates = _pick_windows_assets(list(assets))
    if not candidates:
        raise EngineInstallError(
            "No suitable Windows zip asset found in llama.cpp release"
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

        stem = re.sub(r"[^A-Za-z0-9._-]+", "_", name)
        extract_dir = tag_dir / stem.replace(".zip", "")
        extract_dir.mkdir(parents=True, exist_ok=True)

        # Download zip into memory (avoid partial extract) with a cap (CPU zips are ~tens of MB)
        try:
            rr = requests.get(url, stream=True, timeout=timeout_s)
            rr.raise_for_status()
            buf = io.BytesIO()
            total = 0
            for chunk in rr.iter_content(chunk_size=1024 * 256):
                if not chunk:
                    continue
                total += len(chunk)
                if total > 1024 * 1024 * 900:
                    raise EngineInstallError("engine zip unexpectedly large")
                buf.write(chunk)
        except Exception as e:
            last_err = f"Failed to download llama.cpp zip ({name}): {e}"
            continue

        buf.seek(0)
        try:
            with zipfile.ZipFile(buf) as z:
                z.extractall(extract_dir)
        except Exception as e:
            last_err = f"Failed to extract llama.cpp zip ({name}): {e}"
            continue

        cli = _find_llama_cli(extract_dir)
        if cli is None:
            last_err = f"No llama CLI exe found after extraction ({name})"
            continue
        return LlamaCppInstall(version_tag=tag, bin_dir=cli.parent, llama_cli_path=cli)

    raise EngineInstallError(last_err or "Failed to install llama.cpp")


def find_llama_cpp_installed() -> LlamaCppInstall | None:
    engines = get_engines_dir() / "llama.cpp"
    if not engines.exists():
        return None

    candidates = sorted([p for p in engines.iterdir() if p.is_dir()], reverse=True)
    for c in candidates:
        cli = _find_llama_cli(c)
        if cli is not None:
            return LlamaCppInstall(version_tag=c.name, bin_dir=c, llama_cli_path=cli)
    return None


def _find_llama_cli(root: Path) -> Path | None:
    # Common names across releases
    for name in ["llama-cli.exe", "llama.exe", "main.exe", "llama-cli", "llama"]:
        for p in root.rglob(name):
            if p.is_file():
                return p
    return None
