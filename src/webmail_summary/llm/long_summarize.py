from __future__ import annotations

from dataclasses import dataclass

from collections.abc import Callable

from webmail_summary.llm.base import LlmProvider, LlmResult
import re


@dataclass(frozen=True)
class LongSummarizeConfig:
    # If body is longer than this, chunking is used.
    chunk_if_body_chars_over: int = 4500
    # Target chunk size in chars (approx; respects paragraph boundaries when possible).
    chunk_chars: int = 2400
    # If set, cap the number of chunks (None = summarize all chunks).
    max_chunks: int | None = None
    # Cap merged bullets/tags/backlinks to keep output compact.
    max_bullets: int = 15
    # Per-part bullets to record in the detailed section.
    part_bullets: int = 5
    max_tags: int = 10
    max_backlinks: int = 10


def _split_paragraphs(text: str) -> list[str]:
    s = (text or "").strip()
    if not s:
        return []
    # Normalize newlines, then split on blank lines.
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    paras: list[str] = []
    cur: list[str] = []
    for line in s.split("\n"):
        if not line.strip():
            if cur:
                paras.append("\n".join(cur).strip())
                cur = []
            continue
        cur.append(line)
    if cur:
        paras.append("\n".join(cur).strip())
    return [p for p in paras if p]


def _chunk_text(text: str, *, chunk_chars: int, max_chunks: int | None) -> list[str]:
    s = (text or "").strip()
    if not s:
        return []

    paras = _split_paragraphs(s)
    if not paras:
        return [s[:chunk_chars]]

    chunks: list[str] = []
    cur: list[str] = []
    cur_len = 0
    for p in paras:
        plen = len(p)
        # If a single paragraph is enormous, split it hard.
        if plen > chunk_chars * 2:
            if cur:
                chunks.append("\n\n".join(cur).strip())
                cur = []
                cur_len = 0
                if max_chunks is not None and len(chunks) >= max_chunks:
                    break
            for i in range(0, plen, chunk_chars):
                chunks.append(p[i : i + chunk_chars].strip())
                if max_chunks is not None and len(chunks) >= max_chunks:
                    break
            if max_chunks is not None and len(chunks) >= max_chunks:
                break
            continue

        if cur_len + plen + (2 if cur else 0) > chunk_chars and cur:
            chunks.append("\n\n".join(cur).strip())
            cur = []
            cur_len = 0
            if max_chunks is not None and len(chunks) >= max_chunks:
                break

        cur.append(p)
        cur_len += plen + (2 if cur_len else 0)

    if cur and (max_chunks is None or len(chunks) < max_chunks):
        chunks.append("\n\n".join(cur).strip())
    return [c for c in chunks if c]


def _extract_bullets(summary: str) -> list[str]:
    s = (summary or "").strip()
    if not s:
        return []

    # Handle leaked JSON list output.
    if s.startswith("[") and s.endswith("]"):
        try:
            import json

            obj = json.loads(s)
            if isinstance(obj, list):
                return [str(x).strip() for x in obj if str(x).strip()]
        except Exception:
            pass

    # Remove bold markdown markers to avoid downstream UI artifacts.
    s = s.replace("**", "")

    # Normalize bullets and split clumped inline bullets.
    s = s.replace("·", "-").replace("•", "-")
    s = re.sub(r"\s+-\s+(?=[A-Za-z가-힣0-9\[])", "\n- ", s)

    out: list[str] = []
    for raw_line in s.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        # Keep section headers, remove markdown symbols around them.
        if line.startswith("###"):
            header = re.sub(r"^#{1,6}\s*", "", line).strip()
            if header:
                out.append(header)
            continue

        clean_line = re.sub(r"^([\s\-\*#]+)", "", line).strip()
        clean_line = re.sub(r"[\"'\],]+$", "", clean_line).strip()
        if clean_line and len(clean_line) > 1:
            out.append(clean_line)

    if out:
        return out

    if "; " in s:
        return [x.strip() for x in s.split("; ") if x.strip()]
    return []


def _dedupe_keep_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for x in items:
        k = (x or "").strip()
        if not k:
            continue
        lk = k.lower()
        if lk in seen:
            continue
        seen.add(lk)
        out.append(k)
    return out


def _is_structured(text: str) -> bool:
    """Check if the text already contains structured formatting like headers or bold topics."""
    s = text.strip()
    return "###" in s or (s.count("\n\n") >= 2)


def _normalize_summary_section_labels(text: str) -> str:
    s = str(text or "").strip()
    if not s:
        return s

    lines: list[str] = []
    for raw_line in s.splitlines():
        line = raw_line.strip()
        if not line:
            lines.append(raw_line)
            continue

        clean = re.sub(r"^#{1,6}\s*", "", line).strip()
        clean = clean.strip("[]").strip()
        normalized = clean.lower().replace(" ", "")

        if normalized in {
            "핵심전략결론",
            "핵심결론",
            "핵심요약",
            "bluf",
        }:
            lines.append("### 핵심 요약")
            continue

        if normalized in {
            "주요소식",
            "주제별분석",
            "심층구조화",
            "구조화",
            "상세요약",
        }:
            lines.append("### 상세 요약")
            continue

        lines.append(raw_line)

    return "\n".join(lines).strip()


def _ensure_core_detail_sections(text: str) -> str:
    s = _normalize_summary_section_labels(text)
    if not s:
        return s

    normalized = s.lower().replace(" ", "")
    has_core = "핵심요약" in normalized
    has_detail = "상세요약" in normalized
    if has_core and has_detail:
        return s

    skip_headers = {
        "핵심요약",
        "상세요약",
        "핵심결론",
        "핵심전략결론",
        "주요소식",
        "주제별분석",
        "심층구조화",
        "구조화",
    }

    bullets = _extract_bullets(s)
    cleaned: list[str] = []
    for b in bullets:
        t = str(b or "").strip()
        if not t:
            continue
        n = t.lower().replace(" ", "").strip("[]").strip()
        if n in skip_headers:
            continue
        cleaned.append(t)

    if not cleaned:
        for raw in s.splitlines():
            t = re.sub(r"^#{1,6}\s*", "", raw).strip()
            t = re.sub(r"^[-*•·]\s*", "", t).strip()
            if not t:
                continue
            n = t.lower().replace(" ", "").strip("[]").strip()
            if n in skip_headers:
                continue
            cleaned.append(t)

    cleaned = _dedupe_keep_order(cleaned)
    if not cleaned:
        return "### 핵심 요약\n- (요약 없음)\n\n### 상세 요약\n- (요약 없음)"

    core = cleaned[:3]
    detail = cleaned[3:10]
    if not detail:
        detail = cleaned[: min(7, len(cleaned))]

    core_text = "\n".join([f"- {x}" for x in core])
    detail_text = "\n".join([f"- {x}" for x in detail])
    return f"### 핵심 요약\n{core_text}\n\n### 상세 요약\n{detail_text}".strip()


def summarize_email_long_aware(
    provider: LlmProvider,
    *,
    subject: str,
    body: str,
    cfg: LongSummarizeConfig = LongSummarizeConfig(),
    on_detail: Callable[[dict], None] | None = None,
    on_progress: Callable[[float], None] | None = None,
    user_profile: dict | None = None,
) -> LlmResult:
    body_s = str(body or "")

    # Tier-aware dynamic configuration for performance.
    tier = getattr(provider, "tier", "standard")
    active_cfg = cfg
    if tier == "cloud" and cfg.chunk_chars <= 2400:
        # Cloud models can process larger contexts efficiently.
        active_cfg = LongSummarizeConfig(
            chunk_if_body_chars_over=12000,
            chunk_chars=10000,
            max_chunks=cfg.max_chunks,
            max_bullets=cfg.max_bullets,
            part_bullets=cfg.part_bullets,
            max_tags=cfg.max_tags,
            max_backlinks=cfg.max_backlinks,
        )
    elif tier == "standard" and cfg.chunk_chars <= 2400:
        # Local standard models usually handle medium context windows.
        active_cfg = LongSummarizeConfig(
            chunk_if_body_chars_over=6000,
            chunk_chars=5000,
            max_chunks=cfg.max_chunks,
            max_bullets=cfg.max_bullets,
            part_bullets=cfg.part_bullets,
            max_tags=cfg.max_tags,
            max_backlinks=cfg.max_backlinks,
        )

    if len(body_s) <= active_cfg.chunk_if_body_chars_over:
        res = provider.summarize(subject=subject, body=body_s)
        return LlmResult(
            summary=_ensure_core_detail_sections(res.summary),
            tags=list(res.tags or []),
            backlinks=list(res.backlinks or []),
            personal=bool(res.personal),
        )

    chunks = _chunk_text(
        body_s,
        chunk_chars=active_cfg.chunk_chars,
        max_chunks=active_cfg.max_chunks,
    )
    if not chunks:
        res = provider.summarize(subject=subject, body=body_s[: active_cfg.chunk_chars])
        return LlmResult(
            summary=_ensure_core_detail_sections(res.summary),
            tags=list(res.tags or []),
            backlinks=list(res.backlinks or []),
            personal=bool(res.personal),
        )

    detailed_parts: list[str] = []
    all_bullets: list[str] = []
    tags: list[str] = []
    backlinks: list[str] = []
    personal = False

    # Total units: chunks + synthesis
    total_units = len(chunks) + 1

    # Format user profile for prompt
    profile_info = ""
    if user_profile:
        roles = ", ".join(user_profile.get("roles", []))
        interests = user_profile.get("interests", "")
        profile_info = f"\n[User Profile]\n- Role: {roles}\n- Interests: {interests}\n"

    for i, ch in enumerate(chunks, start=1):
        if on_detail is not None:
            try:
                on_detail({"type": "chunk", "index": i, "total": len(chunks)})
            except Exception:
                pass

        part_body = f"[Part {i}/{len(chunks)}]\n{ch}"
        res = provider.summarize(subject=subject, body=part_body)
        part_bullets = _extract_bullets(res.summary)
        all_bullets.extend(part_bullets)
        tags.extend(list(res.tags or []))
        backlinks.extend(list(res.backlinks or []))
        personal = personal or bool(res.personal)

        short = _dedupe_keep_order(part_bullets)[: max(1, int(active_cfg.part_bullets))]
        if short:
            lines = "\n".join(["- " + x for x in short if x]).strip()
            if lines:
                detailed_parts.append(lines)

        if on_progress:
            try:
                on_progress(i / total_units)
            except Exception:
                pass

    # Synthesize a compact, structured report from the part summaries.
    final_summary_text = ""
    try:
        if on_detail:
            on_detail({"type": "stage", "stage": "synthesis"})

        synth_body = "\n\n---\n\n".join(detailed_parts)

        # Branch prompts based on provider tier
        tier = getattr(provider, "tier", "standard")

        custom_tailor = ""
        if profile_info:
            custom_tailor = f"\n중요: 아래 사용자 프로필에 맞춰 사용자가 특히 관심있어 할 내용을 강조하여 요약하세요.{profile_info}"

        if tier == "fast":
            # Lite version for small models (like Gemma 2 2B)
            system_role = "뉴스레터를 요약하는 어시스턴트"
            guidelines = (
                "1. 형식 고정: 반드시 '### 핵심 요약' 섹션과 '### 상세 요약' 섹션 2개로 작성하세요.\n"
                "2. 핵심 요약: 가장 중요한 내용 3~5개를 불릿 포인트로 작성하세요.\n"
                "3. 상세 요약: 본문 사실에 충실하게 최대 7개 불릿으로 작성하세요(7개 미만 가능).\n"
                "4. 노이즈 제거: 주소, 저작권, 구독 취소 안내 등은 무시하세요.\n"
                "5. 반드시 한국어로만 작성하고 문장을 마침표로 끝내세요."
            )
        elif tier == "cloud":
            # Executive version for high-capability models (Gemini, OpenAI etc)
            system_role = "전문적인 전략 분석가 및 수석 에디터"
            guidelines = (
                "1. 형식 고정: 반드시 '### 핵심 요약'과 '### 상세 요약' 머리말을 사용하세요.\n"
                "2. 핵심 요약: 최상단에 전체를 관통하는 핵심 결론 3~5개를 불릿으로 작성하세요.\n"
                "3. 상세 요약: 본문 사실에 근거해 주제별 핵심 사실을 최대 7개 불릿으로 정리하세요(7개 미만 가능).\n"
                "4. 데이터 밀도: 수치, 인물, 결정 사항을 포함하되 과장/추측은 금지하세요.\n"
                "5. 노이즈 제거: 주소, 저작권, 구독 취소 안내 등은 포함하지 마세요.\n"
                "6. 반드시 한국어로만 격식 있는 문체로 작성하세요."
            )
        else:
            # Standard version (EXAONE, Qwen 3B etc)
            system_role = "뉴스레터를 요약하는 전문 에디터"
            guidelines = (
                "1. 형식 고정: 반드시 '### 핵심 요약'과 '### 상세 요약' 머리말을 사용하세요.\n"
                "2. 핵심 요약: 가장 중요한 내용 3~5개를 불릿으로 작성하세요.\n"
                "3. 상세 요약: 본문 사실에 충실하게 최대 7개 불릿으로 작성하세요(7개 미만 가능).\n"
                "4. 노이즈 제거: 주소, 저작권, 구독 취소 안내 등은 포함하지 마세요.\n"
                "5. 반드시 한국어로 작성하고 모든 문장은 마침표(.)로 끝맺으세요."
            )

        synth = provider.summarize(
            subject=subject,
            body=(
                f"[System Role: {system_role}]\n"
                "아래 초안들을 바탕으로 최종 리포트를 작성하세요.\n\n"
                f"작성 지침:\n{guidelines}{custom_tailor}\n\n"
                "요약 초안 목록:\n" + synth_body
            ),
        )

        # Preserve original formatting (headers/bold) if it looks structured
        raw_synth = _ensure_core_detail_sections(synth.summary.strip())
        if _is_structured(raw_synth):
            final_summary_text = raw_synth
        else:
            merged_bullets = _extract_bullets(raw_synth)
            final_summary_text = "\n".join(["- " + b for b in merged_bullets if b])

        tags.extend(list(synth.tags or []))
        backlinks.extend(list(synth.backlinks or []))
        personal = personal or bool(synth.personal)
    except Exception:
        final_summary_text = ""

    if on_progress:
        try:
            on_progress(1.0)
        except Exception:
            pass

    if not final_summary_text:
        merged_bullets = _dedupe_keep_order(all_bullets)[: active_cfg.max_bullets]
        final_summary_text = "\n".join(["- " + b for b in merged_bullets if b])

    final_summary_text = _ensure_core_detail_sections(final_summary_text)

    tags = _dedupe_keep_order([str(x) for x in tags])[: active_cfg.max_tags]
    backlinks = _dedupe_keep_order([str(x) for x in backlinks])[
        : active_cfg.max_backlinks
    ]

    if not final_summary_text:
        final_summary_text = "(no summary)"

    return LlmResult(
        summary=final_summary_text,
        tags=tags,
        backlinks=backlinks,
        personal=personal,
    )


def synthesize_daily_overview(
    provider: LlmProvider,
    *,
    day: str,
    summaries: list[str],
    user_profile: dict | None = None,
) -> str:
    if not summaries:
        return ""

    # Performance guardrails for day-level synthesis.
    max_items = 24
    max_item_chars = 220
    max_total_chars = 8000

    compact_summaries: list[str] = []
    seen: set[str] = set()
    total_chars = 0
    for raw in summaries:
        s = str(raw or "").strip()
        if not s:
            continue
        # Normalize whitespace and drop obvious duplicates.
        s = re.sub(r"\s+", " ", s)
        key = s.lower()
        if key in seen:
            continue
        seen.add(key)

        clipped = s[:max_item_chars]
        next_total = total_chars + len(clipped)
        if compact_summaries and next_total > max_total_chars:
            break
        compact_summaries.append(clipped)
        total_chars = next_total
        if len(compact_summaries) >= max_items:
            break

    if not compact_summaries:
        return ""

    profile_info = ""
    if user_profile:
        roles = ", ".join(user_profile.get("roles", []))
        interests = user_profile.get("interests", "")
        profile_info = f"\n[User Profile]\n- Role: {roles}\n- Interests: {interests}\n"

    body = (
        f"아래는 {day} 하루 동안 수신된 이메일 요약본들입니다.\n"
        "이 내용들을 종합하여 사용자가 관심 있어 할 만한 주요 내용을 불릿 포인트로 요약하세요.\n"
        "반드시 한국어로 작성하고, 각 항목은 뉴스 헤드라인처럼 핵심만 간결하게 표현하세요.\n"
        + (
            f"\n중요: 아래 사용자 프로필에 맞춰 맞춤형 브리핑을 작성하세요.{profile_info}"
            if profile_info
            else ""
        )
        + "\n\n요약 목록:\n"
        + "\n".join([f"- {s}" for s in compact_summaries])
    )

    try:
        res = provider.summarize(subject=f"{day} Daily Overview", body=body)
        # Extract bullets from the result
        bullets = _extract_bullets(res.summary)
        return "\n".join(["- " + b for b in bullets]).strip()
    except Exception:
        return ""
