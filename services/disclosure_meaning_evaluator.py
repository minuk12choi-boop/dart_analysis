from __future__ import annotations

from dataclasses import dataclass
from typing import Any


_DIRECTIONS = ["positive", "negative", "mixed", "neutral", "insufficient_evidence"]


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
        direction_counter = {direction: 0 for direction in _DIRECTIONS}
        weighted_counter = {direction: 0.0 for direction in _DIRECTIONS}

        for index, item in enumerate(safe_items):
            rcept_no = str((item.get("raw", {}) if isinstance(item.get("raw"), dict) else {}).get("rcept_no") or "")
            recency_weight = self._recency_weight(index)
            row = self._evaluate_item(
                item=item,
                type_item=type_map.get(rcept_no, {}),
                enrich_item=enrichment_map.get(rcept_no, {}),
                recency_weight=recency_weight,
            )
            direction = row["signal_direction"]
            direction_counter[direction] += 1
            weighted_counter[direction] += row["weighted_score"]
            event_rows.append(row)

        pattern_notes = self._pattern_adjustments(safe_items=safe_items)
        for note in pattern_notes:
            weighted_counter[note["direction"]] += note["weight"]

        aggregate_direction = self._aggregate_direction(weighted_counter=weighted_counter, direction_counter=direction_counter)
        confidence = self._confidence_level(weighted_counter=weighted_counter, direction=aggregate_direction)

        aggregate_evidence = [
            f"방향별 건수: {direction_counter}",
            f"가중 합계: { {k: round(v, 3) for k, v in weighted_counter.items()} }",
        ]
        aggregate_evidence.extend([note["evidence"] for note in pattern_notes])

        key_evidence: list[str] = []
        for row in event_rows[:10]:
            if row["evidence"]:
                key_evidence.extend(row["evidence"][:2])
        key_evidence.extend(aggregate_evidence[:2])
        if isinstance(report_preview, dict):
            for note in report_preview.get("structure_notes", [])[:2]:
                key_evidence.append(f"구조 참고: {note}")

        caution_points = [
            "공시 의미 판정은 제목/정규화/타입 규칙/제한적 구조 신호 기반의 보수적 해석입니다.",
            "상반 신호가 동시에 존재하면 mixed로 분류하며 단일 방향 결론을 보류합니다.",
            "가격 구간/시장 데이터는 별도 계층이며 공시 의미 판정과 분리해 해석해야 합니다.",
        ]

        return {
            "aggregate_signal_assessment": {
                "signal_direction": aggregate_direction,
                "confidence_level": confidence,
                "direction_counts": direction_counter,
                "weighted_direction_counts": {k: round(v, 3) for k, v in weighted_counter.items()},
                "considered_disclosure_count": len(event_rows),
                "meaning_engine_version": "v2_rule_weighted",
                "aggregate_evidence": aggregate_evidence[:6],
            },
            "event_assessment": {
                "items": event_rows,
                "limitations": [
                    "공시 제목/정규화 신호/타입 규칙/제한적 구조 정보 기반의 보수적 판정입니다.",
                    "본문 전체 의미 해석이나 실적 확정 판단을 대신하지 않습니다.",
                ],
            },
            "key_evidence": key_evidence[:10],
            "caution_points": caution_points,
        }

    def _evaluate_item(
        self,
        *,
        item: dict[str, Any],
        type_item: dict[str, Any],
        enrich_item: dict[str, Any],
        recency_weight: float,
    ) -> dict[str, Any]:
        raw = item.get("raw", {}) if isinstance(item.get("raw"), dict) else {}
        normalized = item.get("normalized", {}) if isinstance(item.get("normalized"), dict) else {}
        signals = normalized.get("detected_signals", []) if isinstance(normalized.get("detected_signals"), list) else []
        category = str(normalized.get("category") or "other")
        matched_rule = type_item.get("matched_type_rule")

        positive_score = 0.0
        negative_score = 0.0
        neutral_score = 0.0
        scoring_explanation: list[str] = []

        if category == "contract_or_business":
            positive_score += 1.0
            scoring_explanation.append("사업/계약 카테고리로 기본 긍정 가중치 +1.0")
        elif category in {"financing", "legal_or_regulatory"}:
            negative_score += 1.2
            scoring_explanation.append("자금조달/법률 카테고리로 기본 부정 가중치 +1.2")
        elif category == "periodic_report":
            neutral_score += 0.8
            scoring_explanation.append("정기보고 카테고리로 중립 가중치 +0.8")
        elif category == "ownership_or_major_shareholder":
            negative_score += 0.6
            scoring_explanation.append("지배구조 변동 카테고리로 보수적 주의 가중치 +0.6")

        for signal in signals:
            if signal in {"rights_offering", "convertible_bond", "bond_with_warrant", "litigation", "major_shareholder_change"}:
                negative_score += 1.3
                scoring_explanation.append(f"부정 성격 신호({signal})로 +1.3")
            elif signal == "supply_contract":
                positive_score += 1.2
                scoring_explanation.append("공급계약 신호로 +1.2")
            elif signal == "periodic_reporting":
                neutral_score += 0.5
                scoring_explanation.append("정기보고 신호로 중립 +0.5")

        if matched_rule in {"rights_offering_or_capital_increase", "convertible_bond_or_bond_with_warrant"}:
            negative_score += 1.4
            scoring_explanation.append(f"타입 규칙({matched_rule}) 부정 가중치 +1.4")
        elif matched_rule == "supply_or_business_contract":
            positive_score += 1.1
            scoring_explanation.append("타입 규칙(공급/사업계약) 긍정 가중치 +1.1")
        elif matched_rule == "periodic_report":
            neutral_score += 0.7
            scoring_explanation.append("타입 규칙(정기보고) 중립 가중치 +0.7")
        elif matched_rule == "ownership_or_major_shareholder_change":
            negative_score += 0.8
            scoring_explanation.append("타입 규칙(지배구조 변동) 주의 가중치 +0.8")

        structure_support = 0.0
        if enrich_item:
            if enrich_item.get("heading_candidates_available"):
                structure_support += 0.4
            if enrich_item.get("text_extract_preview", {}).get("available"):
                structure_support += 0.4
            if enrich_item.get("document_outline_available"):
                structure_support += 0.3
            if structure_support > 0:
                scoring_explanation.append(f"구조/텍스트 보조 근거 +{round(structure_support, 2)}")

        if positive_score > 0:
            positive_score += structure_support * 0.5
        if negative_score > 0:
            negative_score += structure_support * 0.5

        positive_weighted = positive_score * recency_weight
        negative_weighted = negative_score * recency_weight
        neutral_weighted = neutral_score * recency_weight

        direction, confidence = self._classify_direction(
            positive_weighted=positive_weighted,
            negative_weighted=negative_weighted,
            neutral_weighted=neutral_weighted,
        )

        evidence = [
            f"공시: {raw.get('report_nm') or '제목 정보 없음'} ({raw.get('rcept_dt') or '일자 미상'})",
            f"정규화 분류: {category}",
            f"탐지 신호: {', '.join(signals) if signals else '없음'}",
            f"타입 규칙: {matched_rule or '없음'}",
            f"가중치(최신성 포함): 긍정 {round(positive_weighted, 3)} / 부정 {round(negative_weighted, 3)} / 중립 {round(neutral_weighted, 3)}",
        ]
        if enrich_item:
            evidence.append(
                f"구조 보조: outline={bool(enrich_item.get('document_outline_available'))}, heading={bool(enrich_item.get('heading_candidates_available'))}"
            )

        weighted_score = max(positive_weighted, negative_weighted, neutral_weighted)
        if direction == "mixed":
            weighted_score = (positive_weighted + negative_weighted) / 2
        elif direction == "insufficient_evidence":
            weighted_score = 0.0

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
                "제목/구조 기반 신호이며 본문 의미 확정 해석이 아닙니다.",
            ],
            "scoring_explanation": scoring_explanation[:6],
            "weighted_score": round(weighted_score, 3),
        }

    def _classify_direction(self, *, positive_weighted: float, negative_weighted: float, neutral_weighted: float) -> tuple[str, str]:
        evidence_total = positive_weighted + negative_weighted + neutral_weighted
        if evidence_total < 0.8:
            return "insufficient_evidence", "low"

        diff = abs(positive_weighted - negative_weighted)
        if positive_weighted >= 1.0 and negative_weighted >= 1.0 and diff <= 0.8:
            return "mixed", "medium"
        if negative_weighted > positive_weighted and negative_weighted >= 1.2:
            return "negative", "high" if negative_weighted >= 2.4 else "medium"
        if positive_weighted > negative_weighted and positive_weighted >= 1.2:
            return "positive", "high" if positive_weighted >= 2.4 else "medium"
        if neutral_weighted >= 1.0 and positive_weighted < 1.0 and negative_weighted < 1.0:
            return "neutral", "medium"
        if positive_weighted > 0 and negative_weighted > 0:
            return "mixed", "low"
        return "insufficient_evidence", "low"

    def _aggregate_direction(self, *, weighted_counter: dict[str, float], direction_counter: dict[str, int]) -> str:
        positive = weighted_counter.get("positive", 0.0)
        negative = weighted_counter.get("negative", 0.0)
        neutral = weighted_counter.get("neutral", 0.0)
        mixed = weighted_counter.get("mixed", 0.0)

        if (positive + negative + neutral + mixed) < 1.2:
            return "insufficient_evidence"
        if positive >= 1.0 and negative >= 1.0 and abs(positive - negative) <= 1.0:
            return "mixed"
        if negative > positive and negative >= 1.4:
            return "negative"
        if positive > negative and positive >= 1.4:
            return "positive"
        if neutral >= 1.2 and direction_counter.get("insufficient_evidence", 0) < max(1, direction_counter.get("neutral", 0)):
            return "neutral"
        if positive > 0 and negative > 0:
            return "mixed"
        return "insufficient_evidence"

    def _confidence_level(self, *, weighted_counter: dict[str, float], direction: str) -> str:
        if direction == "insufficient_evidence":
            return "low"
        dominant = weighted_counter.get(direction, 0.0)
        total = sum(weighted_counter.values())
        if total <= 0:
            return "low"
        ratio = dominant / total
        if ratio >= 0.65 and dominant >= 2.0:
            return "high"
        if ratio >= 0.45:
            return "medium"
        return "low"

    def _pattern_adjustments(self, *, safe_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        signal_counts: dict[str, int] = {}
        for item in safe_items:
            normalized = item.get("normalized", {}) if isinstance(item.get("normalized"), dict) else {}
            signals = normalized.get("detected_signals", []) if isinstance(normalized.get("detected_signals"), list) else []
            for signal in signals:
                signal_counts[signal] = signal_counts.get(signal, 0) + 1

        notes: list[dict[str, Any]] = []
        financing_repeat = sum(signal_counts.get(name, 0) for name in ["rights_offering", "convertible_bond", "bond_with_warrant"])
        if financing_repeat >= 2:
            notes.append(
                {
                    "direction": "negative",
                    "weight": 0.8,
                    "evidence": f"반복 자금조달 신호 {financing_repeat}건으로 집계 부정 가중치 +0.8",
                }
            )

        ownership_repeat = signal_counts.get("major_shareholder_change", 0)
        if ownership_repeat >= 2:
            notes.append(
                {
                    "direction": "negative",
                    "weight": 0.5,
                    "evidence": f"반복 지배구조 변동 신호 {ownership_repeat}건으로 주의 가중치 +0.5",
                }
            )

        contract_repeat = signal_counts.get("supply_contract", 0)
        if contract_repeat >= 2 and financing_repeat == 0:
            notes.append(
                {
                    "direction": "positive",
                    "weight": 0.5,
                    "evidence": f"반복 공급계약 신호 {contract_repeat}건으로 제한적 긍정 가중치 +0.5",
                }
            )

        return notes

    def _recency_weight(self, index: int) -> float:
        if index <= 1:
            return 1.0
        if index <= 3:
            return 0.9
        if index <= 5:
            return 0.8
        return 0.7
