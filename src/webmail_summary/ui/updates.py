from __future__ import annotations

import _thread
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from importlib import metadata as importlib_metadata
from importlib import resources as importlib_resources
from pathlib import Path
from urllib.parse import urlparse

import requests
from fastapi import APIRouter
from fastapi.responses import JSONResponse, RedirectResponse
from packaging.version import InvalidVersion, Version

from webmail_summary.index.settings import Settings, load_settings
from webmail_summary.ui.settings_gateway import db_path
from webmail_summary.ui.settings_gateway import get_setting
from webmail_summary.ui.settings_gateway import set_setting
from webmail_summary.util.app_data import get_app_data_dir
from webmail_summary.util.process_control import build_fresh_pyinstaller_env
from webmail_summary.util.ui_lifecycle import read_ui_pid

router = APIRouter()


def _normalize_version(value: str) -> str:
    v = str(value or "").strip()
    if v.lower().startswith("v"):
        v = v[1:]
    return v


def _get_repo_declared_version() -> str | None:
    try:
        repo_root = Path(__file__).resolve().parents[3]
        pyproject = repo_root / "pyproject.toml"
        if not pyproject.exists():
            return None
        text = pyproject.read_text(encoding="utf-8", errors="replace")
        m = re.search(r'^\s*version\s*=\s*"([^"]+)"\s*$', text, re.MULTILINE)
        if not m:
            return None
        v = _normalize_version(m.group(1))
        return v or None
    except Exception:
        return None


def _resolve_powershell_exe() -> str:
    windir = str(os.environ.get("WINDIR") or "").strip()
    candidates: list[Path] = []
    if windir:
        w = Path(windir)
        candidates.append(
            w / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
        )
        candidates.append(
            w / "Sysnative" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
        )
    for c in candidates:
        try:
            if c.is_file():
                return str(c)
        except Exception:
            continue
    return "powershell.exe"


@lru_cache(maxsize=1)
def _get_windows_frozen_exe_version() -> str | None:
    if os.name != "nt" or not bool(getattr(sys, "frozen", False)):
        return None
    exe = str(sys.executable or "").strip()
    if not exe:
        return None

    try:
        ps = (
            "$p=$env:WEBMAIL_SUMMARY_EXE_PATH;"
            "if([string]::IsNullOrWhiteSpace($p)){ exit 1 };"
            "$p=[System.IO.Path]::GetFullPath($p);"
            "$p=[System.Diagnostics.FileVersionInfo]::GetVersionInfo($p);"
            "$v=$p.ProductVersion;"
            "if([string]::IsNullOrWhiteSpace($v)){$v=$p.FileVersion};"
            "Write-Output $v"
        )
        env = dict(os.environ)
        env["WEBMAIL_SUMMARY_EXE_PATH"] = exe
        popen_kwargs: dict = {
            "text": True,
            "errors": "replace",
            "timeout": 3,
            "env": env,
        }
        if os.name == "nt":
            creationflags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
            popen_kwargs["creationflags"] = creationflags
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = subprocess.SW_HIDE
            popen_kwargs["startupinfo"] = si

        out = subprocess.check_output(
            [_resolve_powershell_exe(), "-NoProfile", "-Command", ps],
            **popen_kwargs,
        )
        raw = _normalize_version(str(out or "").strip())
        m = re.search(r"(\d+(?:\.\d+){1,3})", raw)
        if not m:
            return None
        return m.group(1)
    except Exception:
        return None


def _get_app_version() -> str:
    env_v = _normalize_version(os.environ.get("WEBMAIL_SUMMARY_VERSION", ""))
    if env_v:
        return env_v

    frozen_win_v = _get_windows_frozen_exe_version()
    if frozen_win_v:
        return frozen_win_v

    if not bool(getattr(sys, "frozen", False)):
        local_declared = _get_repo_declared_version()
        if local_declared:
            return local_declared

    try:
        p = importlib_resources.files("webmail_summary").joinpath("_version.txt")
        if p.is_file():
            raw = p.read_bytes()
            v = _normalize_version(raw.decode("utf-8", errors="replace"))
            if v and v != "0.0.0":
                return v
    except Exception:
        pass

    try:
        metadata_v = _normalize_version(importlib_metadata.version("webmail-summary"))
        if metadata_v and metadata_v != "0.0.0":
            return metadata_v
    except Exception:
        pass

    return "0.0.0"


def _parse_iso_datetime(value: str) -> datetime | None:
    s = str(value or "").strip()
    if not s:
        return None
    try:
        d = datetime.fromisoformat(s)
    except Exception:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d


def _is_probably_not_installer_url(url: str) -> bool:
    u = (url or "").strip().lower()
    if not u:
        return True
    needles = [
        "sha256sums",
        "sha256",
        "checksum",
        "checksums",
        "signature",
        "signatures",
    ]
    if any(x in u for x in needles):
        return True
    bad_ext = (".txt", ".sha256", ".sha256sum", ".sig", ".asc", ".md", ".json")
    return u.endswith(bad_ext)


_UPDATE_AUTO_CHECK_INTERVAL_HOURS = 6
_DEFAULT_UPDATE_REPO = "repairer5812/ai-email-summarizer"


def _effective_update_repo(settings: Settings) -> str:
    repo = str(settings.update_repo or "").strip()
    return repo or _DEFAULT_UPDATE_REPO


def _parse_github_repo(value: str) -> tuple[str, str] | None:
    repo = str(value or "").strip()
    if not repo:
        return None
    if repo.startswith("https://github.com/"):
        repo = repo.replace("https://github.com/", "", 1)
    repo = repo.strip("/")
    parts = repo.split("/")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        return None
    return parts[0], parts[1]


def _github_release_url(settings: Settings) -> str | None:
    parsed = _parse_github_repo(_effective_update_repo(settings))
    if not parsed:
        return None
    owner, repo = parsed
    return f"https://github.com/{owner}/{repo}/releases/latest"


def _pick_best_release_asset_url(assets: list[object]) -> str | None:
    os_name = (platform.system() or "").strip().lower()

    def _is_noise_filename(name: str) -> bool:
        n = (name or "").strip().lower()
        if not n:
            return True
        needles = [
            "sha256sums",
            "sha256",
            "checksum",
            "checksums",
            "signature",
            "signatures",
        ]
        if any(x in n for x in needles):
            return True
        bad_ext = (".txt", ".sha256", ".sha256sum", ".sig", ".asc", ".md", ".json")
        return n.endswith(bad_ext)

    def _score(name: str) -> int:
        n = (name or "").strip().lower()
        s = 0

        if "x64" in n or "amd64" in n:
            s += 10
        if "arm64" in n or "aarch64" in n:
            s -= 2

        if os_name == "windows":
            if n.endswith(".exe"):
                s += 50
            if n.endswith(".msi"):
                s += 45
            if "setup" in n or "installer" in n:
                s += 30
            if "webmail-summary.exe" in n:
                s -= 40
            if n.endswith(".exe") and ("setup" not in n and "installer" not in n):
                s -= 20
        elif os_name == "darwin":
            if n.endswith(".dmg"):
                s += 50
            if n.endswith(".pkg"):
                s += 45
        else:
            if n.endswith(".appimage"):
                s += 50
            if n.endswith(".deb"):
                s += 45
            if n.endswith(".rpm"):
                s += 40
            if n.endswith(".tar.gz") or n.endswith(".tgz"):
                s += 30

        if "portable" in n:
            s += 5

        return s

    best_url: str | None = None
    best_score = -10_000

    for a in assets or []:
        if not isinstance(a, dict):
            continue
        name = str(a.get("name") or "").strip()
        if _is_noise_filename(name):
            continue
        url = str(a.get("browser_download_url") or "").strip()
        if not url:
            continue
        sc = _score(name)
        if sc > best_score:
            best_score = sc
            best_url = url

    return best_url


def _build_update_state(settings: Settings) -> dict:
    now = datetime.now(timezone.utc)
    current = _get_app_version()
    latest = _normalize_version(settings.update_latest_version)

    has_update = False
    if latest:
        try:
            has_update = Version(latest) > Version(current)
        except InvalidVersion:
            has_update = latest != current

    snooze_until = _parse_iso_datetime(settings.update_snooze_until)
    is_snoozed = bool(snooze_until and snooze_until > now)
    is_skipped = bool(
        settings.update_skip_version and settings.update_skip_version == latest
    )

    download_url = settings.update_download_url
    if _is_probably_not_installer_url(download_url):
        download_url = _github_release_url(settings) or download_url

    return {
        "current": current,
        "latest": latest,
        "repo": _effective_update_repo(settings),
        "channel": settings.update_channel,
        "auto_check_enabled": bool(settings.update_auto_check_enabled),
        "last_checked_at": settings.update_last_checked_at,
        "last_check_status": settings.update_last_check_status,
        "download_url": download_url,
        "release_page_url": _github_release_url(settings),
        "snooze_until": settings.update_snooze_until,
        "has_update": has_update,
        "is_snoozed": is_snoozed,
        "is_skipped": is_skipped,
        "show_notice": bool(has_update and not is_snoozed and not is_skipped),
    }


def _check_github_release(conn, settings: Settings, *, force: bool = False) -> dict:
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    now_epoch = int(now.timestamp())

    parsed = _parse_github_repo(_effective_update_repo(settings))
    if not parsed:
        if force:
            set_setting(conn, "update_last_check_status", "repo_not_set")
            set_setting(conn, "update_last_checked_at", now_iso)
            conn.commit()
        return {"ok": False, "reason": "repo_not_set"}

    if not force and not settings.update_auto_check_enabled:
        return {"ok": False, "reason": "auto_check_disabled"}

    if not force:
        last = _parse_iso_datetime(settings.update_last_checked_at)
        if last is not None:
            delta_h = (now - last).total_seconds() / 3600.0
            if delta_h < float(_UPDATE_AUTO_CHECK_INTERVAL_HOURS):
                return {"ok": False, "reason": "not_due"}

    try:
        lock_until = int(
            (get_setting(conn, "update_check_lock_until") or "0").strip() or "0"
        )
    except Exception:
        lock_until = 0
    if lock_until > now_epoch:
        return {"ok": False, "reason": "locked"}

    set_setting(conn, "update_check_lock_until", str(now_epoch + 60))
    conn.commit()

    owner, repo = parsed
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": f"webmail-summary/{_get_app_version()}",
    }
    etag = (get_setting(conn, "update_check_etag") or "").strip()
    if etag:
        headers["If-None-Match"] = etag

    try:
        if settings.update_channel == "stable":
            url = f"https://api.github.com/repos/{owner}/{repo}/releases/latest"
            r = requests.get(url, headers=headers, timeout=(3.05, 10))
            if r.status_code == 304:
                set_setting(conn, "update_last_checked_at", now_iso)
                set_setting(conn, "update_last_check_status", "not_modified")
                conn.commit()
                return {"ok": True, "reason": "not_modified"}
            if r.status_code != 200:
                set_setting(conn, "update_last_checked_at", now_iso)
                set_setting(conn, "update_last_check_status", f"http_{r.status_code}")
                conn.commit()
                return {"ok": False, "reason": f"http_{r.status_code}"}
            release = r.json() or {}
        else:
            url = f"https://api.github.com/repos/{owner}/{repo}/releases?per_page=20"
            r = requests.get(url, headers=headers, timeout=(3.05, 10))
            if r.status_code == 304:
                set_setting(conn, "update_last_checked_at", now_iso)
                set_setting(conn, "update_last_check_status", "not_modified")
                conn.commit()
                return {"ok": True, "reason": "not_modified"}
            if r.status_code != 200:
                set_setting(conn, "update_last_checked_at", now_iso)
                set_setting(conn, "update_last_check_status", f"http_{r.status_code}")
                conn.commit()
                return {"ok": False, "reason": f"http_{r.status_code}"}
            items = r.json() or []
            release = {}
            if isinstance(items, list):
                for it in items:
                    if not isinstance(it, dict):
                        continue
                    if bool(it.get("draft")):
                        continue
                    release = it
                    break

        new_etag = str(r.headers.get("ETag") or "").strip()
        if new_etag:
            set_setting(conn, "update_check_etag", new_etag)

        tag = _normalize_version(
            str(release.get("tag_name") or release.get("name") or "")
        )
        html_url = str(release.get("html_url") or "").strip()
        download_url = html_url
        assets = release.get("assets")
        if isinstance(assets, list) and assets:
            picked = _pick_best_release_asset_url(assets)
            if picked:
                download_url = picked

        set_setting(conn, "update_latest_version", tag)
        set_setting(conn, "update_download_url", download_url)
        set_setting(conn, "update_last_checked_at", now_iso)
        set_setting(conn, "update_last_check_status", "ok")
        conn.commit()
        return {"ok": True, "reason": "ok"}
    except Exception:
        set_setting(conn, "update_last_checked_at", now_iso)
        set_setting(conn, "update_last_check_status", "network_error")
        conn.commit()
        return {"ok": False, "reason": "network_error"}
    finally:
        set_setting(conn, "update_check_lock_until", "0")
        conn.commit()


def _updates_dir() -> Path:
    p = get_app_data_dir() / "updates"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _updater_status_path() -> Path:
    return _updates_dir() / "apply_update_status.json"


def _read_updater_status(path: Path) -> dict[str, object] | None:
    try:
        if not path.is_file():
            return None
        raw = path.read_text(encoding="utf-8-sig", errors="replace").strip()
        if not raw:
            return None
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
    except Exception:
        return None
    return None


def _download_to_path_with_progress(url: str, dst: Path, *, progress_cb) -> None:
    tmp = dst.with_suffix(dst.suffix + ".part")
    with requests.get(url, stream=True, timeout=(5, 90)) as r:
        r.raise_for_status()
        total = 0
        try:
            total = int(r.headers.get("Content-Length") or 0)
        except Exception:
            total = 0
        written = 0
        last_report = 0.0
        with tmp.open("wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 256):
                if not chunk:
                    continue
                f.write(chunk)
                written += len(chunk)
                now = time.time()
                if now - last_report >= 0.25:
                    last_report = now
                    try:
                        progress_cb(int(written), int(total))
                    except Exception:
                        pass
        try:
            progress_cb(int(written), int(total))
        except Exception:
            pass
    tmp.replace(dst)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b = f.read(1024 * 1024)
            if not b:
                break
            h.update(b)
    return h.hexdigest().lower()


def _parse_sha256sums(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in str(text or "").splitlines():
        m = re.match(r"^\s*([A-Fa-f0-9]{64})\s+\*?(.+?)\s*$", line)
        if not m:
            continue
        out[str(m.group(2)).strip().lower()] = str(m.group(1)).strip().lower()
    return out


def _guess_expected_sha256_from_release(
    settings: Settings, installer_name: str
) -> str | None:
    parsed = _parse_github_repo(_effective_update_repo(settings))
    if not parsed:
        return None
    owner, repo = parsed
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": f"webmail-summary/{_get_app_version()}",
    }
    url = f"https://api.github.com/repos/{owner}/{repo}/releases/latest"
    r = requests.get(url, headers=headers, timeout=(3.05, 10))
    if r.status_code != 200:
        return None
    release = r.json() or {}
    assets = release.get("assets") or []
    if not isinstance(assets, list):
        return None

    checksum_url = ""
    for a in assets:
        if not isinstance(a, dict):
            continue
        name = str(a.get("name") or "").strip().lower()
        dl = str(a.get("browser_download_url") or "").strip()
        if not dl:
            continue
        if "sha256" in name and name.endswith(".txt"):
            checksum_url = dl
            break
        if "sha256sums" in name:
            checksum_url = dl
            break
    if not checksum_url:
        return None

    rr = requests.get(checksum_url, timeout=(3.05, 15))
    if rr.status_code != 200:
        return None
    mapping = _parse_sha256sums(rr.text)
    target = installer_name.strip().lower()
    if target in mapping:
        return mapping[target]
    for k, v in mapping.items():
        if k.endswith(target):
            return v
    return None


def _relaunch_command() -> tuple[str, str]:
    exe = sys.executable

    try:
        local_appdata = os.environ.get("LOCALAPPDATA") or ""
        installed_exe = (
            Path(local_appdata) / "Programs" / "webmail-summary" / "webmail-summary.exe"
        )
        if installed_exe.is_file():
            return str(installed_exe), json.dumps(["ui"], ensure_ascii=True)
    except Exception:
        pass

    if bool(getattr(sys, "frozen", False)):
        return exe, json.dumps(["ui"], ensure_ascii=True)

    return exe, json.dumps(["-m", "webmail_summary", "ui"], ensure_ascii=True)


def _write_updater_script(path: Path) -> None:
    script = r"""
param(
  [int]$ParentPid,
  [int]$UiPid = 0,
  [string]$InstallerPath,
  [string]$RelaunchExe,
  [string]$RelaunchArgsJson,
  [string]$InstallLogPath,
  [string]$StatusPath,
  [string]$InstalledExePath,
  [string]$ExpectedVersion
)
$ErrorActionPreference = 'Stop'
Start-Sleep -Seconds 2

function Write-UpdateStatus([string]$Stage, [string]$Message, [int]$Code = 0) {
  try {
    $obj = [ordered]@{
      stage = $Stage
      message = $Message
      code = $Code
      updated_at = (Get-Date).ToString('o')
    }
    ($obj | ConvertTo-Json -Compress) | Set-Content -Path $StatusPath -Encoding UTF8 -Force
  } catch {}
}

function Stop-PidIfRunning([int]$TargetPid) {
  if ($TargetPid -le 0) { return }
  try {
    Wait-Process -Id $TargetPid -Timeout 10 -ErrorAction SilentlyContinue | Out-Null
  } catch {}
  try {
    if (Get-Process -Id $TargetPid -ErrorAction SilentlyContinue) {
      Stop-Process -Id $TargetPid -Force -ErrorAction SilentlyContinue
      Start-Sleep -Seconds 1
    }
  } catch {}
}

function Stop-ImageIfRunning([string]$ImageName) {
  if ([string]::IsNullOrWhiteSpace($ImageName)) { return }
  try {
    $procs = Get-Process -Name $ImageName -ErrorAction SilentlyContinue
    foreach ($pp in $procs) {
      try {
        Stop-Process -Id $pp.Id -Force -ErrorAction SilentlyContinue
      } catch {}
    }
  } catch {}
}

function Reset-PyInstallerEnv() {
  try { $env:PYINSTALLER_RESET_ENVIRONMENT = '1' } catch {}
  try {
    $vars = Get-ChildItem Env: -ErrorAction SilentlyContinue
    foreach ($vv in $vars) {
      if ($vv.Name -like '_PYI_*' -or $vv.Name -eq '_MEIPASS2') {
        try { Remove-Item -Path ('Env:' + $vv.Name) -ErrorAction SilentlyContinue } catch {}
      }
    }
  } catch {}
}

Write-UpdateStatus 'script_started' 'update handoff started'

if (!(Test-Path $InstallerPath)) {
  Write-UpdateStatus 'error' 'installer file not found' 1001
  exit 1001
}

try {
  Stop-PidIfRunning $UiPid
  try {
    Wait-Process -Id $ParentPid -Timeout 90 -ErrorAction SilentlyContinue | Out-Null
  } catch {}
  try {
    if (Get-Process -Id $ParentPid -ErrorAction SilentlyContinue) {
      Stop-Process -Id $ParentPid -Force -ErrorAction SilentlyContinue
      Start-Sleep -Seconds 1
    }
  } catch {}

  Stop-ImageIfRunning 'webmail-summary'
  Stop-ImageIfRunning 'llama-server'
  Start-Sleep -Seconds 2

  # Retry kill in case processes respawned or were slow to stop.
  Stop-ImageIfRunning 'webmail-summary'
  Stop-ImageIfRunning 'llama-server'
  Start-Sleep -Seconds 1

  # Clean stale _MEI temp dirs that block PyInstaller bootstrapper.
  try {
    $meiDirs = Get-ChildItem -Path $env:TEMP -Directory -Filter '_MEI*' -ErrorAction SilentlyContinue
    foreach ($d in $meiDirs) {
      try { Remove-Item -Path $d.FullName -Recurse -Force -ErrorAction SilentlyContinue } catch {}
    }
  } catch {}

  Write-UpdateStatus 'installer_launching' 'installer launching'
  $args = @('/SP-', '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/CLOSEAPPLICATIONS', '/FORCECLOSEAPPLICATIONS', '/LOGCLOSEAPPLICATIONS', ('/LOG=' + $InstallLogPath))
  $p = Start-Process -FilePath $InstallerPath -ArgumentList $args -Wait -PassThru -ErrorAction Stop
  $code = 0
  if ($null -ne $p) { $code = [int]$p.ExitCode }

  if ($code -ne 0) {
    Write-UpdateStatus 'error' ('installer exit code: ' + $code) $code
    exit $code
  }

  Write-UpdateStatus 'installer_succeeded' 'installer completed' $code

  $targetExe = $RelaunchExe
  if (!( [string]::IsNullOrWhiteSpace($InstalledExePath) ) -and (Test-Path $InstalledExePath)) {
    $targetExe = $InstalledExePath
  }

  if (!( [string]::IsNullOrWhiteSpace($ExpectedVersion) ) -and (Test-Path $targetExe)) {
    try {
      $expected = [string]$ExpectedVersion
      $expected = $expected.Trim()
      if ($expected.StartsWith('v')) {
        $expected = $expected.Substring(1)
      }
      if ($expected -match '^([0-9]+(?:\.[0-9]+){1,3})') {
        $expected = $matches[1]
      }

      $vi = (Get-Item $targetExe).VersionInfo
      $pv = [string]$vi.ProductVersion
      if ([string]::IsNullOrWhiteSpace($pv)) {
        $pv = [string]$vi.FileVersion
      }
      $pv = $pv.Trim()
      if ($pv.StartsWith('v')) {
        $pv = $pv.Substring(1)
      }
      if ($pv -match '^([0-9]+(?:\.[0-9]+){1,3})') {
        $pv = $matches[1]
      }

      $expParts = @($expected.Split('.') | ForEach-Object { [int]$_ })
      $actParts = @($pv.Split('.') | ForEach-Object { [int]$_ })
      $verOk = $true
      for ($i = 0; $i -lt $expParts.Count; $i++) {
        if ($i -ge $actParts.Count -or $actParts[$i] -ne $expParts[$i]) {
          $verOk = $false
          break
        }
      }
      if (-not $verOk) {
        Write-UpdateStatus 'error' ('installed version mismatch: expected ' + $expected + ', actual ' + $pv) 1003
        exit 1003
      }
    } catch {
      $msgv = ''
      try { $msgv = $_.Exception.Message } catch { $msgv = 'unknown version check error' }
      Write-UpdateStatus 'error' ('installed version check failed: ' + $msgv) 1004
      exit 1004
    }
  }

  if (Test-Path $targetExe) {
    Reset-PyInstallerEnv
    $argsList = @()
    if (![string]::IsNullOrWhiteSpace($RelaunchArgsJson)) {
      try {
        $tmp = ConvertFrom-Json $RelaunchArgsJson
        if ($tmp -is [System.Array]) { $argsList = $tmp }
        elseif ($null -ne $tmp) { $argsList = @($tmp) }
      } catch {
        $argsList = @($RelaunchArgsJson)
      }
    }
    if ($argsList.Count -eq 0) {
      Start-Process -FilePath $targetExe -ErrorAction SilentlyContinue | Out-Null
    } else {
      Start-Process -FilePath $targetExe -ArgumentList $argsList -ErrorAction SilentlyContinue | Out-Null
    }
  }
  Write-UpdateStatus 'done' 'update install completed' $code
  exit $code
} catch {
  $msg = ''
  try { $msg = $_.Exception.Message } catch { $msg = 'unknown error' }
  Write-UpdateStatus 'error' ('update execution failed: ' + $msg) 1999
  exit 1999
}
""".strip()
    path.write_text(script + "\n", encoding="utf-8-sig")


def _schedule_app_shutdown(delay_s: float = 2.0) -> None:
    def _worker() -> None:
        time.sleep(float(delay_s))
        try:
            from webmail_summary.jobs.runner import get_runner

            get_runner().terminate_all()
        except Exception:
            pass
        try:
            from webmail_summary.llm.llamacpp_server import stop_server

            stop_server(force=True)
        except Exception:
            pass
        try:
            _thread.interrupt_main()
        except Exception:
            pass

        deadline = time.time() + 8.0
        while time.time() < deadline:
            time.sleep(0.1)
        os._exit(0)

    threading.Thread(target=_worker, daemon=True).start()


_update_apply_lock = threading.Lock()
_update_apply_thread: threading.Thread | None = None


def _set_update_apply_state(conn, *, stage: str, percent: int, message: str) -> None:
    set_setting(conn, "update_apply_stage", str(stage))
    set_setting(conn, "update_apply_percent", str(int(percent)))
    set_setting(conn, "update_apply_message", str(message or ""))
    set_setting(conn, "update_apply_updated_at", datetime.now(timezone.utc).isoformat())
    conn.commit()


def _get_update_apply_state(conn) -> dict:
    stage = str(get_setting(conn, "update_apply_stage") or "idle")
    try:
        percent = int(float(get_setting(conn, "update_apply_percent") or 0))
    except Exception:
        percent = 0
    msg = str(get_setting(conn, "update_apply_message") or "")
    updated_at = str(get_setting(conn, "update_apply_updated_at") or "")
    if percent < 0:
        percent = 0
    if percent > 100:
        percent = 100
    return {
        "stage": stage,
        "percent": percent,
        "message": msg,
        "updated_at": updated_at,
    }


def _run_update_apply_thread(*, db_path: Path) -> None:
    from webmail_summary.index.db import get_conn

    conn = get_conn(db_path)
    should_shutdown = False
    try:
        settings = load_settings(conn)
        _check_github_release(conn, settings, force=True)
        settings = load_settings(conn)
        st = _build_update_state(settings)
        if not bool(st.get("has_update")):
            _set_update_apply_state(
                conn, stage="idle", percent=0, message="이미 최신 버전입니다."
            )
            return

        download_url = str(st.get("download_url") or "").strip()
        if not download_url or _is_probably_not_installer_url(download_url):
            _set_update_apply_state(
                conn,
                stage="error",
                percent=0,
                message="설치 파일 URL을 찾지 못했습니다. 수동 업데이트를 시도하세요.",
            )
            return

        parsed = urlparse(download_url)
        filename = Path(parsed.path).name or "webmail-summary-setup-windows-x64.exe"
        if not filename.lower().endswith(".exe"):
            filename = "webmail-summary-setup-windows-x64.exe"

        low_name = filename.strip().lower()
        if ("setup" not in low_name and "installer" not in low_name) or (
            low_name == "webmail-summary.exe"
        ):
            _set_update_apply_state(
                conn,
                stage="error",
                percent=0,
                message=(
                    "설치형 업데이트 파일을 찾지 못했습니다. "
                    "수동 다운로드로 setup 설치 파일을 실행하세요."
                ),
            )
            return

        updates_dir = _updates_dir()
        installer_path = updates_dir / filename

        _set_update_apply_state(
            conn, stage="downloading", percent=0, message="업데이트 파일 다운로드 중..."
        )

        def _progress(cur: int, total: int) -> None:
            c = int(cur)
            t = int(total)
            p = 0
            if t > 0:
                p = int((c * 100) / t)
            msg = "업데이트 파일 다운로드 중..."
            if t > 0:
                mb = 1024 * 1024
                msg = f"업데이트 파일 다운로드 중... ({c / mb:.1f}MB / {t / mb:.1f}MB)"
            else:
                msg = f"업데이트 파일 다운로드 중... ({c / 1024 / 1024:.1f}MB)"
            _set_update_apply_state(conn, stage="downloading", percent=p, message=msg)

        _download_to_path_with_progress(
            download_url, installer_path, progress_cb=_progress
        )

        _set_update_apply_state(
            conn, stage="verifying", percent=100, message="다운로드 검증 중..."
        )
        downloaded_sha = _sha256_file(installer_path)
        expected_sha = _guess_expected_sha256_from_release(settings, filename)
        if expected_sha and downloaded_sha != expected_sha.strip().lower():
            try:
                installer_path.unlink(missing_ok=True)
            except Exception:
                pass
            _set_update_apply_state(
                conn,
                stage="error",
                percent=0,
                message="다운로드 파일 검증(SHA256)에 실패했습니다. 업데이트를 중단합니다.",
            )
            return

        _set_update_apply_state(
            conn,
            stage="launching",
            percent=100,
            message="설치 프로그램 실행 준비 중...",
        )
        script_path = updates_dir / "apply_update.ps1"
        _write_updater_script(script_path)
        install_log_path = updates_dir / "installer.log"
        status_path = _updater_status_path()
        installed_exe_path = (
            Path(str(os.environ.get("LOCALAPPDATA") or ""))
            / "Programs"
            / "webmail-summary"
            / "webmail-summary.exe"
        )
        expected_version = _normalize_version(str(st.get("latest") or ""))
        try:
            status_path.unlink(missing_ok=True)
        except Exception:
            pass
        relaunch_exe, relaunch_args_json = _relaunch_command()
        ui_pid = int(read_ui_pid() or 0)

        cmd = [
            _resolve_powershell_exe(),
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-WindowStyle",
            "Hidden",
            "-File",
            str(script_path),
            "-ParentPid",
            str(os.getpid()),
            "-UiPid",
            str(ui_pid),
            "-InstallerPath",
            str(installer_path),
            "-RelaunchExe",
            str(relaunch_exe),
            "-RelaunchArgsJson",
            str(relaunch_args_json),
            "-InstallLogPath",
            str(install_log_path),
            "-StatusPath",
            str(status_path),
            "-InstalledExePath",
            str(installed_exe_path),
            "-ExpectedVersion",
            str(expected_version),
        ]
        creationflags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
        popen_kwargs: dict = {
            "close_fds": True,
            "creationflags": creationflags,
            "env": build_fresh_pyinstaller_env(),
        }
        if os.name == "nt":
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = subprocess.SW_HIDE
            popen_kwargs["startupinfo"] = si
        updater_proc = subprocess.Popen(cmd, **popen_kwargs)
        time.sleep(0.25)
        if updater_proc.poll() is not None:
            raise RuntimeError(
                "업데이트 핸드오프 프로세스가 즉시 종료되었습니다. 다시 시도하거나 수동 업데이트를 사용하세요."
            )

        status_deadline = time.monotonic() + 8.0
        while time.monotonic() < status_deadline:
            st_data = _read_updater_status(status_path)
            stage_name = str((st_data or {}).get("stage") or "")
            if stage_name == "error":
                msg = str((st_data or {}).get("message") or "업데이트 실행 실패")
                raise RuntimeError(msg)
            if stage_name in {
                "script_started",
                "installer_launching",
                "installer_succeeded",
                "done",
            }:
                break
            if updater_proc.poll() is not None:
                raise RuntimeError("업데이트 핸드오프가 중간에 종료되었습니다.")
            time.sleep(0.2)

        if not _read_updater_status(status_path):
            raise RuntimeError("업데이트 핸드오프 상태를 확인하지 못했습니다.")

        _set_update_apply_state(
            conn,
            stage="installer_started",
            percent=100,
            message="설치 프로그램을 실행했습니다. 잠시 후 앱이 종료되고 자동으로 다시 실행됩니다.",
        )
        should_shutdown = True
    except Exception as e:
        try:
            _set_update_apply_state(
                conn,
                stage="error",
                percent=0,
                message=f"업데이트 실패: {str(e)[:200]}",
            )
        except Exception:
            pass
    finally:
        conn.close()

    if should_shutdown:
        _schedule_app_shutdown()


@router.get("/updates/apply-status")
def updates_apply_status():
    from webmail_summary.index.db import get_conn

    conn = get_conn(db_path())
    try:
        return {"ok": True, **_get_update_apply_state(conn)}
    finally:
        conn.close()


@router.post("/updates/apply-start")
def updates_apply_start():
    if (platform.system() or "").strip().lower() != "windows":
        return JSONResponse(
            {
                "ok": False,
                "message": "자동 업데이트 설치는 현재 Windows에서만 지원됩니다.",
            },
            status_code=400,
        )

    global _update_apply_thread
    try:
        from webmail_summary.index.db import get_conn

        conn0 = get_conn(db_path())
        try:
            _set_update_apply_state(
                conn0,
                stage="starting",
                percent=0,
                message="업데이트 준비 중...",
            )
        finally:
            conn0.close()
    except Exception:
        pass

    with _update_apply_lock:
        t = _update_apply_thread
        if t is not None and t.is_alive():
            return JSONResponse(
                {"ok": False, "message": "이미 업데이트를 진행 중입니다."},
                status_code=409,
            )
        _update_apply_thread = threading.Thread(
            target=_run_update_apply_thread,
            kwargs={"db_path": db_path()},
            daemon=True,
        )
        _update_apply_thread.start()

    return {"ok": True, "message": "업데이트를 시작합니다."}


@router.post("/updates/apply-now")
def updates_apply_now():
    return updates_apply_start()


@router.post("/updates/snooze-week")
def updates_snooze_week():
    from webmail_summary.index.db import get_conn

    conn = get_conn(db_path())
    try:
        until = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
        set_setting(conn, "update_snooze_until", until)
        conn.commit()
    finally:
        conn.close()
    return RedirectResponse("/", status_code=303)


@router.post("/updates/snooze-day")
def updates_snooze_day():
    from webmail_summary.index.db import get_conn

    conn = get_conn(db_path())
    try:
        until = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        set_setting(conn, "update_snooze_until", until)
        conn.commit()
    finally:
        conn.close()
    return RedirectResponse("/", status_code=303)


@router.post("/updates/skip-latest")
def updates_skip_latest():
    from webmail_summary.index.db import get_conn

    conn = get_conn(db_path())
    try:
        latest = (get_setting(conn, "update_latest_version") or "").strip()
        set_setting(conn, "update_skip_version", latest)
        conn.commit()
    finally:
        conn.close()
    return RedirectResponse("/", status_code=303)


@router.post("/updates/check-now")
def updates_check_now():
    from webmail_summary.index.db import get_conn

    conn = get_conn(db_path())
    status = "error"
    try:
        settings = load_settings(conn)
        result = _check_github_release(conn, settings, force=True)
        settings = load_settings(conn)
        st = _build_update_state(settings)

        if bool(st.get("has_update")):
            status = "available"
        else:
            reason = str((result or {}).get("reason") or "").strip().lower()
            if reason in {"ok", "not_modified", ""}:
                status = "latest"
            elif reason in {"network_error", "repo_not_set", "locked"}:
                status = "error"
            else:
                status = "latest"
    finally:
        conn.close()
    return RedirectResponse(f"/?update_checked={status}", status_code=303)
