from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class DocumentHeadingCandidatesBuilder:
    def build(self, markup_fallback_inspection: dict[str, Any] | None) -> dict[str, Any] | None:
        if markup_fallback_inspection is None:
            return None

        attempted = bool(markup_fallback_inspection.get("markup_fallback_attempted"))
        succeeded = bool(markup_fallback_inspection.get("markup_fallback_succeeded"))
        heading_like_tag_names_used = list(markup_fallback_inspection.get("heading_like_tag_names_used", []))
        raw_candidates = list(markup_fallback_inspection.get("heading_candidates", []))

        if not attempted:
            return {
                "extraction_attempted": False,
                "extraction_succeeded": False,
                "reason": "markup fallback이 시도되지 않았습니다.",
                "heading_like_tag_names_used": [],
                "heading_candidates": [],
                "heading_candidate_count": 0,
                "deduplicated_heading_candidate_count": 0,
            }

        if not succeeded:
            return {
                "extraction_attempted": True,
                "extraction_succeeded": False,
                "reason": "markup fallback이 실패하여 heading 후보를 추출하지 못했습니다.",
                "heading_like_tag_names_used": heading_like_tag_names_used,
                "heading_candidates": [],
                "heading_candidate_count": 0,
                "deduplicated_heading_candidate_count": 0,
            }

        normalized_candidates: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for item in raw_candidates[:30]:
            source_tag = str(item.get("source_tag", "")).strip()
            text = str(item.get("text", "")).strip()
            if not source_tag or not text:
                continue
            key = (source_tag, text)
            if key in seen:
                continue
            seen.add(key)
            normalized_candidates.append(
                {
                    "source_tag": source_tag,
                    "text": text,
                    "text_length": len(text),
                }
            )

        return {
            "extraction_attempted": True,
            "extraction_succeeded": True,
            "derived_from": "markup_fallback_inspection",
            "heading_like_tag_names_used": heading_like_tag_names_used,
            "heading_candidates": normalized_candidates,
            "heading_candidate_count": len(raw_candidates),
            "deduplicated_heading_candidate_count": len(normalized_candidates),
        }
