from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    imap_host: str
    imap_port: int
    imap_user: str
    imap_folder: str
    sender_filter: str
    obsidian_root: str
    llm_backend: str
    cloud_provider: str
    cloud_multimodal_enabled: bool
    openrouter_model: str
    local_model_id: str
    external_max_bytes: int
    revert_seen_after_sync: bool
    user_roles: list[str]
    user_interests: str
    ui_theme: str
    close_behavior: str
    update_channel: str
    update_latest_version: str
    update_auto_check_enabled: bool
    update_repo: str
    update_snooze_until: str
    update_skip_version: str
    update_last_checked_at: str
    update_download_url: str
    update_last_check_status: str
    local_engine: str = "auto"  # "auto" | "llamacpp" | "mlx"
    new_models_v2_dismissed: bool = False


def get_setting(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return str(row[0]) if row else None


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def _normalize_ui_theme(value: str | None) -> str:
    v = str(value or "").strip().lower()
    legacy = {
        "trust": "bento",
        "creative": "clay",
    }
    v = legacy.get(v, v)
    if v not in {"bento", "clay"}:
        return "bento"
    return v


def load_settings(conn: sqlite3.Connection) -> Settings:
    imap_host = get_setting(conn, "imap_host") or ""
    imap_port = int(get_setting(conn, "imap_port") or "993")
    imap_user = get_setting(conn, "imap_user") or ""
    imap_folder = get_setting(conn, "imap_folder") or "INBOX"
    sender_filter = get_setting(conn, "sender_filter") or ""
    obsidian_root = get_setting(conn, "obsidian_root") or ""
    llm_backend = get_setting(conn, "llm_backend") or "local"
    cloud_provider = get_setting(conn, "cloud_provider") or "openai"
    cloud_multimodal_enabled = (
        get_setting(conn, "cloud_multimodal_enabled") or "0"
    ).strip().lower() in {"1", "true", "yes", "on"}
    openrouter_model = get_setting(conn, "openrouter_model") or "openai/gpt-4o-mini"
    from webmail_summary.llm.local_models import get_local_model, recommend_local_model

    local_model_id = (
        (get_setting(conn, "local_model_id") or recommend_local_model().id)
        .strip()
        .lower()
    )
    # Normalize to a known model id; unknown values fall back to default.
    local_model_id = get_local_model(local_model_id).id
    external_max_bytes = int(get_setting(conn, "external_max_bytes") or str(1024**3))
    revert_seen_after_sync = (
        get_setting(conn, "revert_seen_after_sync") or "0"
    ).strip() in {
        "1",
        "true",
        "yes",
        "on",
    }
    try:
        user_roles = json.loads(get_setting(conn, "user_roles") or "[]")
    except Exception:
        user_roles = []
    user_interests = get_setting(conn, "user_interests") or ""
    close_behavior = (
        (get_setting(conn, "close_behavior") or "background").strip().lower()
    )
    if close_behavior not in {"background", "exit"}:
        close_behavior = "background"
    update_channel = (get_setting(conn, "update_channel") or "stable").strip().lower()
    if update_channel not in {"stable", "beta"}:
        update_channel = "stable"
    update_latest_version = (get_setting(conn, "update_latest_version") or "").strip()
    update_auto_check_enabled = (
        get_setting(conn, "update_auto_check_enabled") or "1"
    ).strip().lower() in {"1", "true", "yes", "on"}
    update_repo = (get_setting(conn, "update_repo") or "").strip()
    update_snooze_until = (get_setting(conn, "update_snooze_until") or "").strip()
    update_skip_version = (get_setting(conn, "update_skip_version") or "").strip()
    update_last_checked_at = (get_setting(conn, "update_last_checked_at") or "").strip()
    update_download_url = (get_setting(conn, "update_download_url") or "").strip()
    update_last_check_status = (
        get_setting(conn, "update_last_check_status") or ""
    ).strip()
    local_engine = (get_setting(conn, "local_engine") or "auto").strip().lower()
    if local_engine not in {"auto", "llamacpp", "mlx"}:
        local_engine = "auto"
    new_models_v2_dismissed = (
        get_setting(conn, "new_models_v2_dismissed") or "0"
    ).strip().lower() in {"1", "true", "yes", "on"}

    return Settings(
        imap_host=imap_host,
        imap_port=imap_port,
        imap_user=imap_user,
        imap_folder=imap_folder,
        sender_filter=sender_filter,
        obsidian_root=obsidian_root,
        llm_backend=llm_backend,
        cloud_provider=cloud_provider,
        cloud_multimodal_enabled=cloud_multimodal_enabled,
        openrouter_model=openrouter_model,
        local_model_id=local_model_id,
        external_max_bytes=external_max_bytes,
        revert_seen_after_sync=revert_seen_after_sync,
        user_roles=user_roles,
        user_interests=user_interests,
        ui_theme=_normalize_ui_theme(get_setting(conn, "ui_theme")),
        close_behavior=close_behavior,
        update_channel=update_channel,
        update_latest_version=update_latest_version,
        update_auto_check_enabled=update_auto_check_enabled,
        update_repo=update_repo,
        update_snooze_until=update_snooze_until,
        update_skip_version=update_skip_version,
        update_last_checked_at=update_last_checked_at,
        update_download_url=update_download_url,
        update_last_check_status=update_last_check_status,
        local_engine=local_engine,
        new_models_v2_dismissed=new_models_v2_dismissed,
    )
