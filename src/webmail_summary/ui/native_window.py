from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import threading
import time
import webbrowser
from typing import Any, Protocol, cast

import requests

from webmail_summary.util.app_data import get_app_data_dir
from webmail_summary.util.platform_caps import is_windows, ui_platform_caps
from webmail_summary.util.process_control import (
    build_fresh_pyinstaller_env,
    detached_subprocess_kwargs,
)
from webmail_summary.util.single_instance import SingleInstanceLock
from webmail_summary.util.ui_lifecycle import (
    clear_ui_pid,
    read_bring_to_front_ts,
    signal_bring_to_front,
    write_ui_pid,
)


class _TrayIconLike(Protocol):
    def stop(self) -> Any: ...


def _server_command(port: int | None) -> list[str]:
    if bool(getattr(sys, "frozen", False)):
        cmd = [sys.executable, "serve", "--no-browser"]
        if port and int(port) > 0:
            cmd += ["--port", str(int(port))]
        return cmd

    cmd = [sys.executable, "-m", "webmail_summary", "serve", "--no-browser"]
    if port and int(port) > 0:
        cmd += ["--port", str(int(port))]
    return cmd


def _wait_for_active_url(data_dir, *, timeout_s: float = 12.0) -> str:
    url_path = data_dir / "active_url.txt"
    deadline = time.time() + float(timeout_s)
    last = ""
    while time.time() < deadline:
        try:
            if url_path.is_file():
                last = url_path.read_text(encoding="utf-8", errors="replace").strip()
                if last.startswith("http://") or last.startswith("https://"):
                    return last
        except Exception:
            pass
        time.sleep(0.05)
    return last


def _wait_for_active_url_change(
    data_dir,
    *,
    old_text: str,
    old_mtime: float,
    timeout_s: float = 30.0,
) -> str:
    url_path = data_dir / "active_url.txt"
    deadline = time.time() + float(timeout_s)
    last = ""
    while time.time() < deadline:
        try:
            if url_path.is_file():
                st = url_path.stat()
                txt = url_path.read_text(encoding="utf-8", errors="replace").strip()
                last = txt
                if not (txt.startswith("http://") or txt.startswith("https://")):
                    time.sleep(0.05)
                    continue
                if float(st.st_mtime) > float(old_mtime) + 1e-6:
                    return txt
                if txt and txt != old_text:
                    return txt
        except Exception:
            pass
        time.sleep(0.05)
    return last


def _wait_for_http_ready(
    url: str,
    *,
    timeout_s: float = 60.0,
    server_proc: subprocess.Popen | None = None,
) -> None:
    deadline = time.time() + float(timeout_s)
    last_exc: Exception | None = None
    while time.time() < deadline:
        if server_proc is not None:
            try:
                if server_proc.poll() is not None:
                    raise RuntimeError("server process exited")
            except Exception as e:
                last_exc = e
                break
        try:
            r = requests.get(url, timeout=(0.5, 1.5))
            if 200 <= r.status_code < 500:
                return
        except Exception as e:
            last_exc = e
        time.sleep(0.1)
    if last_exc:
        raise last_exc


def _is_reachable(url: str) -> bool:
    try:
        r = requests.get(url, timeout=(0.25, 0.75))
        return 200 <= r.status_code < 500
    except Exception:
        return False


def _show_error(title: str, message: str) -> None:
    if not is_windows():
        return
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(0, str(message), str(title), 0x10)
    except Exception:
        return


def _load_close_behavior(data_dir) -> str:
    db_path = data_dir / "db.sqlite3"
    try:
        conn = sqlite3.connect(str(db_path))
    except Exception:
        return "background"
    try:
        row = conn.execute(
            "SELECT value FROM settings WHERE key = ?", ("close_behavior",)
        ).fetchone()
        v = str(row[0] if row else "background").strip().lower()
        if v not in {"background", "exit"}:
            return "background"
        return v
    except Exception:
        return "background"
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _load_tray_image() -> object:
    from io import BytesIO
    from importlib import resources as importlib_resources

    from PIL import Image

    b = (
        importlib_resources.files("webmail_summary")
        .joinpath("ui", "static", "app-icon.png")
        .read_bytes()
    )
    return Image.open(BytesIO(b))


def _open_browser_fallback(url: str) -> bool:
    if not url:
        return False
    try:
        if webbrowser.open(url):
            return True
    except Exception:
        pass
    if is_windows():
        try:
            os.startfile(url)
            return True
        except Exception:
            pass
    return False


def _run_native_window(
    url: str,
    *,
    data_dir,
    server_proc: subprocess.Popen | None,
) -> None:
    import webview

    class _NativeApi:
        def __init__(self) -> None:
            self._prepared = False

        def prepare_update(self):
            if self._prepared:
                return True
            self._prepared = True
            quitting.set()
            try:
                icon = tray_state.get("icon")
                if icon is not None:
                    cast(_TrayIconLike, icon).stop()
            except Exception:
                pass
            try:
                window.destroy()
            except Exception:
                pass
            return True

    api = _NativeApi()
    window = webview.create_window(
        "webmail-summary",
        url,
        width=1200,
        height=820,
        min_size=(980, 680),
        js_api=api,
    )

    stop_evt = threading.Event()
    quitting = threading.Event()
    tray_state: dict[str, object] = {"icon": None, "thread": None}

    def _ensure_tray_icon() -> None:
        if tray_state.get("icon") is not None:
            return
        try:
            import pystray
        except Exception:
            return

        img = _load_tray_image()

        def _open(_icon=None, _item=None):
            try:
                window.show()
                window.restore()
            except Exception:
                pass

        def _exit(_icon=None, _item=None):
            quitting.set()
            try:
                requests.post(
                    url.rstrip("/") + "/lifecycle/request-exit",
                    timeout=(0.5, 1.5),
                )
            except Exception:
                pass
            try:
                window.destroy()
            except Exception:
                pass
            try:
                icon = tray_state.get("icon")
                if icon is not None:
                    cast(_TrayIconLike, icon).stop()
            except Exception:
                pass

        menu = pystray.Menu(
            pystray.MenuItem("프로그램 열기", _open, default=True),
            pystray.MenuItem("프로그램 종료", _exit),
        )
        icon = pystray.Icon("webmail-summary", img, "webmail-summary", menu)
        tray_state["icon"] = icon

        def _run_icon() -> None:
            try:
                icon.run()
            except Exception:
                pass

        th = threading.Thread(target=_run_icon, daemon=True)
        tray_state["thread"] = th
        th.start()

    def _bring_to_front_watcher() -> None:
        last_ts = read_bring_to_front_ts()
        while not stop_evt.wait(0.5):
            ts = read_bring_to_front_ts()
            if ts > last_ts:
                last_ts = ts
                try:
                    window.restore()
                    window.show()
                except Exception:
                    continue

    threading.Thread(target=_bring_to_front_watcher, daemon=True).start()

    def _on_closing() -> bool:
        if quitting.is_set():
            return True
        mode = _load_close_behavior(data_dir)
        if mode == "background":
            _ensure_tray_icon()
            try:
                window.hide()
            except Exception:
                pass
            return False
        return True

    def _on_closed() -> None:
        stop_evt.set()
        try:
            requests.post(
                url.rstrip("/") + "/lifecycle/request-exit",
                timeout=(0.5, 1.5),
            )
        except Exception:
            pass

        deadline = time.time() + 8.0
        while time.time() < deadline:
            try:
                if server_proc is None or server_proc.poll() is not None:
                    break
            except Exception:
                break
            time.sleep(0.05)

        try:
            if server_proc is not None and server_proc.poll() is None:
                server_proc.terminate()
        except Exception:
            pass

        deadline = time.time() + 4.0
        while time.time() < deadline:
            try:
                if server_proc is None or server_proc.poll() is not None:
                    break
            except Exception:
                break
            time.sleep(0.05)

        try:
            if server_proc is not None and server_proc.poll() is None:
                server_proc.kill()
        except Exception:
            pass

    window.events.closing += _on_closing
    window.events.closed += _on_closed
    webview.start()


def run_ui(*, port: int | None = None) -> None:
    if not ui_platform_caps().use_native_window:
        from webmail_summary.app.main import ServeOptions, serve

        serve(ServeOptions(port=port, open_browser=True))
        return

    data_dir = get_app_data_dir()
    ui_lock = SingleInstanceLock(data_dir / "ui.lock")
    if not ui_lock.acquire():
        signal_bring_to_front()
        return

    write_ui_pid(os.getpid())

    server_proc: subprocess.Popen | None = None
    try:
        url_path = data_dir / "active_url.txt"
        old_text = ""
        old_mtime = 0.0
        try:
            if url_path.is_file():
                old_text = url_path.read_text(
                    encoding="utf-8", errors="replace"
                ).strip()
                old_mtime = float(url_path.stat().st_mtime)
        except Exception:
            old_text = ""
            old_mtime = 0.0

        if old_text.startswith("http://") or old_text.startswith("https://"):
            url = old_text if _is_reachable(old_text) else ""
        else:
            url = ""

        if not url:
            cmd = _server_command(port)
            popen_kwargs: dict[str, object] = {"close_fds": True}
            popen_kwargs.update(detached_subprocess_kwargs())
            if bool(getattr(sys, "frozen", False)):
                popen_kwargs["env"] = build_fresh_pyinstaller_env()
            server_proc = subprocess.Popen(cmd, **popen_kwargs)

            url = _wait_for_active_url_change(
                data_dir, old_text=old_text, old_mtime=old_mtime
            )
            if not url:
                url = _wait_for_active_url(data_dir, timeout_s=12.0)
            if not url:
                raise RuntimeError("Failed to obtain active_url.txt from server")

            _wait_for_http_ready(url, timeout_s=90.0, server_proc=server_proc)

        try:
            _run_native_window(url, data_dir=data_dir, server_proc=server_proc)
        except Exception:
            if _open_browser_fallback(url):
                return
            raise
    except Exception as e:
        logs_hint = str(get_app_data_dir() / "logs" / "server.log")
        rt_hint = str(get_app_data_dir() / "runtime")
        _show_error(
            "webmail-summary",
            "UI start failed.\n\n"
            f"Reason: {type(e).__name__}: {str(e)[:200]}\n\n"
            f"Try: wait a few seconds and run again.\n"
            f"Logs: {logs_hint}\n"
            f"Runtime: {rt_hint}",
        )
        return
    finally:
        clear_ui_pid()
        ui_lock.release()
