from webmail_summary.jobs.tasks_resummarize import _needs_resummarize
from webmail_summary.llm.summary_quality import (
    PRODUCED_FAILURE_SUMMARIES,
    is_failed_summary,
)


def test_needs_resummarize_when_empty():
    assert _needs_resummarize("") is True


def test_needs_resummarize_when_llm_timeout():
    assert _needs_resummarize("(LLM timeout)") is True
    assert _needs_resummarize("LLM TIMEOUT") is True


def test_needs_resummarize_when_no_summary_or_placeholder():
    assert _needs_resummarize("(no summary)") is True
    assert _needs_resummarize("### 핵심 요약\n- (no summary)") is True
    assert _needs_resummarize("### 상세 요약\n- (상세 요약 항목이 부족합니다.)") is True


def test_needs_resummarize_when_ok_summary():
    assert _needs_resummarize("- 일정 확정\n- 요청 사항") is False
    assert is_failed_summary("- 일정 확정\n- 요청 사항") is False


def test_korean_and_english_fallbacks_need_resummarize():
    # Cloud concurrent sync stores Korean text. The old English-only check
    # left "(LLM 응답 timeout)" off the retry list because it does not
    # contain the contiguous substring "llm timeout".
    for text in PRODUCED_FAILURE_SUMMARIES:
        assert is_failed_summary(text) is True
        assert _needs_resummarize(text) is True
    assert is_failed_summary("(LLM error: HTTP 400)") is True
    assert is_failed_summary("?\ubdbf\ube5f?\ub181\uc4ec") is True
