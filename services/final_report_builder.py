from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class FinalReportBuilder:
    card_limit: int = 3

    def build(self, *, validate_payload: dict[str, Any], validate_status_code: int) -> dict[str, Any]:
        request_block = validate_payload.get("input", {})
        analysis = validate_payload.get("analysis", {})
        disclosures_data = validate_payload.get("disclosures", {}).get("data", {})
        summary = disclosures_data.get("summary", {}) if isinstance(disclosures_data, dict) else {}
        normalized_items = disclosures_data.get("normalized_items", []) if isinstance(disclosures_data, dict) else []
        enrichment = disclosures_data.get("document_structure_enrichment", {}) if isinstance(disclosures_data, dict) else {}
        report_preview = validate_payload.get("report_preview", {})
        type_specific_analysis = validate_payload.get("type_specific_analysis", {})
        type_specific_summary = validate_payload.get("type_specific_summary", {})

        type_item_map = {
            str(item.get("rcept_no")): item
            for item in type_specific_analysis.get("items", [])
            if isinstance(item, dict) and item.get("rcept_no")
        } if isinstance(type_specific_analysis, dict) else {}
        enrichment_item_map = {
            str(item.get("rcept_no")): item
            for item in enrichment.get("items", [])
            if isinstance(item, dict) and item.get("rcept_no")
        } if isinstance(enrichment, dict) else {}

        cards = []
        for item in normalized_items[: self.card_limit]:
            if not isinstance(item, dict):
                continue
            raw = item.get("raw", {}) if isinstance(item.get("raw"), dict) else {}
            normalized = item.get("normalized", {}) if isinstance(item.get("normalized"), dict) else {}
            rcept_no = str(raw.get("rcept_no") or "")
            type_item = type_item_map.get(rcept_no, {})
            enrich_item = enrichment_item_map.get(rcept_no, {})
            cards.append(
                {
                    "rcept_no": raw.get("rcept_no"),
                    "report_nm": raw.get("report_nm"),
                    "rcept_dt": raw.get("rcept_dt"),
                    "normalized_category": normalized.get("category"),
                    "detected_signals": normalized.get("detected_signals", []),
                    "type_specific_matched_rule": type_item.get("matched_type_rule"),
                    "type_specific_facts": type_item.get("type_specific_facts", [])[:3],
                    "type_specific_hints": type_item.get("type_specific_hints", [])[:3],
                    "heading_preview": enrich_item.get("heading_candidates_preview", [])[:3],
                    "structure_hint_preview": enrich_item.get("text_extract_preview", {}).get("plain_text_snippets", [])[:2],
                }
            )

        report_status = {
            "code": "ok",
            "source_validate_status_code": validate_status_code,
            "message": "검증된 구조 데이터 기반으로 보고서가 생성되었습니다.",
        }
        if validate_status_code == 502:
            report_status = {
                "code": "partial_failure",
                "source_validate_status_code": validate_status_code,
                "message": "업스트림 일부 실패가 있었으나 가능한 구조 데이터로 보고서를 생성했습니다.",
            }
        elif validate_status_code >= 400 and validate_status_code != 502:
            report_status = {
                "code": "error",
                "source_validate_status_code": validate_status_code,
                "message": "입력 또는 해석 실패로 보고서 생성 범위가 제한되었습니다.",
            }

        return {
            "request": request_block,
            "report_meta": {
                "version": "v1",
                "built_from": "validate_response",
                "card_limit": self.card_limit,
                "total_disclosures": summary.get("total_disclosures", 0),
                "category_counts": summary.get("category_counts", {}),
            },
            "executive_summary": {
                "summary_line": report_preview.get("summary_line"),
                "evaluation_summary": analysis.get("evaluation_summary"),
            },
            "key_findings": report_preview.get("key_points", []),
            "caution_findings": report_preview.get("caution_points", []),
            "structure_findings": report_preview.get("structure_notes", []),
            "disclosure_cards": cards,
            "limitations": [
                "이 보고서는 이미 생성된 validate 구조 결과를 재구성한 소비자용 JSON입니다.",
                "본문 의미 해석/투자 추천/매수·매도 판단은 포함하지 않습니다.",
            ],
            "status": report_status,
            "upstream_status": validate_payload.get("upstream_status"),
            "cache_status": validate_payload.get("cache_status"),
            "type_specific_summary": type_specific_summary if isinstance(type_specific_summary, dict) else {},
        }
