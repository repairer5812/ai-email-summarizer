from __future__ import annotations

from dataclasses import dataclass

from collections.abc import Callable

from webmail_summary.llm.base import LlmImageInput, LlmProvider, LlmResult
import re


@dataclass(frozen=True)
class LongSummarizeConfig:
    # If body is longer than this, chunking is used.
    chunk_if_body_chars_over: int = 4500
    # Target chunk size in chars (approx; respects paragraph boundaries when possible).
    chunk_chars: int = 2400
    # Cap the number of chunks to keep latency bounded on very long emails.
    max_chunks: int | None = 6
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


def _has_strong_section_boundaries(text: str) -> bool:
    s = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    if not s.strip():
        return False

    lines = s.split("\n")
    separator_hits = sum(
        1 for line in lines if re.match(r"^\s*[-_=]{8,}\s*$", str(line or "").strip())
    )
    if separator_hits >= 1:
        return True

    paras = _split_paragraphs(s)
    if len(paras) >= 7:
        return True

    short_dense_paras = sum(1 for p in paras if 18 <= len(p) <= 220)
    return short_dense_paras >= 6


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


def _is_placeholder_bullet(text: str) -> bool:
    t = str(text or "").strip()
    if not t:
        return True

    low = t.lower()
    normalized = re.sub(r"[\s\[\]\(\)\{\}<>\-_*#`\"'“”‘’:;,.!?/\\|]+", "", low)
    if not normalized:
        return True

    if normalized in {"nosummary", "요약없음"}:
        return True
    if "상세요약항목이부족합니다" in normalized:
        return True
    if "llmtimeout" in normalized or "llmunavailable" in normalized:
        return True
    if "failedtoformatinput" in normalized or "invalidcodepoint" in normalized:
        return True
    if "loadingmodel" in normalized or "availablecommands" in normalized:
        return True
    return False


def _is_newsletter_like(*, subject: str, body: str, bullets: list[str]) -> bool:
    s = str(subject or "").strip().lower()
    if any(x in s for x in ["뉴스레터", "소식지", "newsletter", "q-letter", "qletter"]):
        return True
    # Many newsletters are long and contain many labeled bullets.
    if len(str(body or "")) >= 4500:
        return True
    labeled = sum(1 for b in bullets if ":" in str(b))
    if len(bullets) >= 10 and labeled >= 4:
        return True
    return False


def _is_article_like(*, subject: str, body: str) -> bool:
    s = str(subject or "").strip().lower()
    body_s = str(body or "")
    if len(body_s) < 900:
        return False
    if any(x in s for x in ["뉴스레터", "newsletter", "소식지"]):
        return False

    paras = _split_paragraphs(body_s)
    dense_paras = sum(1 for p in paras if len(p) >= 45)
    if len(paras) >= 6 and dense_paras >= 6:
        return True
    if len(paras) >= 6 and dense_paras >= 5 and _has_strong_section_boundaries(body_s):
        return True

    lines = [ln.strip() for ln in body_s.splitlines() if ln.strip()]
    dense_lines = sum(1 for ln in lines if len(ln) >= 45)
    if len(lines) >= 8 and dense_lines >= 6:
        return True

    long_sentences = sum(
        1 for seg in re.split(r"(?<=[.!?])\s+", body_s) if len(seg.strip()) >= 60
    )
    if len(lines) >= 8 and long_sentences >= 6:
        return True

    return False


def _target_min_bullets(*, subject: str, body: str, bullets: list[str]) -> int:
    body_len = len(str(body or ""))
    if _is_newsletter_like(subject=subject, body=body, bullets=bullets):
        return 8 if body_len >= 2500 else 6
    if _is_article_like(subject=subject, body=body):
        return 10 if body_len >= 2500 else 8
    return 4


def _is_noise_bullet(text: str) -> bool:
    """Return True if a bullet line is likely UI/notification noise."""

    t = str(text or "").strip()
    if not t:
        return True

    low = t.lower()

    if "\ufffd" in t:
        return True

    # URLs / bare links
    if "http://" in low or "https://" in low or low.startswith("www."):
        return True

    # Email header echoes
    if re.match(r"^(from|to|cc|bcc|subject|sent|date)\s*:\s*", t, re.IGNORECASE):
        return True
    if re.match(
        r"^(\ubcf4\ub0b8\uc0ac\ub78c|\ubcf4\ub0b8 \uc0ac\ub78c|\ubcf4\ub0b8\ub0a0\uc9dc|\uc218\uc2e0|\ucc38\uc870|\uc81c\ubaa9)\s*:\s*",
        t,
    ):
        return True

    # Standalone timestamps / timezone lines
    if "asia/seoul" in low or "+09:00" in low or "gmt" in low:
        if re.search(r"\d{4}[-./]\d{2}[-./]\d{2}", t) or re.search(r"\d{1,2}:\d{2}", t):
            return True
    if re.fullmatch(
        r"\d{4}[-./]\d{2}[-./]\d{2}(\([A-Za-z]{3}\))?(\s+\d{1,2}:\d{2}(:\d{2})?)?(\s*\([^)]*\))?",
        t,
    ):
        return True

    # Link-instruction boilerplate
    if any(
        k in t
        for k in [
            "\ubc14\ub85c\uac00\uae30",
            "\ubc14\ub85c \uac00\uae30",
            "\ud074\ub9ad",
            "Click",
            "click",
        ]
    ):
        if any(
            k in t
            for k in [
                "\ud655\uc778",
                "\ubb38\uc11c",
                "\uc811\uc18d",
                "\ub9c1\ud06c",
                "\ud574\ub2f9",
            ]
        ):
            return True
        if len(t) <= 12:
            return True

    # Bare email address
    if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", t):
        return True

    # Name-only artifacts (Korean or Latin) - remove only if extremely short.
    if len(t) <= 10 and re.fullmatch(
        r"[\uac00-\ud7a3]{2,4}(?:\s+[\uac00-\ud7a3]{2,4})?", t
    ):
        return True
    if len(t) <= 24 and re.fullmatch(r"[A-Za-z][A-Za-z .'-]{1,23}", t):
        return True

    # Greeting / signature-like lines that are usually off-topic in summaries.
    if re.search(r"\b(안녕하세요|감사합니다|좋은\s*하루|즐거운\s*하루)\b", t):
        return True
    if re.search(r"(올림|드림)$", t):
        return True
    if re.search(
        r"\b(대표이사|팀장|부장|과장|실장|박사|교수|기자)\b", t
    ) and t.endswith("입니다."):
        return True

    # Workflow/notification artifacts.
    if any(k in t for k in ["결재 완료", "승인 요청", "승인 완료", "반려", "실패"]):
        if any(k in t for k in ["바로가기", "클릭", "문서", "결재"]):
            return True

    return False


def _tokenize_for_relevance(text: str) -> set[str]:
    s = str(text or "")
    toks = re.findall(r"[A-Za-z]{2,}|[0-9]{2,}|[가-힣]{2,}", s)
    return {t.lower() for t in toks}


def _is_context_relevant_bullet(*, bullet: str, source_tokens: set[str]) -> bool:
    b = str(bullet or "").strip()
    if not b:
        return False
    if _is_placeholder_bullet(b):
        return False
    if _is_noise_bullet(b):
        return False

    btoks = _tokenize_for_relevance(b)
    if not btoks:
        return False

    overlap = sum(1 for t in btoks if t in source_tokens)
    if overlap <= 0:
        return False

    ratio = overlap / max(1, len(btoks))
    # Avoid keeping generic/off-context lines with very weak lexical anchoring.
    if len(btoks) >= 5 and ratio < 0.2 and not re.search(r"\d", b):
        return False

    return True


def _validate_summary_bullets(
    *,
    subject: str,
    body: str,
    bullets: list[str],
    min_keep: int,
    max_keep: int,
) -> list[str]:
    source_tokens = _tokenize_for_relevance(f"{subject}\n{body[:16000]}")
    out: list[str] = []
    for b in _dedupe_keep_order([str(x or "").strip() for x in bullets]):
        if _is_context_relevant_bullet(bullet=b, source_tokens=source_tokens):
            out.append(b)

    if len(out) < max(1, int(min_keep)):
        # Recover with conservative body-derived bullets.
        fb = _fallback_bullets_from_body(body, limit=max(16, int(max_keep) + 6))
        existing_tokens = _tokenize_for_relevance("\n".join(out))
        seen_lows = {y.lower() for y in out}

        scored: list[tuple[int, int, str]] = []
        for idx, x in enumerate(fb):
            if not _is_context_relevant_bullet(bullet=x, source_tokens=source_tokens):
                continue
            xl = x.lower()
            if xl in seen_lows:
                continue
            xtoks = _tokenize_for_relevance(x)
            novelty = sum(1 for t in xtoks if t not in existing_tokens)
            scored.append((novelty, idx, x))

        # Prefer lexically novel candidates first to avoid repeating only the
        # opening section when the model output is shallow.
        scored.sort(key=lambda it: (-it[0], it[1]))

        for _novelty, _idx, x in scored:
            xl = x.lower()
            if xl in seen_lows:
                continue
            out.append(x)
            seen_lows.add(xl)
            existing_tokens.update(_tokenize_for_relevance(x))
            if len(out) >= max(1, int(min_keep)):
                break

    # For medium/long mails, ensure at least one bullet anchored in the latter
    # part of the body so second-half sections are not dropped entirely.
    if len(str(body or "")) >= 800 and out:
        s_body = str(body or "")
        tail = s_body[int(len(s_body) * 0.55) :]
        tail_tokens = _tokenize_for_relevance(tail)

        def _is_tail_anchored(x: str) -> bool:
            if not tail_tokens:
                return True
            xt = _tokenize_for_relevance(x)
            if not xt:
                return False
            overlap = sum(1 for t in xt if t in tail_tokens)
            return overlap >= 2

        if tail_tokens and not any(_is_tail_anchored(b) for b in out):
            fb_tail = _fallback_bullets_from_body(
                body, limit=max(20, int(max_keep) + 8)
            )
            seen_lows = {y.lower() for y in out}
            for x in fb_tail:
                xl = x.lower()
                if xl in seen_lows:
                    continue
                if not _is_tail_anchored(x):
                    continue
                if not _is_context_relevant_bullet(
                    bullet=x, source_tokens=source_tokens
                ):
                    continue
                out.append(x)
                break

    if len(out) < 2:
        out.append("본문의 추가 정보가 제한적입니다.")

    return _dedupe_keep_order(out)[: max(1, int(max_keep))]


def _build_dynamic_cfg(
    provider: LlmProvider,
    *,
    body_len: int,
    tier: str,
    cfg: LongSummarizeConfig,
) -> LongSummarizeConfig:
    # Derive chunk sizes from model context when available.
    default_ctx_tokens = {
        "fast": 3072,
        "standard": 4096,
        "performance": 4096,
        "cloud": 8192,
    }
    ctx_tokens = int(default_ctx_tokens.get(tier, 4096))

    p_cfg = getattr(provider, "_cfg", None)
    try:
        if p_cfg is not None and hasattr(p_cfg, "ctx_size"):
            ctx_tokens = max(1024, int(getattr(p_cfg, "ctx_size")))
    except Exception:
        pass

    # Reserve headroom for instructions + output tokens.
    usable_tokens = max(800, int(ctx_tokens * 0.62))
    # Conservative char estimate for mixed Korean/English.
    input_chars_budget = max(1600, int(usable_tokens * 1.9))

    def _clamp(v: int, lo: int, hi: int) -> int:
        return max(lo, min(hi, int(v)))

    chunk_chars = _clamp(int(input_chars_budget * 0.64), 1600, 10000)
    chunk_if_over = _clamp(int(input_chars_budget * 0.9), 2200, 12000)

    # Bound total map calls for latency; still scale with body size.
    est_chunks = max(1, (max(1, int(body_len)) + chunk_chars - 1) // chunk_chars)
    max_chunks = _clamp(est_chunks + 1, 2, 10)

    if tier == "fast":
        chunk_chars = min(chunk_chars, 3200)
        max_chunks = min(max_chunks, 4)
    elif tier in {"standard", "performance"}:
        chunk_chars = min(chunk_chars, 4200)
        max_chunks = min(max_chunks, 6)
    else:  # cloud
        chunk_chars = min(chunk_chars, 10000)
        max_chunks = min(max_chunks, 8)

    return LongSummarizeConfig(
        chunk_if_body_chars_over=chunk_if_over,
        chunk_chars=chunk_chars,
        max_chunks=max_chunks,
        max_bullets=cfg.max_bullets,
        part_bullets=cfg.part_bullets,
        max_tags=cfg.max_tags,
        max_backlinks=cfg.max_backlinks,
    )


def _structure_newsletter_summary(
    *, subject: str, body: str, bullets: list[str]
) -> str:
    """Build a UI-friendly newsletter summary.

    Target style (as rendered by ui/static/app.js):
    - [핵심 결론]: ...
    ### 섹션 제목
    - 라벨: 내용

    This is a deterministic post-processor so the UI stays consistent even when
    smaller local models return thin/flat bullets.
    """

    # subject currently used only for newsletter detection upstream.
    _ = subject

    raw_bullets = _dedupe_keep_order([str(x or "").strip() for x in bullets])

    def is_noise(x: str) -> bool:
        return _is_noise_bullet(x)

    cleaned: list[str] = []
    for b in raw_bullets:
        if is_noise(b):
            continue
        # Remove any existing section markers so we can rebuild consistently.
        if b.lstrip().startswith("###"):
            continue
        n = b.lower().replace(" ", "").strip("[]").strip()
        if n in {
            "핵심요약",
            "상세요약",
            "핵심결론",
            "핵심전략결론",
            "주요소식",
            "주제별분석",
            "심층구조화",
            "구조화",
        }:
            continue
        cleaned.append(b)

    # If we still don't have enough content, use body heuristics.
    if len(cleaned) < 8:
        fb = _fallback_bullets_from_body(str(body or ""), limit=14)
        for x in fb:
            if is_noise(x):
                continue
            if x.lower() not in {y.lower() for y in cleaned}:
                cleaned.append(x)
            if len(cleaned) >= 12:
                break

    cleaned = _dedupe_keep_order(cleaned)
    if not cleaned:
        return "- [\ud575\uc2ec \uacb0\ub860]: (\uc694\uc57d \uc5c6\uc74c)."

    def pick_section(b: str) -> str:
        t = str(b or "")
        # (keep matching in original case for Korean tokens)
        # International/partnership
        if any(
            k in t
            for k in [
                "\uad6d\uc81c",
                "\uae00\ub85c\ubc8c",
                "\ud574\uc678",
                "\ud30c\ud2b8\ub108",
                "\ud611\ub825",
                "MOU",
                "KOTRA",
                "\uc544\ud504\ub9ac\uce74",
                "\uc9c4\ucd9c",
            ]
        ):
            return "intl"
        # Events/expo/contests
        if any(
            k in t
            for k in [
                "\ubc15\ub78c\ud68c",
                "\uc804\uc2dc",
                "\ud589\uc0ac",
                "\ud3ec\ub7fc",
                "\uc138\ubbf8\ub098",
                "\ucee8\ud37c\ub7f0\uc2a4",
                "\ub300\ud68c",
                "\uacbd\uc2dc\ub300\ud68c",
                "\uc2dc\uc0c1",
                "\uac1c\ucd5c",
                "\ucc38\uac00",
            ]
        ):
            return "event"
        # Policy/market
        if any(
            k in t
            for k in [
                "\uc81c\ub3c4",
                "\uc815\ucc45",
                "\uc2dc\uc7a5",
                "\uaddc\uc81c",
                "\uc870\ub2ec",
                "\uc778\uc99d",
                "\ud45c\uc900",
                "\uac00\uc774\ub4dc\ub77c\uc778",
                "\ubcf4\uc548",
                "\uac1c\uc778\uc815\ubcf4",
            ]
        ):
            return "policy"
        # Company news: has label: content pattern
        if ":" in t and len(t.split(":", 1)[0].strip()) <= 24:
            return "company"
        return "other"

    sections: dict[str, list[str]] = {
        "event": [],
        "company": [],
        "intl": [],
        "policy": [],
        "other": [],
    }
    for b in cleaned:
        sections[pick_section(b)].append(b)

    # Decide which sections to show (up to 3) + spillover.
    order = ["event", "company", "intl", "policy", "other"]
    present = [k for k in order if sections.get(k)]
    chosen = present[:3] if present else ["other"]

    def title_for(key: str) -> str:
        if key == "event":
            # Match the user's preferred phrasing when possible.
            if any(
                "\ubc15\ub78c\ud68c" in x or "\uc804\uad6d" in x
                for x in sections.get(key, [])
            ):
                return "\uad50\uc721 \ubc0f \uae30\uc220 \ubc15\ub78c\ud68c \ucc38\uac00 \ud604\ud669"
            return "\ud589\uc0ac/\uc804\uc2dc \ub3d9\ud5a5"
        if key == "company":
            return "\uae30\uc5c5\ubcc4 \uc8fc\uc694 \ub274\uc2a4"
        if key == "intl":
            return "\uad6d\uc81c \ud611\ub825 \ubc0f \ud30c\ud2b8\ub108\uc2ed"
        if key == "policy":
            return "\uc2dc\uc7a5/\uc815\ucc45 \ubcc0\ud654"
        return "\uae30\ud0c0 \uc8fc\uc694 \uc0ac\ud56d"

    # Core conclusion: mention the dominant sections.
    sec_names = [title_for(k) for k in chosen]
    if len(sec_names) >= 2:
        core = f"\uc774\ubc88 \uba54\uc77c\uc740 {sec_names[0]}\uc640 {sec_names[1]} \uc911\uc2ec\uc73c\ub85c, \uac1c\ubcc4 \uc5c5\uccb4\uc758 \ud65c\ub3d9/\uc131\uacfc \uc5c5\ub370\uc774\ud2b8\uac00 \ud3ec\ud568\ub429\ub2c8\ub2e4."
    else:
        core = f"\uc774\ubc88 \uba54\uc77c\uc740 {sec_names[0]} \uad00\ub828 \uc5c5\ub370\uc774\ud2b8\uac00 \ud575\uc2ec\uc785\ub2c8\ub2e4."

    lines: list[str] = [f"- [\ud575\uc2ec \uacb0\ub860]: {core}"]

    max_per_section = 6
    for key in chosen:
        lines.append("")
        lines.append(f"### {title_for(key)}")
        for b in sections.get(key, [])[:max_per_section]:
            lines.append("- " + b)

    # If there are leftover bullets from unchosen sections, add a final spillover.
    leftovers: list[str] = []
    for key in order:
        if key in chosen:
            continue
        leftovers.extend(sections.get(key, [])[:3])
    leftovers = _dedupe_keep_order(leftovers)
    if leftovers:
        lines.append("")
        lines.append(f"### {title_for('other')}")
        for b in leftovers[:5]:
            lines.append("- " + b)

    return "\n".join(lines).strip()


def _fallback_bullets_from_body(body: str, *, limit: int) -> list[str]:
    """Heuristic fallback bullets when the model output is too thin.

    This is used sparingly: only when the LLM returns very few bullets.
    It extracts sentence/line candidates from the visible body while filtering common footer noise.
    """

    s = str(body or "").strip()
    if not s:
        return []

    noise_needles = [
        "unsubscribe",
        "수신거부",
        "수신 거부",
        "개인정보",
        "privacy",
        "대표전화",
        "고객센터",
        "사업자등록",
        "사업자 등록",
        "무단전재",
        "all rights reserved",
        "copyright",
        "서울특별시",
        "주소:",
        "address",
        "tel",
        "fax",
    ]

    def is_noise_line(line: str) -> bool:
        if _is_noise_bullet(line):
            return True
        low = line.lower()
        if "http://" in low or "https://" in low or low.startswith("www."):
            return True
        if "@" in line and "." in line and len(line) < 80:
            # likely an email address line
            return True
        for n in noise_needles:
            if n in low:
                return True
        return False

    def _looks_like_new_item(t: str) -> bool:
        if not t:
            return False
        if t.lstrip().startswith("###"):
            return True
        if re.match(r"^([\-•·\*]+)\s+", t):
            return True
        if re.match(r"^\(?\d+\)?[\.)]\s+", t):
            return True
        # "Label: content" often denotes a new bullet-ish item.
        if re.match(r"^[^\s:]{1,24}\s*:\s*\S+", t):
            return True
        return False

    def _ends_sentence(t: str) -> bool:
        tt = (t or "").strip()
        if not tt:
            return False
        if tt.endswith((".", "?", "!")):
            return True
        # Common Korean sentence endings.
        if tt.endswith(("다.", "니다.", "습니다.", "요.")):
            return True
        return False

    # Merge soft-wrapped lines so a single sentence isn't cut at arbitrary newlines.
    merged_lines: list[str] = []
    cur = ""
    for raw in s.splitlines():
        t = re.sub(r"\s+", " ", str(raw or "")).strip()
        if not t:
            if cur:
                merged_lines.append(cur)
                cur = ""
            continue
        if is_noise_line(t):
            if cur:
                merged_lines.append(cur)
                cur = ""
            continue

        if not cur:
            cur = t
            continue

        if _looks_like_new_item(t):
            merged_lines.append(cur)
            cur = t
            continue

        if _ends_sentence(cur):
            merged_lines.append(cur)
            cur = t
            continue

        cur = (cur + " " + t).strip()

    if cur:
        merged_lines.append(cur)

    raw_lines = merged_lines
    cand: list[str] = []
    for ln in raw_lines:
        if not ln:
            continue
        if len(ln) < 12:
            continue
        if is_noise_line(ln):
            continue
        # Strip leading bullets/numbering.
        t = re.sub(r"^([\-•·\*]+)\s*", "", ln).strip()
        t = re.sub(r"^\(?\d+\)?[\.)]\s*", "", t).strip()
        if not t or len(t) < 12:
            continue
        # Clip overly long lines.
        if len(t) > 220:
            t = t[:220].rstrip() + "..."
        cand.append(t)
        if len(cand) >= max(40, int(limit) * 6):
            break

    # Prefer lines with numbers/dates/colon.
    def score(x: str) -> int:
        sc = 0
        if re.search(r"\d", x):
            sc += 2
        if ":" in x or "·" in x:
            sc += 1
        if re.search(r"\b(\d{1,2}/\d{1,2}|\d{4}-\d{2}-\d{2})\b", x):
            sc += 2
        return sc

    # Stable sort: keep original order among same scores.
    indexed = list(enumerate(cand))
    indexed.sort(key=lambda it: (-score(it[1]), it[0]))
    picked = [t for _i, t in indexed]
    return _dedupe_keep_order(picked)[: max(0, int(limit))]


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
        if _is_placeholder_bullet(t):
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
            if _is_placeholder_bullet(t):
                continue
            n = t.lower().replace(" ", "").strip("[]").strip()
            if n in skip_headers:
                continue
            cleaned.append(t)

    cleaned = _dedupe_keep_order(cleaned)
    if not cleaned:
        return "### 핵심 요약\n- (요약 없음)\n\n### 상세 요약\n- (요약 없음)"

    n = len(cleaned)
    # Avoid duplicating core bullets into the detail section.
    # When there are few bullets, split them across the two sections.
    if n <= 1:
        core = cleaned[:1]
        detail: list[str] = []
    elif n == 2:
        core = cleaned[:1]
        detail = cleaned[1:]
    elif n == 3:
        core = cleaned[:2]
        detail = cleaned[2:]
    elif n in {4, 5}:
        core = cleaned[:2]
        detail = cleaned[2:]
    else:
        core = cleaned[:3]
        detail = cleaned[3:10]

    if not detail:
        detail = ["(상세 요약 항목이 부족합니다.)"]

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
    multimodal_inputs: list[LlmImageInput] | None = None,
) -> LlmResult:
    body_s = str(body or "")

    # Tier-aware, context-aware dynamic chunk configuration.
    tier = getattr(provider, "tier", "standard")
    active_cfg = _build_dynamic_cfg(provider, body_len=len(body_s), tier=tier, cfg=cfg)

    skip_headers_norm = {
        "핵심요약",
        "상세요약",
        "핵심결론",
        "핵심전략결론",
        "주요소식",
        "주제별분석",
        "심층구조화",
        "구조화",
    }

    def _is_header_line(x: str) -> bool:
        n = str(x or "").lower().replace(" ", "").strip("[]").strip()
        return n in skip_headers_norm

    article_like = _is_article_like(subject=subject, body=body_s)
    force_chunked_coverage = len(body_s) >= 900 and (
        _has_strong_section_boundaries(body_s) or article_like
    )

    if (
        not force_chunked_coverage
        and len(body_s) <= active_cfg.chunk_if_body_chars_over
    ):
        res = provider.summarize(
            subject=subject,
            body=body_s,
            multimodal_inputs=multimodal_inputs,
        )
        raw_bullets = _dedupe_keep_order(
            [
                b
                for b in _extract_bullets(res.summary)
                if b
                and ("\ufffd" not in b)
                and (not _is_placeholder_bullet(b))
                and (not _is_header_line(b))
                and (not _is_noise_bullet(b))
            ]
        )
        min_keep = _target_min_bullets(
            subject=subject, body=body_s, bullets=raw_bullets
        )
        bullets = _validate_summary_bullets(
            subject=subject,
            body=body_s,
            bullets=raw_bullets,
            min_keep=min_keep,
            max_keep=active_cfg.max_bullets,
        )
        summary_text = (
            "\n".join(["- " + b for b in bullets if b]).strip() or res.summary
        )
        # For newsletters, prefer a multi-section structure.
        bullets2 = _dedupe_keep_order(
            [
                b
                for b in _extract_bullets(summary_text)
                if b
                and ("\ufffd" not in b)
                and (not _is_placeholder_bullet(b))
                and (not _is_noise_bullet(b))
            ]
        )
        if _is_newsletter_like(subject=subject, body=body_s, bullets=bullets2):
            summary_out = _structure_newsletter_summary(
                subject=subject, body=body_s, bullets=bullets2
            )
        else:
            summary_out = _ensure_core_detail_sections(summary_text)

        return LlmResult(
            summary=summary_out,
            tags=list(res.tags or []),
            backlinks=list(res.backlinks or []),
            personal=bool(res.personal),
        )

    chunk_chars = active_cfg.chunk_chars
    if force_chunked_coverage:
        chunk_chars = min(chunk_chars, 900)

    chunks = _chunk_text(
        body_s,
        chunk_chars=chunk_chars,
        max_chunks=active_cfg.max_chunks,
    )
    if not chunks:
        res = provider.summarize(
            subject=subject,
            body=body_s[: active_cfg.chunk_chars],
            multimodal_inputs=multimodal_inputs,
        )
        raw_bullets = _dedupe_keep_order(
            [
                b
                for b in _extract_bullets(res.summary)
                if b
                and ("\ufffd" not in b)
                and (not _is_placeholder_bullet(b))
                and (not _is_header_line(b))
                and (not _is_noise_bullet(b))
            ]
        )
        min_keep = _target_min_bullets(
            subject=subject, body=body_s, bullets=raw_bullets
        )
        checked = _validate_summary_bullets(
            subject=subject,
            body=body_s,
            bullets=raw_bullets,
            min_keep=min_keep,
            max_keep=active_cfg.max_bullets,
        )
        summary_text = (
            "\n".join(["- " + b for b in checked if b]).strip() or res.summary
        )
        return LlmResult(
            summary=_ensure_core_detail_sections(summary_text),
            tags=list(res.tags or []),
            backlinks=list(res.backlinks or []),
            personal=bool(res.personal),
        )

    detailed_parts: list[str] = []
    all_bullets: list[str] = []
    tags: list[str] = []
    backlinks: list[str] = []
    personal = False

    # Synthesis adds one extra LLM call but significantly improves output quality
    # for long newsletters (chunked body). Keep it enabled for all tiers.
    skip_synthesis = False
    # Total units: chunks + (optional) synthesis
    total_units = len(chunks) + (0 if skip_synthesis else 1)

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
        part_bullets = [
            b
            for b in _extract_bullets(res.summary)
            if b
            and ("\ufffd" not in b)
            and (not _is_placeholder_bullet(b))
            and (not _is_header_line(b))
            and (not _is_noise_bullet(b))
        ]
        all_bullets.extend(part_bullets)
        tags.extend(list(res.tags or []))
        backlinks.extend(list(res.backlinks or []))
        personal = personal or bool(res.personal)

        part_limit = max(1, int(active_cfg.part_bullets))
        if article_like:
            part_limit = max(part_limit, 7)
        short = _dedupe_keep_order(part_bullets)[:part_limit]
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
    if not skip_synthesis:
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
                # Lite version for smaller local models (e.g., Gemma 3 4B)
                system_role = "뉴스레터를 요약하는 어시스턴트"
                guidelines = (
                    "1. 형식 고정: 반드시 '### 핵심 요약' 섹션과 '### 상세 요약' 섹션 2개로 작성하세요.\n"
                    "2. 핵심 요약: 가장 중요한 내용 3~5개를 불릿 포인트로 작성하세요.\n"
                    f"3. 상세 요약: 본문 사실에 충실하게 {'8~12개 불릿으로 최대한 폭넓게' if article_like else '최대 7개 불릿으로'} 작성하세요.\n"
                    "4. 노이즈 제거: 주소, 저작권, 구독 취소 안내 등은 무시하세요.\n"
                    "5. 반드시 한국어로만 작성하고 문장을 마침표로 끝내세요."
                )
            elif tier == "cloud":
                # Executive version for high-capability models (Gemini, OpenAI etc)
                system_role = "전문적인 전략 분석가 및 수석 에디터"
                article_line = (
                    "6. 앞부분 요지만 반복하지 말고 후반부 정보와 사례도 반드시 포함하세요.\n"
                    if article_like
                    else ""
                )
                guidelines = (
                    "1. 형식 고정: 반드시 '### 핵심 요약'과 '### 상세 요약' 머리말을 사용하세요.\n"
                    f"2. 핵심 요약: 최상단에 전체를 관통하는 핵심 결론 {'3~4개' if article_like else '3~5개'}를 불릿으로 작성하세요.\n"
                    f"3. 상세 요약: 본문 사실에 근거해 주제별 핵심 사실을 {'8~12개 불릿으로 최대한 폭넓게 정리' if article_like else '최대 7개 불릿으로 정리'}하세요.\n"
                    "4. 데이터 밀도: 수치, 인물, 결정 사항을 포함하되 과장/추측은 금지하세요.\n"
                    "5. 노이즈 제거: 주소, 저작권, 구독 취소 안내 등은 포함하지 마세요.\n"
                    f"{article_line}7. 반드시 한국어로만 격식 있는 문체로 작성하세요."
                )
            else:
                # Standard version (EXAONE, Qwen 3B etc)
                system_role = "뉴스레터를 요약하는 전문 에디터"
                guidelines = (
                    "1. 형식 고정: 반드시 '### 핵심 요약'과 '### 상세 요약' 머리말을 사용하세요.\n"
                    "2. 핵심 요약: 가장 중요한 내용 3~5개를 불릿으로 작성하세요.\n"
                    f"3. 상세 요약: 본문 사실에 충실하게 {'8~12개 불릿으로 최대한 폭넓게' if article_like else '최대 7개 불릿으로'} 작성하세요.\n"
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
                multimodal_inputs=multimodal_inputs,
            )

            # Preserve original formatting (headers/bold) if it looks structured
            raw_synth = _ensure_core_detail_sections(synth.summary.strip())
            if _is_structured(raw_synth):
                final_summary_text = raw_synth
            else:
                merged_bullets = _extract_bullets(raw_synth)
                final_summary_text = "\n".join(["- " + b for b in merged_bullets if b])

            synth_bullets = _dedupe_keep_order(
                [
                    b
                    for b in _extract_bullets(final_summary_text)
                    if b
                    and (not _is_placeholder_bullet(b))
                    and (not _is_header_line(b))
                    and (not _is_noise_bullet(b))
                ]
            )
            target_min = _target_min_bullets(
                subject=subject,
                body=body_s,
                bullets=synth_bullets,
            )
            merged_chunk_bullets = _dedupe_keep_order(
                [
                    b
                    for b in all_bullets
                    if b
                    and (not _is_placeholder_bullet(b))
                    and (not _is_header_line(b))
                    and (not _is_noise_bullet(b))
                ]
            )
            if (
                len(synth_bullets) < target_min
                and len(merged_chunk_bullets) >= target_min
            ):
                final_summary_text = "\n".join(
                    ["- " + b for b in merged_chunk_bullets if b]
                )

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
        merged_bullets = _dedupe_keep_order(
            [
                b
                for b in all_bullets
                if b
                and (not _is_placeholder_bullet(b))
                and (not _is_header_line(b))
                and (not _is_noise_bullet(b))
            ]
        )
        min_keep = _target_min_bullets(
            subject=subject, body=body_s, bullets=merged_bullets
        )
        merged_bullets = _validate_summary_bullets(
            subject=subject,
            body=body_s,
            bullets=merged_bullets,
            min_keep=min_keep,
            max_keep=active_cfg.max_bullets,
        )
        final_summary_text = "\n".join(["- " + b for b in merged_bullets if b])

    # Prefer newsletter-style sections when the content looks like a newsletter.
    final_bullets = _dedupe_keep_order(
        [
            b
            for b in _extract_bullets(final_summary_text)
            if b
            and ("\ufffd" not in b)
            and (not _is_placeholder_bullet(b))
            and (not _is_noise_bullet(b))
        ]
    )
    min_keep = _target_min_bullets(subject=subject, body=body_s, bullets=final_bullets)
    final_bullets = _validate_summary_bullets(
        subject=subject,
        body=body_s,
        bullets=final_bullets,
        min_keep=min_keep,
        max_keep=active_cfg.max_bullets,
    )
    display_bullets = _dedupe_keep_order(
        [
            b
            for b in _extract_bullets(final_summary_text)
            if b
            and ("\ufffd" not in b)
            and (not _is_placeholder_bullet(b))
            and (not _is_header_line(b))
            and (not _is_noise_bullet(b))
        ]
        + list(final_bullets)
    )[: active_cfg.max_bullets]
    rebuilt_summary_text = "\n".join(["- " + b for b in display_bullets if b]).strip()
    if _is_newsletter_like(subject=subject, body=body_s, bullets=final_bullets):
        final_summary_text = _structure_newsletter_summary(
            subject=subject, body=body_s, bullets=final_bullets
        )
    else:
        final_summary_text = _ensure_core_detail_sections(
            rebuilt_summary_text or final_summary_text
        )

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

    target_count = len(compact_summaries) if len(compact_summaries) <= 5 else 5

    def _fallback_headlines(limit: int) -> list[str]:
        out: list[str] = []
        for raw in compact_summaries:
            line = ""
            for b in _extract_bullets(raw):
                t = str(b or "").strip()
                if not t:
                    continue
                if _is_noise_bullet(t):
                    continue
                normalized = t.lower().replace(" ", "").strip("[]").strip()
                if normalized in {"핵심요약", "상세요약"}:
                    continue
                line = t
                break
            if not line:
                line = re.sub(r"^[-*•·\s]+", "", str(raw or "").strip())
            line = re.sub(r"\s+", " ", line).strip()
            if len(line) > 120:
                line = line[:120].rstrip() + "..."
            if line:
                out.append(line)
            if len(out) >= limit:
                break
        return _dedupe_keep_order(out)

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
        bullets = _dedupe_keep_order(_extract_bullets(res.summary))

        fallback_limit = max(len(compact_summaries), target_count)
        fallbacks = _fallback_headlines(fallback_limit)

        if len(compact_summaries) <= 5:
            if len(bullets) < target_count:
                for fb in fallbacks:
                    if fb.lower() not in {x.lower() for x in bullets}:
                        bullets.append(fb)
                    if len(bullets) >= target_count:
                        break
            bullets = bullets[:target_count]
        else:
            if len(bullets) < target_count:
                for fb in fallbacks:
                    if fb.lower() not in {x.lower() for x in bullets}:
                        bullets.append(fb)
                    if len(bullets) >= target_count:
                        break

        if not bullets:
            bullets = fallbacks[:target_count]

        return "\n".join(["- " + b for b in bullets]).strip()
    except Exception:
        fallbacks = _fallback_headlines(target_count)
        return "\n".join(["- " + b for b in fallbacks]).strip()
