from __future__ import annotations


from webmail_summary.llm.base import LlmImageInput, LlmProvider, LlmResult
from webmail_summary.llm.long_summarize import summarize_email_long_aware


class _DummyProvider(LlmProvider):
    def __init__(self, summary: str, *, tier: str = "standard") -> None:
        self._summary = summary
        self._tier = tier

    @property
    def tier(self) -> str:
        return self._tier

    def summarize(
        self,
        *,
        subject: str,
        body: str,
        multimodal_inputs: list[LlmImageInput] | None = None,
    ) -> LlmResult:
        _ = (subject, body, multimodal_inputs)
        return LlmResult(summary=self._summary, tags=[], backlinks=[], personal=False)


class _SectionAwareProvider(LlmProvider):
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
        if "요약 초안 목록:" in body:
            return LlmResult(
                summary="\n".join(
                    [
                        "### 핵심 요약",
                        "- 2026년 3월 3일 첫번째 주 화요일 인사와 봄의 기대감으로 시작합니다.",
                        "### 상세 요약",
                        "- 무지를 벗어나는 가장 근본적인 방법은 알아차림이라고 설명합니다.",
                        "- 반응하기 전에 관찰하고 내가 모른다는 사실을 인정하는 태도를 강조합니다.",
                    ]
                ),
                tags=[],
                backlinks=[],
                personal=False,
            )
        if "무지를 벗어나는 가장 근본적인 방법" in body:
            return LlmResult(
                summary="\n".join(
                    [
                        "- 무지를 벗어나는 가장 근본적인 방법은 알아차림이라고 설명합니다.",
                        "- 반응하기 전에 관찰하고 내가 모른다는 사실을 인정하는 태도를 강조합니다.",
                    ]
                ),
                tags=[],
                backlinks=[],
                personal=False,
            )
        return LlmResult(
            summary="\n".join(
                [
                    "- 2026년 3월 3일 첫번째 주 화요일 인사와 봄의 기대감으로 시작합니다.",
                    "- 춘삼월에 대한 설렘과 기대를 전합니다.",
                ]
            ),
            tags=[],
            backlinks=[],
            personal=False,
        )


class _RecordingProvider(LlmProvider):
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def summarize(
        self,
        *,
        subject: str,
        body: str,
        multimodal_inputs: list[LlmImageInput] | None = None,
    ) -> LlmResult:
        self.calls.append(
            {
                "subject": subject,
                "body": body,
                "multimodal_count": len(multimodal_inputs or []),
            }
        )
        if "요약 초안 목록:" in body:
            return LlmResult(
                summary="### 핵심 요약\n- 앞부분과 뒷부분을 모두 반영합니다.\n\n### 상세 요약\n- 후반부 핵심 이미지를 함께 참고했습니다.",
                tags=[],
                backlinks=[],
                personal=False,
            )
        return LlmResult(summary="- 파트 요약", tags=[], backlinks=[], personal=False)


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


def test_summary_recovers_tail_topic_when_intro_only_bullets_returned():
    provider = _DummyProvider(
        "\n".join(
            [
                "### 핵심 요약",
                "- 이형세님과 김용관 대표이사가 2026년 봄의 기대감을 공유하며 시작",
                "- 2026년 3월 3일 첫번째 주 화요일입니다.",
                "### 상세 요약",
                "- 드디어 3월 춘삼월입니다.",
                "- 이런 춘삼월을 도대체 몇 번이나 지났는지 가물가물하지만 확실한 건 아직도 마음이 가슴이 이 3월만 되면 뜁니다.",
            ]
        ),
        tier="standard",
    )

    subject = "이번주 화두는 삶이 끝날 때 우리를 심판하는 기준은!"
    body = "\n".join(
        [
            "이형세님, 안녕하세요.",
            "아웃소싱타임스 대표이사 김용관입니다.",
            "2026년 3월 3일 첫번째 주 화요일입니다.",
            "드디어 3월 춘삼월입니다.",
            "이런 기대와 설렘으로 이 봄날의 첫번째 주를 시작합니다.",
            "이번주도 우분투와 화이팅으로 시작합니다.",
            "---------------------------------------------",
            "https://i.pinimg.com/736x/d0/93/ff/d093ff6f85ca534416a7391397291ced.jpg",
            "무지를 벗어나는 가장 근본적인 방법은 알아차림입니다.",
            "참회는 '잘못했습니다'가 아니라 '이제는 알겠습니다'에 더 가깝습니다.",
            "옛날 밀린다 왕이 나가세나 스님에게 알고 짓는 죄가 큽니까, 모르고 짓는 죄가 큽니까 하고 물었습니다.",
            "모르고 지은 죄가 더 큽니다. 왜 그런가를 묻자, 모르고 잡는 불덩이에 손을 더 많이 데게 된다고 답했습니다.",
            "상대편한테 주는 피해는 모르고 지은 죄가 피해가 더 큽니다.",
            "본인이 알면 조심하게 되고 죄를 지으면서도 눈치를 보는데, 모르면 눈치도 안 봅니다.",
            "우리가 겪는 모든 고통의 원인도 사실은 무지이며 알지 못하기 때문에 생기는 것입니다.",
            "고통에서 벗어나려면 누가 대신 용서해주는 것이 아니라 무지를 깨쳐야 됩니다.",
            "무지는 단순히 모른다는 뜻이 아니라 자신이 모른다는 사실조차 모르는 상태에 가깝습니다.",
            "그래서 벗어나는 방법도 감정이나 의식이 아니라 인식의 전환과 훈련입니다.",
            "내가 지금 분노 중이라는 사실, 욕심 때문에 움직인다는 사실, 두려움에 끌린다는 사실을 알아차리는 순간 절반은 벗어납니다.",
            "무지에서 벗어나는 길은 나를 더 많이 알고, 내가 모른다는 사실을 인정하고, 반응하기 전에 관찰하는 것입니다.",
            "이번주 화두는 삶이 끝날 때 우리를 심판하는 기준은!",
        ]
    )

    res = summarize_email_long_aware(provider, subject=subject, body=body)
    s = res.summary

    assert "무지를 벗어나는 가장 근본적인 방법" in s


def test_multi_section_medium_mail_uses_chunked_full_coverage():
    provider = _SectionAwareProvider()

    subject = "이번주 화두는 삶이 끝날 때 우리를 심판하는 기준은!"
    body = "\n\n".join(
        [
            "이형세님, 안녕하세요.\n아웃소싱타임스 대표이사 김용관입니다.\n2026년 3월 3일 첫번째 주 화요일입니다.",
            "드디어 3월 춘삼월입니다.\n이런 기대와 설렘으로 이 봄날의 첫번째 주를 시작합니다.\n이번주도 우분투와 화이팅으로 시작합니다.",
            "---------------------------------------------",
            "https://i.pinimg.com/736x/d0/93/ff/d093ff6f85ca534416a7391397291ced.jpg",
            "무지를 벗어나는 가장 근본적인 방법은 알아차림입니다.\n고통에서 벗어나려면 누가 대신 용서해주는 것이 아니라 무지를 깨쳐야 됩니다.",
            "내가 모른다는 사실을 인정하고, 반응하기 전에 관찰하는 것입니다.\n이번주 화두는 삶이 끝날 때 우리를 심판하는 기준은!",
        ]
    )

    res = summarize_email_long_aware(provider, subject=subject, body=body)
    s = res.summary

    assert "첫번째 주" in s or "춘삼월" in s or "기대와 설렘" in s
    assert "무지를 벗어나는 가장 근본적인 방법" in s
    assert "반응하기 전에 관찰" in s


def test_multimodal_inputs_only_used_for_single_pass_or_synthesis(tmp_path):
    provider = _RecordingProvider()
    img = tmp_path / "hero.jpg"
    img.write_bytes(b"fake-image-bytes")

    body = "\n\n".join(
        [
            "도입부 문장입니다.\n봄의 기대를 설명합니다.",
            "---------------------------------------------",
            "중간 본문을 길게 채웁니다. " * 40,
            "후반부에서는 무지에서 벗어나는 알아차림의 중요성을 설명합니다. " * 20,
        ]
    )

    summarize_email_long_aware(
        provider,
        subject="멀티모달 테스트",
        body=body,
        multimodal_inputs=[LlmImageInput(path=str(img), mime_type="image/jpeg")],
    )

    assert len(provider.calls) >= 2
    assert provider.calls[0]["multimodal_count"] == 0
    assert provider.calls[-1]["multimodal_count"] == 1


class _ArticleShallowProvider(LlmProvider):
    @property
    def tier(self) -> str:
        return "cloud"

    def summarize(
        self,
        *,
        subject: str,
        body: str,
        multimodal_inputs: list[LlmImageInput] | None = None,
    ) -> LlmResult:
        _ = (subject, multimodal_inputs)
        if "요약 초안 목록:" in body:
            return LlmResult(
                summary="\n".join(
                    [
                        "### 핵심 요약",
                        "- 하버드대는 논증적 글쓰기 수업을 필수로 운영한다.",
                        "### 상세 요약",
                        "- 스탠퍼드대도 작문 단계의 AI 활용을 엄격히 금지한다.",
                        "- 코넬대는 AI 작성 글을 표절로 판단할 수 있다.",
                    ]
                ),
                tags=[],
                backlinks=[],
                personal=False,
            )

        if "[Part 1/2]" in body:
            return LlmResult(
                summary="\n".join(
                    [
                        "- 하버드대는 모든 학생이 논증적 글쓰기 수업을 필수로 듣게 한다.",
                        "- 교수는 학생 글을 1대1로 첨삭하고 토론을 진행한다.",
                        "- 기초 글쓰기 과목을 통해 부족한 학생을 보완한다.",
                        "- 생성형 AI 글쓰기 과제는 A 학점을 받을 수 없다고 명시했다.",
                    ]
                ),
                tags=[],
                backlinks=[],
                personal=False,
            )

        return LlmResult(
            summary="\n".join(
                [
                    "- 스탠퍼드대는 기초·심화·전공 글쓰기 수업 체계를 운영한다.",
                    "- 스탠퍼드대는 글을 쓰거나 수정할 때 AI 활용을 엄격히 금지한다.",
                    "- 코넬대는 AI 작성 글을 표절로 보고 반성문이나 낙제를 줄 수 있다.",
                    "- 여러 미국 명문대가 교육 과정 전반에서 직접 글쓰기 훈련을 강화하고 있다.",
                ]
            ),
            tags=[],
            backlinks=[],
            personal=False,
        )


def test_article_like_summary_falls_back_to_chunk_coverage_when_synthesis_is_shallow():
    provider = _ArticleShallowProvider()
    body = "\n\n".join(
        [
            "Elite universities are strengthening human writing instruction without relying on AI tools in final composition work.",
            "Harvard requires argumentative writing courses for all students and uses one-on-one feedback plus live discussion to improve reasoning, evidence selection, and response to counterarguments in a structured classroom setting.",
            "The school also runs a placement-style writing check for freshmen and directs weaker students into foundational writing courses before they move into the required full writing curriculum.",
            "In the AI era guidance, Harvard still allows limited preparation-stage AI use for discovery or data analysis, but final writing quality and grades depend on what the student personally writes and can explain.",
            "Students are expected to document how they found ideas, how they summarized readings, and how peer feedback shaped the final draft instead of outsourcing the thinking process to a chatbot or automated writer.",
            "Stanford uses a three-stage writing sequence that covers foundational writing, advanced rhetoric, and later field-specific writing, which means writing practice is embedded across the broader educational path rather than treated as a single introductory course.",
            "Stanford also blocks AI use in actual drafting and revision, stating that students should not rely on AI even for individual sentences or word-level phrasing when producing formal writing assignments.",
            "Cornell treats AI-authored student writing as plagiarism in its first-year writing context and may require reflection papers or failing grades, reinforcing the view that writing remains central to thinking and academic integrity.",
        ]
    )

    res = summarize_email_long_aware(
        provider,
        subject="미 명문대는 AI 없이 직접 글쓰는 수업 강화",
        body=body,
    )
    bullets = [
        line for line in res.summary.splitlines() if line.strip().startswith("-")
    ]

    assert len(bullets) >= 8
    assert "하버드대" in res.summary
    assert "스탠퍼드대" in res.summary
    assert "코넬대" in res.summary


def test_article_like_detection_handles_soft_wrapped_lines_without_blank_paragraphs():
    body = "\n".join(
        [
            "Elite universities are strengthening human writing instruction without relying on AI tools in final composition work.",
            "Harvard requires argumentative writing courses for all students and uses one-on-one feedback plus live discussion to improve reasoning, evidence selection, and response to counterarguments in a structured classroom setting.",
            "The school also runs a placement-style writing check for freshmen and directs weaker students into foundational writing courses before they move into the required full writing curriculum.",
            "In the AI era guidance, Harvard still allows limited preparation-stage AI use for discovery or data analysis, but final writing quality and grades depend on what the student personally writes and can explain.",
            "Students are expected to document how they found ideas, how they summarized readings, and how peer feedback shaped the final draft instead of outsourcing the thinking process to a chatbot or automated writer.",
            "Stanford uses a three-stage writing sequence that covers foundational writing, advanced rhetoric, and later field-specific writing, which means writing practice is embedded across the broader educational path rather than treated as a single introductory course.",
            "Stanford also blocks AI use in actual drafting and revision, stating that students should not rely on AI even for individual sentences or word-level phrasing when producing formal writing assignments.",
            "Cornell treats AI-authored student writing as plagiarism in its first-year writing context and may require reflection papers or failing grades, reinforcing the view that writing remains central to thinking and academic integrity.",
        ]
    )

    from webmail_summary.llm.long_summarize import _is_article_like

    assert _is_article_like(
        subject="미 명문대는 AI 없이 직접 글쓰는 수업 강화",
        body=body,
    )
