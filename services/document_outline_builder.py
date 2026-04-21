from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class DocumentOutlineBuilder:
    def build(self, markup_fallback_inspection: dict[str, Any] | None) -> dict[str, Any] | None:
        if markup_fallback_inspection is None:
            return None

        if not markup_fallback_inspection.get("markup_fallback_attempted"):
            return {
                "outline_available": False,
                "reason": "markup fallback이 시도되지 않았습니다.",
            }

        if not markup_fallback_inspection.get("markup_fallback_succeeded"):
            return {
                "outline_available": False,
                "reason": "markup fallback이 실패하여 구조 요약을 생성하지 못했습니다.",
            }

        first_unique_tag_names = list(markup_fallback_inspection.get("first_unique_tag_names", []))
        first_opening_tags = list(markup_fallback_inspection.get("first_opening_tags", []))
        shallow_tag_sequence = list(markup_fallback_inspection.get("shallow_tag_sequence", []))
        tag_counts = dict(markup_fallback_inspection.get("tag_counts", {}))

        section_tag_names = sorted([tag for tag in tag_counts.keys() if tag.startswith("section-")])
        section_tag_total_count = sum(tag_counts.get(tag, 0) for tag in section_tag_names)
        table_like_tag_total_count = sum(
            tag_counts.get(tag, 0) for tag in ["table", "table-group", "tbody", "thead", "tr", "td", "th", "colgroup", "col"]
        )
        paragraph_like_tag_total_count = sum(tag_counts.get(tag, 0) for tag in ["p", "tu", "te"])

        return {
            "outline_available": True,
            "derived_from": "markup_fallback_inspection",
            "has_body": "body" in tag_counts,
            "has_cover": "cover" in tag_counts or "cover-title" in tag_counts,
            "has_summary": "summary" in tag_counts,
            "has_title_tags": "title" in tag_counts or "cover-title" in tag_counts,
            "section_tag_names": section_tag_names,
            "section_tag_total_count": section_tag_total_count,
            "table_like_tag_total_count": table_like_tag_total_count,
            "paragraph_like_tag_total_count": paragraph_like_tag_total_count,
            "tag_counts": tag_counts,
            "first_unique_tag_names": first_unique_tag_names,
            "first_opening_tags": first_opening_tags,
            "shallow_tag_sequence": shallow_tag_sequence,
        }
