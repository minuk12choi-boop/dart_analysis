from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from services.report_preview_quality_filter import ReportPreviewQualityFilter


@dataclass(slots=True)
class FinalReportBuilder:
    card_limit: int = 3
    preview_quality_filter: ReportPreviewQualityFilter = field(default_factory=ReportPreviewQualityFilter)

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
            heading_preview, heading_quality = self.preview_quality_filter.filter_values(
                [str(value) for value in enrich_item.get("heading_candidates_preview", [])[:3]]
            )
            structure_hint_preview, structure_quality = self.preview_quality_filter.filter_values(
                [str(value) for value in enrich_item.get("text_extract_preview", {}).get("plain_text_snippets", [])[:2]]
            )
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
                    "heading_preview": heading_preview,
                    "structure_hint_preview": structure_hint_preview,
                    "preview_quality": {
                        "heading_preview": heading_quality,
                        "structure_hint_preview": structure_quality,
                    },
                }
            )

        report_status = {
            "code": "ok",
            "source_validate_status_code": validate_status_code,
            "message": "조회된 공시를 바탕으로 소비자용 요약 리포트를 생성했습니다.",
        }
        if validate_status_code == 502:
            report_status = {
                "code": "partial_failure",
                "source_validate_status_code": validate_status_code,
                "message": "일부 조회에 실패했지만 확보된 데이터 범위에서 리포트를 생성했습니다.",
            }
        elif validate_status_code >= 400 and validate_status_code != 502:
            report_status = {
                "code": "error",
                "source_validate_status_code": validate_status_code,
                "message": "입력값 또는 조회 상태로 인해 리포트 생성 범위가 제한되었습니다.",
            }

        return {
            "request": request_block,
            "report_meta": {
                "version": "v1",
                "built_from": "validate_response",
                "card_limit": self.card_limit,
                "total_disclosures": summary.get("total_disclosures", 0),
                "category_counts": summary.get("category_counts", {}),
                "naming_policy": "stable_v1",
                "field_aliases": {
                    "executive_summary.summary_text": "executive_summary.summary_line",
                    "findings.key": "key_findings",
                    "findings.caution": "caution_findings",
                    "findings.structure": "structure_findings",
                },
            },
            "executive_summary": {
                "summary_line": report_preview.get("summary_line"),
                "summary_text": report_preview.get("summary_line"),
                "evaluation_summary": analysis.get("evaluation_summary"),
            },
            "key_findings": report_preview.get("key_points", []),
            "caution_findings": report_preview.get("caution_points", []),
            "structure_findings": report_preview.get("structure_notes", []),
            "findings": {
                "key": report_preview.get("key_points", []),
                "caution": report_preview.get("caution_points", []),
                "structure": report_preview.get("structure_notes", []),
            },
            "disclosure_cards": cards,
            "limitations": [
                "이 보고서는 validate 결과를 재구성한 소비자용 요약 JSON입니다.",
                "본문 의미 해석, 투자 추천, 매수·매도 판단은 포함하지 않습니다.",
                "공시 원문 검토를 대체하지 않으며, 최종 판단 전 원문 확인이 필요합니다.",
            ],
            "status": report_status,
            "upstream_status": validate_payload.get("upstream_status"),
            "cache_status": validate_payload.get("cache_status"),
            "type_specific_summary": type_specific_summary if isinstance(type_specific_summary, dict) else {},
        }
