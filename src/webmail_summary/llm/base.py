from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LlmResult:
    summary: str
    tags: list[str]
    backlinks: list[str]
    personal: bool


class LlmProvider:
    @property
    def tier(self) -> str:
        """Return the tier of this provider: 'fast', 'standard', or 'cloud'."""
        return "standard"

    def summarize(self, *, subject: str, body: str) -> LlmResult:
        raise NotImplementedError
