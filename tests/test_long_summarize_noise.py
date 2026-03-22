from __future__ import annotations


from webmail_summary.llm.base import LlmProvider, LlmResult
from webmail_summary.llm.long_summarize import summarize_email_long_aware


class _DummyProvider(LlmProvider):
    def __init__(self, summary: str, *, tier: str = "standard") -> None:
        self._summary = summary
        self._tier = tier

    @property
    def tier(self) -> str:
        return self._tier

    def summarize(self, *, subject: str, body: str) -> LlmResult:
        return LlmResult(summary=self._summary, tags=[], backlinks=[], personal=False)


def test_summary_filters_noise_bullets_and_avoids_placeholder():
    provider = _DummyProvider(
        "\n".join(
            [
                "- 김재현",
                "- 2026-03-02(Mon) 16:42 (+09:00 Asia/Seoul)",
                '- "바로가기"를 클릭하여 해당 결재 문서를 확인하세요.',
            ]
        ),
        tier="standard",
    )

    subject = "[공지] 맞춤형교실 운영 용역 입찰"
    body = "\n".join(
        [
            "김재현 대외협력팀장이 2026 맞춤형교실 운영 용역 입찰을 제안했습니다.",
            "핵심은 예산/일정/요구사항을 정리해 제출하는 것입니다.",
            "2026-03-02(Mon) 16:42 (+09:00 Asia/Seoul)",
            '"바로가기"를 클릭하여 해당 결재 문서를 확인하세요.',
        ]
    )

    res = summarize_email_long_aware(provider, subject=subject, body=body)
    s = res.summary

    assert "Asia/Seoul" not in s
    assert "바로가기" not in s
    assert "\n- 김재현\n" not in s
    assert "상세 요약 항목이 부족합니다" not in s


def test_summary_drops_name_only_bullet_and_keeps_contextual_name():
    provider = _DummyProvider("- 홍길동", tier="standard")

    subject = "[안내] 회의 일정"
    body = "\n".join(
        [
            "홍길동: 3/30(월) 10:00에 회의 진행 예정입니다.",
            "안건은 일정 확정 및 담당자 지정입니다.",
        ]
    )

    res = summarize_email_long_aware(provider, subject=subject, body=body)
    s = res.summary

    assert "\n- 홍길동\n" not in s
    # Name with context is allowed
    assert "홍길동" in s
