import os
import sys
from pathlib import Path
from types import SimpleNamespace

from webmail_summary.ui.updates import _write_updater_script
from webmail_summary.util.process_control import build_fresh_pyinstaller_env
from webmail_summary.util.ssl_certs import configure_requests_ca_bundle


def test_build_fresh_pyinstaller_env_clears_private_vars(monkeypatch):
    monkeypatch.setenv("_PYI_ARCHIVE_FILE", "C:/old/app.exe")
    monkeypatch.setenv("_PYI_APPLICATION_HOME_DIR", "C:/Users/User/AppData/Local/Temp/_MEI123")
    monkeypatch.setenv("_PYI_PARENT_PROCESS_LEVEL", "1")
    monkeypatch.setenv("_PYI_SPLASH_IPC", "12345")
    monkeypatch.setenv("_MEIPASS2", "C:/Users/User/AppData/Local/Temp/_MEI123")
    monkeypatch.setenv("NORMAL_VAR", "keep-me")

    env = build_fresh_pyinstaller_env()

    assert env["PYINSTALLER_RESET_ENVIRONMENT"] == "1"
    assert env["NORMAL_VAR"] == "keep-me"
    assert "_PYI_ARCHIVE_FILE" not in env
    assert "_PYI_APPLICATION_HOME_DIR" not in env
    assert "_PYI_PARENT_PROCESS_LEVEL" not in env
    assert "_PYI_SPLASH_IPC" not in env
    assert "_MEIPASS2" not in env


def test_build_fresh_pyinstaller_env_drops_stale_tls_bundle_vars(monkeypatch):
    monkeypatch.setenv(
        "REQUESTS_CA_BUNDLE",
        "C:/Users/User/AppData/Local/Temp/_MEI123/cacert.pem",
    )
    monkeypatch.setenv("SSL_CERT_FILE", "C:/missing/cacert.pem")
    monkeypatch.setenv("NORMAL_VAR", "keep-me")

    env = build_fresh_pyinstaller_env()

    assert "REQUESTS_CA_BUNDLE" not in env
    assert "SSL_CERT_FILE" not in env
    assert env["NORMAL_VAR"] == "keep-me"


def test_configure_requests_ca_bundle_replaces_foreign_mei_cert_path(
    monkeypatch, tmp_path: Path
):
    stale_mei = tmp_path / "_MEIold"
    stale_mei.mkdir()
    stale_cert = stale_mei / "cacert.pem"
    stale_cert.write_text("old", encoding="utf-8")

    current_mei = tmp_path / "_MEInew"
    current_mei.mkdir()

    fresh_cert = tmp_path / "fresh-cacert.pem"
    fresh_cert.write_text("new", encoding="utf-8")

    monkeypatch.setenv("REQUESTS_CA_BUNDLE", str(stale_cert))
    monkeypatch.setenv("SSL_CERT_FILE", str(stale_cert))
    monkeypatch.setattr(
        "webmail_summary.util.ssl_certs.sys._MEIPASS",
        str(current_mei),
        raising=False,
    )
    monkeypatch.setitem(
        sys.modules,
        "certifi",
        SimpleNamespace(where=lambda: str(fresh_cert)),
    )

    configured = configure_requests_ca_bundle()

    assert configured == str(fresh_cert)
    assert os.environ["REQUESTS_CA_BUNDLE"] == str(fresh_cert)
    assert os.environ["SSL_CERT_FILE"] == str(fresh_cert)


def test_write_updater_script_resets_pyinstaller_env_before_relaunch(tmp_path: Path):
    script_path = tmp_path / "apply_update.ps1"
    _write_updater_script(script_path)
    text = script_path.read_text(encoding="utf-8-sig")

    assert "function Reset-PyInstallerEnv()" in text
    assert "$env:PYINSTALLER_RESET_ENVIRONMENT = '1'" in text
    assert "$vv.Name -like '_PYI_*' -or $vv.Name -eq '_MEIPASS2'" in text
    assert "Reset-PyInstallerEnv" in text
