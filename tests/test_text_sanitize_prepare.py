from __future__ import annotations

from webmail_summary.util.text_sanitize import prepare_body_for_llm


def test_prepare_body_keeps_forwarded_content_after_header_block():
    body = "\n".join(
        [
            "From: sender@example.com",
            "Sent: Monday, March 2, 2026 8:08 AM",
            "To: user@example.com",
            "Subject: FW: 뉴스레터",
            "",
            "안녕하세요, 구독자 여러분!",
            "이번 호에서는 교사 AI 리터러시 투자 소식을 다룹니다.",
        ]
    )

    out = prepare_body_for_llm(body)

    assert "안녕하세요, 구독자 여러분!" in out
    assert "교사 AI 리터러시" in out


def test_prepare_body_splits_quoted_history_after_main_content():
    body = "\n".join(
        [
            "이번 주 요약입니다.",
            "핵심 변경 사항은 세 가지입니다.",
            "",
            "On Mon, Mar 2, 2026 at 10:00 AM foo@example.com wrote:",
            "이 아래는 과거 인용 본문입니다.",
        ]
    )

    out = prepare_body_for_llm(body)

    assert "이번 주 요약입니다." in out
    assert "핵심 변경 사항은 세 가지입니다." in out
    assert "과거 인용 본문" not in out


def test_prepare_body_does_not_return_empty_for_forwarded_like_input():
    body = "\n".join(
        [
            "From: newsletter@example.com",
            "Sent: Sunday, March 1, 2026 11:04 PM",
            "To: user@example.com",
            "Subject: FW: 다락편지",
            "",
            "다락편지 1383호",
            "마케팅을 이해하면 세상이 보인다!",
            "이주의 싱싱신간",
        ]
    )

    out = prepare_body_for_llm(body)

    assert out.strip() != ""
    assert "다락편지 1383호" in out
