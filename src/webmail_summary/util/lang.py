from __future__ import annotations


def contains_hangul(text: str) -> bool:
    s = str(text or "")
    for ch in s:
        o = ord(ch)
        # Hangul syllables + jamo ranges
        if 0xAC00 <= o <= 0xD7A3 or 0x1100 <= o <= 0x11FF or 0x3130 <= o <= 0x318F:
            return True
    return False
