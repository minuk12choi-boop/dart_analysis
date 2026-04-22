from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(slots=True)
class ReportPreviewQualityFilter:
    max_preview_length: int = 120

    def filter_values(self, values: list[str]) -> tuple[list[str], dict[str, int]]:
        cleaned: list[str] = []
        suppressed = 0
        seen: set[str] = set()

        for raw in values:
            text = self._normalize(raw)
            if not text:
                suppressed += 1
                continue
            if self._looks_like_noisy_markup(text):
                suppressed += 1
                continue
            normalized = text[: self.max_preview_length]
            if normalized in seen:
                continue
            seen.add(normalized)
            cleaned.append(normalized)

        return cleaned, {
            "input_count": len(values),
            "filtered_count": len(cleaned),
            "suppressed_noisy_count": suppressed,
        }

    def _normalize(self, value: str) -> str:
        return re.sub(r"\s+", " ", str(value or "")).strip()

    def _looks_like_noisy_markup(self, text: str) -> bool:
        if re.search(r"</?[A-Za-z][^>]*>", text):
            return True
        if re.search(r'\b[A-Z]{2,}\s*=\s*"[^"]*"', text):
            return True
        if text.count("<") + text.count(">") >= 2:
            return True
        if " VALIGN=" in text.upper() or " ALIGN=" in text.upper():
            return True
        if len(text) < 2:
            return True
        return False
