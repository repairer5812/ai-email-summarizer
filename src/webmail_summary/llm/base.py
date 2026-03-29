from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LlmResult:
    summary: str
    tags: list[str]
    backlinks: list[str]
    personal: bool


@dataclass(frozen=True)
class LlmImageInput:
    path: str
    mime_type: str | None = None
    detail: str = "auto"
    source: str = ""


class LlmProvider:
    @property
    def tier(self) -> str:
        """Return the tier of this provider: 'fast', 'standard', or 'cloud'."""
        return "standard"

    def supports_multimodal_inputs(self) -> bool:
        return False

    def summarize(
        self,
        *,
        subject: str,
        body: str,
        multimodal_inputs: list[LlmImageInput] | None = None,
    ) -> LlmResult:
        _ = (subject, body, multimodal_inputs)
        raise NotImplementedError
