"""Locks the multi-chunk path of summarize_email_long_aware.

The function is split into short, chunked, and post-process steps. These
assertions are the control-flow contract those steps have to keep.
"""

from __future__ import annotations

import re

from webmail_summary.llm.base import LlmImageInput, LlmProvider, LlmResult
from webmail_summary.llm.long_summarize import summarize_email_long_aware


class _ChunkProbe(LlmProvider):
    def __init__(self) -> None:
        self.bodies: list[str] = []

    @property
    def tier(self) -> str:
        return "standard"

    def summarize(
        self,
        *,
        subject: str,
        body: str,
        multimodal_inputs: list[LlmImageInput] | None = None,
    ) -> LlmResult:
        _ = (subject, multimodal_inputs)
        self.bodies.append(body)
        if "요약 초안 목록:" in body:
            return LlmResult(
                summary="\n".join(
                    [
                        "### 핵심 요약",
                        "- 합성된 핵심입니다.",
                        "",
                        "### 상세 요약",
                        "- 마지막 파트 토큰 LATEFACT 입니다.",
                    ]
                ),
                tags=["synth-tag"],
                backlinks=["synth-topic"],
                personal=True,
            )
        match = re.search(r"\[Part (\d+)/(\d+)\]", body)
        number = match.group(1) if match else "0"
        return LlmResult(
            summary=f"- 파트 {number} 사실입니다.",
            tags=[f"tag-{number}"],
            backlinks=[f"topic-{number}"],
            personal=False,
        )


def test_chunked_summary_reports_each_part_then_synthesizes_once():
    provider = _ChunkProbe()
    details: list[dict] = []
    progress: list[float] = []
    paragraph = "본문은 청크로 나뉘어야 하는 평범한 문단입니다. " * 30
    body = "\n\n".join([paragraph for _ in range(8)])

    result = summarize_email_long_aware(
        provider,
        subject="긴 메일",
        body=body,
        on_detail=details.append,
        on_progress=progress.append,
        user_profile={"roles": ["편집"], "interests": "요약"},
    )

    part_calls = [b for b in provider.bodies if b.startswith("[Part ")]
    synth_calls = [b for b in provider.bodies if "요약 초안 목록:" in b]
    assert len(part_calls) == 4
    assert len(synth_calls) == 1
    assert provider.bodies[-1] == synth_calls[0]
    assert "[User Profile]" in synth_calls[0]
    assert "편집" in synth_calls[0]

    chunk_events = [d for d in details if d.get("type") == "chunk"]
    assert [d["index"] for d in chunk_events] == list(range(1, len(part_calls) + 1))
    assert chunk_events[-1]["total"] == len(part_calls)
    assert {"type": "stage", "stage": "synthesis"} in details
    assert progress[-1] == 1.0
    assert result.summary.startswith("- [핵심 결론]:")
    assert "청크로 나뉘어야 하는 평범한 문단" in result.summary
    assert result.tags == ["tag-1", "tag-2", "tag-3", "tag-4", "synth-tag"]
    assert "synth-topic" in result.backlinks
    assert result.personal is True
