from __future__ import annotations

from dataclasses import dataclass
from typing import Any


_SIGNAL_DIRECTION_PRIORITY = {
    "insufficient_evidence": 0,
    "neutral": 1,
    "mixed": 2,
    "positive": 3,
    "negative": 4,
}


@dataclass(slots=True)
class DisclosureMeaningEvaluator:
    def evaluate(
        self,
        *,
        normalized_items: list[dict[str, Any]] | None,
        type_specific_analysis: dict[str, Any] | None,
        analysis: dict[str, Any] | None,
        report_preview: dict[str, Any] | None,
        document_structure_enrichment: dict[str, Any] | None,
    ) -> dict[str, Any]:
        safe_items = [item for item in (normalized_items or []) if isinstance(item, dict)]
        type_items = []
        if isinstance(type_specific_analysis, dict):
            type_items = [item for item in type_specific_analysis.get("items", []) if isinstance(item, dict)]
        type_map = {str(item.get("rcept_no") or ""): item for item in type_items if item.get("rcept_no")}

        enrichment_items = []
        if isinstance(document_structure_enrichment, dict):
            enrichment_items = [item for item in document_structure_enrichment.get("items", []) if isinstance(item, dict)]
        enrichment_map = {str(item.get("rcept_no") or ""): item for item in enrichment_items if item.get("rcept_no")}

        event_rows: list[dict[str, Any]] = []
        direction_counter = {
            "positive": 0,
            "negative": 0,
            "mixed": 0,
            "neutral": 0,
            "insufficient_evidence": 0,
        }

        for item in safe_items:
            row = self._evaluate_item(item=item, type_item=type_map.get(str(item.get("raw", {}).get("rcept_no") or ""), {}), enrich_item=enrichment_map.get(str(item.get("raw", {}).get("rcept_no") or ""), {}))
            direction_counter[row["signal_direction"]] += 1
            event_rows.append(row)

        aggregate_direction = self._aggregate_direction(direction_counter)
        confidence = self._confidence_level(total=len(event_rows), direction_counter=direction_counter)

        evidence: list[str] = []
        for row in event_rows[:10]:
            if row["evidence"]:
                evidence.extend(row["evidence"][:1])
        if isinstance(report_preview, dict):
            for note in report_preview.get("structure_notes", [])[:2]:
                evidence.append(f"구조 참고: {note}")

        return {
            "aggregate_signal_assessment": {
                "signal_direction": aggregate_direction,
                "confidence_level": confidence,
                "direction_counts": direction_counter,
                "considered_disclosure_count": len(event_rows),
            },
            "event_assessment": {
                "items": event_rows,
                "limitations": [
                    "공시 제목/정규화 신호/타입 규칙/제한적 구조 정보 기반의 보수적 판정입니다.",
                    "본문 전체 의미 해석이나 실적 확정 판단을 대신하지 않습니다.",
                ],
            },
            "key_evidence": evidence[:8],
            "caution_points": [
                "공급계약/사업 공시는 실제 실적 반영 여부를 후속 분기에서 재확인해야 합니다.",
                "자금조달/법률 신호는 단일 공시만으로 결론 내리지 말고 기간 내 반복 여부를 함께 확인해야 합니다.",
            ],
        }

    def _evaluate_item(self, *, item: dict[str, Any], type_item: dict[str, Any], enrich_item: dict[str, Any]) -> dict[str, Any]:
        raw = item.get("raw", {}) if isinstance(item.get("raw"), dict) else {}
        normalized = item.get("normalized", {}) if isinstance(item.get("normalized"), dict) else {}
        signals = normalized.get("detected_signals", []) if isinstance(normalized.get("detected_signals"), list) else []
        category = str(normalized.get("category") or "other")

        positive_hits = 0
        negative_hits = 0

        if "supply_contract" in signals:
            positive_hits += 1
        if "periodic_reporting" in signals:
            positive_hits += 0
        if any(signal in signals for signal in ["rights_offering", "convertible_bond", "bond_with_warrant", "litigation"]):
            negative_hits += 1

        if category in {"financing", "legal_or_regulatory"}:
            negative_hits += 1
        if category in {"contract_or_business", "treasury_share_or_shareholder_return"}:
            positive_hits += 1

        matched_rule = type_item.get("matched_type_rule")
        if matched_rule in {"rights_offering_or_capital_increase", "convertible_bond_or_bond_with_warrant"}:
            negative_hits += 1
        elif matched_rule == "supply_or_business_contract":
            positive_hits += 1

        if positive_hits == 0 and negative_hits == 0:
            direction = "insufficient_evidence"
            confidence = "low"
        elif positive_hits > 0 and negative_hits > 0:
            direction = "mixed"
            confidence = "medium"
        elif negative_hits > 0:
            direction = "negative"
            confidence = "medium" if negative_hits == 1 else "high"
        elif positive_hits > 0:
            direction = "positive"
            confidence = "medium" if positive_hits == 1 else "high"
        else:
            direction = "neutral"
            confidence = "low"

        evidence = [
            f"공시: {raw.get('report_nm') or '제목 정보 없음'} ({raw.get('rcept_dt') or '일자 미상'})",
            f"정규화 분류: {category}",
            f"탐지 신호: {', '.join(signals) if signals else '없음'}",
        ]
        if matched_rule:
            evidence.append(f"타입 규칙: {matched_rule}")
        if enrich_item:
            evidence.append(
                f"문서 구조 신호: {'가용' if enrich_item.get('document_outline_available') else '제한'} / heading 후보 {enrich_item.get('heading_candidate_count', 0)}건"
            )

        return {
            "rcept_no": raw.get("rcept_no"),
            "report_nm": raw.get("report_nm"),
            "rcept_dt": raw.get("rcept_dt"),
            "event_assessment": "보수적 공시 의미 판정",
            "signal_direction": direction,
            "confidence_level": confidence,
            "evidence": evidence,
            "limitations": [
                "공시 단건 기준 판단으로 확정적 투자의견이 아닙니다.",
            ],
        }

    def _aggregate_direction(self, direction_counter: dict[str, int]) -> str:
        positive = direction_counter.get("positive", 0)
        negative = direction_counter.get("negative", 0)
        mixed = direction_counter.get("mixed", 0)
        if positive == 0 and negative == 0 and mixed == 0:
            return "insufficient_evidence"
        if positive > 0 and negative > 0:
            return "mixed"
        if negative > 0:
            return "negative"
        if positive > 0:
            return "positive"
        if direction_counter.get("neutral", 0) > 0:
            return "neutral"
        return "insufficient_evidence"

    def _confidence_level(self, *, total: int, direction_counter: dict[str, int]) -> str:
        if total == 0:
            return "low"
        dominant = max(direction_counter.items(), key=lambda x: x[1])[0]
        dominant_count = direction_counter.get(dominant, 0)
        ratio = dominant_count / total
        if ratio >= 0.7 and total >= 3:
            return "high"
        if ratio >= 0.5:
            return "medium"
        return "low"
