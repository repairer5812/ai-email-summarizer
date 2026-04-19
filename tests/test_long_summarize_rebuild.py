from __future__ import annotations

from webmail_summary.llm.base import LlmImageInput, LlmProvider, LlmResult
from webmail_summary.llm.long_summarize import summarize_email_long_aware


class _StructuredPlaceholderProvider(LlmProvider):
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
        if "요약 초안 목록:" in body:
            return LlmResult(
                summary="\n".join(
                    [
                        "### 핵심 요약",
                        "- 당근은 단순 중고거래 플랫폼을 넘어 확장 중입니다.",
                        "",
                        "### 상세 요약",
                        "- (상세 요약 항목이 부족합니다.)",
                    ]
                ),
                tags=[],
                backlinks=[],
                personal=False,
            )

        return LlmResult(
            summary="- 당근은 중고거래를 넘어 지역 기반 서비스로 확장하고 있습니다.",
            tags=[],
            backlinks=[],
            personal=False,
        )


class _StructuredNoSummaryProvider(LlmProvider):
    @property
    def tier(self) -> str:
        return "performance"

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
                        "- (no summary)",
                        "",
                        "### 상세 요약",
                        "- 큐텐은 이커머스 확장을 위해 물류와 결제를 함께 묶어 운영하고 있습니다.",
                    ]
                ),
                tags=[],
                backlinks=[],
                personal=False,
            )

        return LlmResult(
            summary="\n".join(
                [
                    "- 큐텐은 물류와 결제를 결합한 커머스 인프라를 키우고 있습니다.",
                    "- 동남아 셀러와 소비자를 잇는 해외 거래망을 확장하고 있습니다.",
                ]
            ),
            tags=[],
            backlinks=[],
            personal=False,
        )


def test_structured_placeholder_summary_is_rebuilt_from_validated_bullets():
    provider = _StructuredPlaceholderProvider()
    body = "\n\n".join(
        [
            "당근은 중고거래 앱을 넘어 지역 커뮤니티, 동네생활, 광고, 구인구직 서비스를 함께 키우고 있습니다.",
            "회사는 사용자 체류 시간을 늘리기 위해 동네 상점 광고와 로컬 비즈니스 도구를 강화하고 있습니다.",
            "특히 부동산, 중고차, 알바 같은 생활 밀착형 카테고리를 통해 거래 외 수익원을 넓히고 있습니다.",
            "동네 인증 기반 신뢰 구조를 바탕으로 하이퍼로컬 플랫폼 정체성을 유지하려고 합니다.",
            "콘텐츠와 커뮤니티 기능을 늘려 거래가 없는 날에도 앱을 열게 만드는 전략을 추진하고 있습니다.",
            "이 과정에서 광고 상품 고도화와 로컬 사업자 대상 SaaS형 도구 실험도 병행하고 있습니다.",
            "핵심 과제는 중고거래 중심 브랜드를 유지하면서도 다양한 지역 서비스로 자연스럽게 확장하는 것입니다.",
            "경쟁이 치열해지는 가운데 당근은 사용자 접점을 더 자주 만들고 생활 전반을 아우르는 앱이 되려 합니다.",
        ]
    )

    res = summarize_email_long_aware(
        provider,
        subject="중고거래 플랫폼을 넘어 당근의 진화는 계속된다",
        body=body,
    )
    bullets = [
        line for line in res.summary.splitlines() if line.strip().startswith("-")
    ]

    assert "상세 요약 항목이 부족합니다" not in res.summary
    assert len(bullets) >= 4
    assert "구인구직" in res.summary or "광고" in res.summary or "로컬" in res.summary


def test_structured_no_summary_marker_is_dropped_from_rebuilt_summary():
    provider = _StructuredNoSummaryProvider()
    body = "\n\n".join(
        [
            "큐텐은 동남아와 일본을 잇는 전자상거래 플랫폼 확장에 집중하고 있습니다.",
            "최근에는 물류 자회사와 결제 서비스를 묶어 판매자에게 통합 운영 환경을 제공하려고 합니다.",
            "회사는 해외 셀러 유치와 풀필먼트 역량 강화를 통해 거래 규모를 키우는 전략을 추진 중입니다.",
            "핵심 과제는 국가별 규제와 배송 품질을 안정적으로 관리하면서도 성장 속도를 유지하는 것입니다.",
            "시장에서는 물류비 부담과 운영 복잡도가 동시에 커지는 점을 주요 리스크로 보고 있습니다.",
        ]
    )

    res = summarize_email_long_aware(
        provider,
        subject="큐텐은 물류와 결제를 묶어 해외 커머스 확장 속도를 높이고 있다",
        body=body,
    )

    assert "(no summary)" not in res.summary
    assert "물류" in res.summary or "결제" in res.summary or "해외" in res.summary
