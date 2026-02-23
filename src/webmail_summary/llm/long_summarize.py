from __future__ import annotations

from dataclasses import dataclass

from collections.abc import Callable

from webmail_summary.llm.base import LlmProvider, LlmResult


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

    # If it looks like bullet lines, keep them.
    lines = [ln.strip() for ln in s.splitlines() if ln.strip()]
    if any(ln.startswith("-") for ln in lines):
        out: list[str] = []
        for ln in lines:
            if ln.startswith("-"):
                out.append(ln.lstrip("- ").strip())
            else:
                out.append(ln)
        return [x for x in out if x]

    # If it's a single line with separators.
    if "; " in s:
        return [x.strip() for x in s.split("; ") if x.strip()]

    return [s]


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
    return "###" in s or "**" in s or (s.count("\n\n") >= 2)


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
    if len(body_s) <= cfg.chunk_if_body_chars_over:
        return provider.summarize(subject=subject, body=body_s)

    chunks = _chunk_text(body_s, chunk_chars=cfg.chunk_chars, max_chunks=cfg.max_chunks)
    if not chunks:
        return provider.summarize(subject=subject, body=body_s[: cfg.chunk_chars])

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

        short = _dedupe_keep_order(part_bullets)[: max(1, int(cfg.part_bullets))]
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
            custom_tailor = f"\n**중요**: 아래 사용자 프로필에 맞춰 사용자가 특히 관심있어 할 내용을 강조하여 요약하세요.{profile_info}"

        if tier == "fast":
            # Lite version for small models (like Gemma 2 2B)
            system_role = "뉴스레터를 요약하는 어시스턴트"
            guidelines = (
                "1. **핵심 요약**: 가장 중요한 내용 3~5개를 불릿 포인트로 작성하세요.\n"
                "2. **단순 구조**: `[주요 소식]`과 같은 간단한 주제별로 그룹화하세요.\n"
                "3. **노이즈 제거**: 주소, 저작권, 구독 취소 안내 등은 무시하세요.\n"
                "4. 반드시 한국어로만 작성하고 문장을 마침표로 끝내세요."
            )
        elif tier == "cloud":
            # Executive version for high-capability models (Gemini, OpenAI etc)
            system_role = "전문적인 전략 분석가 및 수석 에디터"
            guidelines = (
                "1. **BLUF (핵심 결론 우선)**: 최상단에 전체를 관통하는 인사이트를 `**[핵심 전략 결론]**`으로 굵게 작성하세요.\n"
                "2. **심층 구조화**: `### [주제별 분석]` 머리말을 사용하여 논리적으로 섹션을 나누세요.\n"
                "3. **데이터 밀도**: 수치, 인물, 결정 사항을 포함하여 전문 리포트 수준의 풍부한 정보를 담으세요.\n"
                "4. **Smart Brevity**: 각 섹션마다 'Why it matters'를 포함하여 가치가 높은 리포트를 작성하세요.\n"
                "5. 반드시 한국어로만 격식 있는 문체로 작성하세요."
            )
        else:
            # Standard version (EXAONE, Qwen 3B etc)
            system_role = "뉴스레터를 요약하는 전문 에디터"
            guidelines = (
                "1. **BLUF (핵심 결론 우선)**: 최상단에 가장 중요한 결론을 `**[핵심 결론]**` 머리말과 함께 작성하세요.\n"
                "2. **구조화**: 관련 소식을 2~3개의 주제로 묶고 `### [주제명]` 머리말을 사용하세요.\n"
                "3. **Smart Brevity**: 주제 아래에 핵심 요지를 적고 상세 내용을 불릿으로 설명하세요.\n"
                "4. **노이즈 제거**: 주소, 저작권, 구독 취소 안내 등은 포함하지 마세요.\n"
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
        raw_synth = synth.summary.strip()
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
        merged_bullets = _dedupe_keep_order(all_bullets)[: cfg.max_bullets]
        final_summary_text = "\n".join(["- " + b for b in merged_bullets if b])

    tags = _dedupe_keep_order([str(x) for x in tags])[: cfg.max_tags]
    backlinks = _dedupe_keep_order([str(x) for x in backlinks])[: cfg.max_backlinks]

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

    profile_info = ""
    if user_profile:
        roles = ", ".join(user_profile.get("roles", []))
        interests = user_profile.get("interests", "")
        profile_info = f"\n[User Profile]\n- Role: {roles}\n- Interests: {interests}\n"

    body = (
        f"아래는 {day} 하루 동안 수신된 이메일 요약본들입니다.\n"
        "이 내용들을 종합하여 사용자가 가장 관심 있어 할 만한 내용을 5줄 이내의 불릿 포인트로 요약하세요.\n"
        "반드시 한국어로 작성하세요.\n"
        + (
            f"\n**중요**: 아래 사용자 프로필에 맞춰 맞춤형 브리핑을 작성하세요.{profile_info}"
            if profile_info
            else ""
        )
        + "\n\n요약 목록:\n"
        + "\n".join([f"- {s[:300]}" for s in summaries])
    )

    try:
        res = provider.summarize(subject=f"{day} Daily Overview", body=body)
        # Extract bullets from the result
        bullets = _extract_bullets(res.summary)
        return "\n".join(["- " + b for b in bullets[:5]]).strip()
    except Exception:
        return ""
