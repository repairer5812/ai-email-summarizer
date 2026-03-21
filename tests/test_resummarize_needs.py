from webmail_summary.jobs.tasks_resummarize import _needs_resummarize


def test_needs_resummarize_when_empty():
    assert _needs_resummarize("") is True


def test_needs_resummarize_when_llm_timeout():
    assert _needs_resummarize("(LLM timeout)") is True
    assert _needs_resummarize("LLM TIMEOUT") is True


def test_needs_resummarize_when_ok_summary():
    assert _needs_resummarize("- 일정 확정\n- 요청 사항") is False
