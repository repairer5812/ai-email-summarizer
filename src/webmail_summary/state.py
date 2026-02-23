from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass
class AppState:
    # Per folder, per sender: last processed UID (best-effort)
    last_uid_by_key: dict[str, int] = field(default_factory=dict)


def _key(folder: str, sender: str) -> str:
    return f"{folder}::{sender}".lower()


def get_last_uid(state: AppState, folder: str, sender: str) -> int | None:
    return state.last_uid_by_key.get(_key(folder, sender))


def set_last_uid(state: AppState, folder: str, sender: str, uid: int) -> None:
    state.last_uid_by_key[_key(folder, sender)] = int(uid)


def load_state(path: Path) -> AppState:
    if not path.exists():
        return AppState()
    raw = json.loads(path.read_text(encoding="utf-8"))
    return AppState(
        last_uid_by_key={
            k: int(v) for k, v in (raw.get("last_uid_by_key") or {}).items()
        }
    )


def save_state(path: Path, state: AppState) -> None:
    path.write_text(
        json.dumps(asdict(state), ensure_ascii=True, indent=2), encoding="utf-8"
    )
