from webmail_summary.jobs.tasks_resummarize import _needs_resummarize


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
