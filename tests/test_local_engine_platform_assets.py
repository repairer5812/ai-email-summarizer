from __future__ import annotations

import webmail_summary.llm.local_engine as mod


def test_pick_release_assets_for_macos_arm64(monkeypatch):
    monkeypatch.setattr(mod.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(mod, "_normalized_arch", lambda: "arm64")

    assets = [
        {"name": "llama-b4052-bin-macos-arm64.zip"},
        {"name": "llama-b4052-bin-win-cpu-x64.zip"},
        {"name": "llama-b4052-bin-linux-x64.zip"},
    ]

    picked = mod._pick_release_assets(assets)

    assert picked
    assert picked[0]["name"] == "llama-b4052-bin-macos-arm64.zip"


def test_pick_release_assets_for_linux_x64(monkeypatch):
    monkeypatch.setattr(mod.platform, "system", lambda: "Linux")
    monkeypatch.setattr(mod, "_normalized_arch", lambda: "x64")

    assets = [
        {"name": "llama-b4052-bin-macos-arm64.zip"},
        {"name": "llama-b4052-bin-linux-x64.zip"},
        {"name": "cudart-llama-bin-linux-x64.zip"},
    ]

    picked = mod._pick_release_assets(assets)

    assert picked
    assert picked[0]["name"] == "llama-b4052-bin-linux-x64.zip"
