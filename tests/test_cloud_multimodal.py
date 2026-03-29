from __future__ import annotations

from dataclasses import dataclass

from webmail_summary.llm.base import LlmImageInput
from webmail_summary.llm.openrouter import CloudConfig, CloudProvider


@dataclass
class _Resp:
    status_code: int
    payload: dict
    text: str = ""
    headers: dict | None = None

    def json(self) -> dict:
        return self.payload


def test_cloud_provider_uses_text_only_payload_without_images(monkeypatch):
    captured = {}

    def _fake_post(url, headers=None, json=None, timeout=0):
        _ = (url, headers, timeout)
        captured["payload"] = json
        return _Resp(
            status_code=200,
            payload={
                "choices": [
                    {
                        "message": {
                            "content": '{"summary": ["요약"], "tags": [], "backlinks": [], "personal": false}'
                        }
                    }
                ]
            },
            headers={},
        )

    import webmail_summary.llm.openrouter as mod

    monkeypatch.setattr(mod.requests, "post", _fake_post)
    provider = CloudProvider(
        CloudConfig(
            api_key="sk-test",
            model="openai/gpt-4o-mini",
            base_url="https://openrouter.ai/api/v1",
        )
    )
    provider.summarize(subject="제목", body="본문")

    user_content = captured["payload"]["messages"][1]["content"]
    assert isinstance(user_content, str)


def test_cloud_provider_uses_image_parts_when_multimodal_supported(
    tmp_path, monkeypatch
):
    captured = {}
    img = tmp_path / "mail.png"
    img.write_bytes(b"fake-png-bytes")

    def _fake_post(url, headers=None, json=None, timeout=0):
        _ = (url, headers, timeout)
        captured["payload"] = json
        return _Resp(
            status_code=200,
            payload={
                "choices": [
                    {
                        "message": {
                            "content": '{"summary": ["요약"], "tags": [], "backlinks": [], "personal": false}'
                        }
                    }
                ]
            },
            headers={},
        )

    import webmail_summary.llm.openrouter as mod

    monkeypatch.setattr(mod.requests, "post", _fake_post)
    provider = CloudProvider(
        CloudConfig(
            api_key="sk-test",
            model="openai/gpt-4.1-mini",
            base_url="https://openrouter.ai/api/v1",
        )
    )
    provider.summarize(
        subject="제목",
        body="본문",
        multimodal_inputs=[LlmImageInput(path=str(img), mime_type="image/png")],
    )

    user_content = captured["payload"]["messages"][1]["content"]
    assert isinstance(user_content, list)
    assert user_content[0]["type"] == "text"
    assert user_content[1]["type"] == "image_url"
    assert user_content[1]["image_url"]["url"].startswith("data:image/png;base64,")
