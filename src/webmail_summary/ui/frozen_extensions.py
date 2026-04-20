from __future__ import annotations

import importlib
import importlib.machinery
import importlib.util
import os
from pathlib import Path
import shutil
import sys
import tempfile
from types import ModuleType

_DLL_DIR_HANDLES: list[object] = []
_PREPARED_DIRS: set[str] = set()


def _candidate_roots(base: Path) -> list[Path]:
    roots = [base]
    internal = base / "_internal"
    if internal.is_dir():
        roots.append(internal)
    return roots


def extension_search_roots() -> list[Path]:
    roots: list[Path] = []
    seen: set[str] = set()

    def _add_dir(path_text: str | Path | None) -> None:
        if path_text is None:
            return
        text = str(path_text).strip()
        if not text:
            return
        base = Path(text)
        if base.is_file():
            base = base.parent
        for candidate in _candidate_roots(base):
            key = str(candidate).lower()
            if key in seen or not candidate.is_dir():
                continue
            seen.add(key)
            roots.append(candidate)

    _add_dir(getattr(sys, "_MEIPASS", "") or "")
    _add_dir(os.environ.get("_PYI_APPLICATION_HOME_DIR", ""))
    _add_dir(os.environ.get("_MEIPASS2", ""))

    executable = str(getattr(sys, "executable", "") or "").strip()
    if executable:
        _add_dir(Path(executable).parent)

    try:
        temp_root = Path(tempfile.gettempdir())
        mei_dirs = sorted(
            [d for d in temp_root.glob("_MEI*") if d.is_dir()],
            key=lambda d: d.stat().st_mtime,
            reverse=True,
        )
        for directory in mei_dirs[:12]:
            _add_dir(directory)
    except Exception:
        pass

    return roots


def prepare_extension_dir(path: Path) -> None:
    if not path.is_dir():
        return
    base_text = str(path)
    key = base_text.lower()
    if base_text not in sys.path:
        sys.path.insert(0, base_text)
    if key in _PREPARED_DIRS:
        return
    _PREPARED_DIRS.add(key)
    add_dir = getattr(os, "add_dll_directory", None)
    if callable(add_dir):
        try:
            handle = add_dir(base_text)
        except Exception:
            handle = None
        if handle is not None:
            _DLL_DIR_HANDLES.append(handle)


def find_frozen_extension(module_name: str) -> Path | None:
    candidates_seen: set[str] = set()
    for base in extension_search_roots():
        prepare_extension_dir(base)

        plain = base / f"{module_name}.pyd"
        if plain.is_file():
            return plain

        for suffix in importlib.machinery.EXTENSION_SUFFIXES:
            candidate = base / f"{module_name}{suffix}"
            key = str(candidate).lower()
            if key in candidates_seen or not candidate.is_file():
                continue
            candidates_seen.add(key)
            return candidate

        for candidate in base.glob(f"{module_name}*.pyd"):
            key = str(candidate).lower()
            if key in candidates_seen or not candidate.is_file():
                continue
            candidates_seen.add(key)
            return candidate

        try:
            nested_candidates = base.rglob(f"{module_name}*.pyd")
        except Exception:
            nested_candidates = ()
        for candidate in nested_candidates:
            key = str(candidate).lower()
            if key in candidates_seen or not candidate.is_file():
                continue
            candidates_seen.add(key)
            prepare_extension_dir(candidate.parent)
            return candidate
    return None


def ensure_frozen_extension_alias(module_name: str) -> Path | None:
    found = find_frozen_extension(module_name)
    if found is None:
        return None
    plain = found.parent / f"{module_name}.pyd"
    if plain.is_file():
        return plain
    if found.name.lower() == plain.name.lower():
        return found
    try:
        shutil.copyfile(found, plain)
        return plain
    except Exception:
        return found


def preload_extension_module(module_name: str) -> ModuleType:
    try:
        module = importlib.import_module(module_name)
        return module
    except (ModuleNotFoundError, ImportError, OSError) as first_error:
        alias = ensure_frozen_extension_alias(module_name)
        if alias is None:
            raise first_error

        prepare_extension_dir(alias.parent)
        importlib.invalidate_caches()

        try:
            module = importlib.import_module(module_name)
            return module
        except (ModuleNotFoundError, ImportError, OSError):
            pass

        spec = importlib.util.spec_from_file_location(module_name, str(alias))
        if spec is None or spec.loader is None:
            raise first_error
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
            return module
        except Exception:
            sys.modules.pop(module_name, None)
            raise


def preload_cffi_backend() -> ModuleType:
    return preload_extension_module("_cffi_backend")


__all__ = [
    "ensure_frozen_extension_alias",
    "extension_search_roots",
    "find_frozen_extension",
    "preload_cffi_backend",
    "preload_extension_module",
    "prepare_extension_dir",
]
