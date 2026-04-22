from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any


@dataclass(slots=True)
class DocumentTextExtractBuilder:
    def build(
        self,
        *,
        markup_fallback_inspection: dict[str, Any] | None,
        document_heading_candidates: dict[str, Any] | None,
    ) -> dict[str, Any]:
        heading_candidates = self._collect_heading_candidates(document_heading_candidates)
        plain_snippets = self._collect_plain_snippets(markup_fallback_inspection, heading_candidates)
        numeric_tokens = self._extract_tokens(
            plain_snippets,
            pattern=r"(?<!\w)\d{1,3}(?:,\d{3})*(?:\.\d+)?(?!\w)",
            max_items=10,
        )
        date_tokens = self._extract_tokens(
            plain_snippets,
            pattern=r"(?:19|20)\d{2}[./-]\d{1,2}[./-]\d{1,2}",
            max_items=10,
        )
        ratio_tokens = self._extract_tokens(
            plain_snippets,
            pattern=r"(?<!\w)\d{1,3}(?:\.\d+)?%",
            max_items=10,
        )

        table_labels = self._collect_table_adjacent_labels(markup_fallback_inspection)
        extraction_succeeded = len(heading_candidates) > 0 or len(plain_snippets) > 0

        if not extraction_succeeded:
            return {
                "extraction_attempted": True,
                "extraction_succeeded": False,
                "extracted_from": [],
                "heading_text_candidates": [],
                "plain_text_snippets": [],
                "table_adjacent_label_candidates": [],
                "token_candidates": {
                    "numeric_like": [],
                    "date_like": [],
                    "ratio_like": [],
                },
                "limitations": [
                    "안전하게 확정 가능한 짧은 텍스트를 찾지 못했습니다.",
                    "문서 구조/heading 후보가 없는 경우 추출을 건너뜁니다.",
                ],
            }

        extracted_from = []
        if heading_candidates:
            extracted_from.append("document_heading_candidates")
        if plain_snippets:
            extracted_from.append("markup_fallback_inspection.raw_excerpt_near_error")
        if table_labels:
            extracted_from.append("markup_fallback_inspection.first_opening_tags")

        return {
            "extraction_attempted": True,
            "extraction_succeeded": True,
            "extracted_from": extracted_from,
            "heading_text_candidates": heading_candidates[:10],
            "plain_text_snippets": plain_snippets[:5],
            "table_adjacent_label_candidates": table_labels[:5],
            "token_candidates": {
                "numeric_like": numeric_tokens,
                "date_like": date_tokens,
                "ratio_like": ratio_tokens,
            },
            "limitations": [
                "짧은 텍스트 조각만 제공하며 본문 전체 해석을 수행하지 않습니다.",
                "의미 해석/섹션 라벨링/투자 판단은 포함하지 않습니다.",
            ],
        }

    def _collect_heading_candidates(self, document_heading_candidates: dict[str, Any] | None) -> list[str]:
        if not isinstance(document_heading_candidates, dict):
            return []
        if not document_heading_candidates.get("extraction_succeeded"):
            return []
        texts = []
        for candidate in document_heading_candidates.get("heading_candidates", [])[:20]:
            if not isinstance(candidate, dict):
                continue
            text = self._normalize_text(candidate.get("text"))
            if text:
                texts.append(text)
        return self._deduplicate(texts)[:10]

    def _collect_plain_snippets(
        self,
        markup_fallback_inspection: dict[str, Any] | None,
        heading_candidates: list[str],
    ) -> list[str]:
        snippets = []
        if isinstance(markup_fallback_inspection, dict):
            excerpt = self._normalize_text(markup_fallback_inspection.get("raw_excerpt_near_error"))
            if excerpt:
                snippets.append(excerpt[:180])
        snippets.extend([text[:120] for text in heading_candidates[:5]])
        return self._deduplicate(snippets)

    def _collect_table_adjacent_labels(self, markup_fallback_inspection: dict[str, Any] | None) -> list[str]:
        if not isinstance(markup_fallback_inspection, dict):
            return []
        first_tags = markup_fallback_inspection.get("first_opening_tags", [])
        if not isinstance(first_tags, list):
            return []
        if not any(str(tag).lower() == "table" for tag in first_tags):
            return []
        labels = [self._normalize_text(tag) for tag in first_tags[:20] if self._normalize_text(tag)]
        return self._deduplicate(labels)

    def _extract_tokens(self, snippets: list[str], *, pattern: str, max_items: int) -> list[str]:
        joined = " ".join(snippets)
        if not joined:
            return []
        matches = [self._normalize_text(token) for token in re.findall(pattern, joined)]
        return self._deduplicate([token for token in matches if token])[:max_items]

    def _normalize_text(self, value: Any) -> str:
        text = str(value or "")
        return re.sub(r"\s+", " ", text).strip()

    def _deduplicate(self, items: list[str]) -> list[str]:
        seen: set[str] = set()
        result = []
        for item in items:
            if item in seen:
                continue
            seen.add(item)
            result.append(item)
        return result
