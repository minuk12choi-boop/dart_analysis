from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class TypeSpecificAnalyzer:
    def analyze(
        self,
        *,
        normalized_items: list[dict[str, Any]] | None,
        document_structure_enrichment: dict[str, Any] | None,
    ) -> dict[str, Any]:
        safe_items = [item for item in (normalized_items or []) if isinstance(item, dict)]
        enrichment_items = []
        if isinstance(document_structure_enrichment, dict):
            enrichment_items = [item for item in document_structure_enrichment.get("items", []) if isinstance(item, dict)]
        enrichment_map = {str(item.get("rcept_no")): item for item in enrichment_items if item.get("rcept_no")}

        analysis_items = [self._analyze_item(item, enrichment_map) for item in safe_items]
        supported_count = sum(1 for item in analysis_items if item.get("status") == "supported")

        rule_counts: dict[str, int] = {}
        for item in analysis_items:
            matched_rule = item.get("matched_type_rule")
            if isinstance(matched_rule, str):
                rule_counts[matched_rule] = rule_counts.get(matched_rule, 0) + 1

        return {
            "type_specific_analysis": {
                "available": True,
                "supported_type_rules": [
                    "rights_offering_or_capital_increase",
                    "convertible_bond_or_bond_with_warrant",
                    "ownership_or_major_shareholder_change",
                    "supply_or_business_contract",
                    "periodic_report",
                ],
                "items": analysis_items,
                "limitations": [
                    "제목/정규화 분류/문서 구조 신호만 사용한 1차 타입별 규칙입니다.",
                    "본문 의미 해석 및 투자 판단을 포함하지 않습니다.",
                ],
            },
            "type_specific_summary": {
                "available": True,
                "total_items": len(analysis_items),
                "supported_items": supported_count,
                "not_applicable_items": len(analysis_items) - supported_count,
                "matched_rule_counts": rule_counts,
            },
        }

    def _analyze_item(self, item: dict[str, Any], enrichment_map: dict[str, dict[str, Any]]) -> dict[str, Any]:
        raw = item.get("raw", {}) if isinstance(item.get("raw"), dict) else {}
        normalized = item.get("normalized", {}) if isinstance(item.get("normalized"), dict) else {}
        detected_signals = normalized.get("detected_signals", [])
        if not isinstance(detected_signals, list):
            detected_signals = []

        report_nm = str(raw.get("report_nm") or "")
        category = normalized.get("category")
        rcept_no = str(raw.get("rcept_no") or "")
        enrichment = enrichment_map.get(rcept_no, {})

        matched_rule = self._match_rule(
            report_nm=report_nm,
            category=category,
            detected_signals=detected_signals,
        )

        if not matched_rule:
            return {
                "rcept_no": raw.get("rcept_no"),
                "report_nm": raw.get("report_nm"),
                "rcept_dt": raw.get("rcept_dt"),
                "normalized_category": category,
                "status": "not_applicable",
                "matched_type_rule": None,
                "type_specific_facts": [],
                "type_specific_hints": [],
                "limitations": ["현재 1차 타입별 규칙 대상에 포함되지 않은 공시 유형입니다."],
            }

        facts = [
            f"매칭된 타입 규칙: {matched_rule}",
            f"제목 기반 신호: {', '.join(detected_signals) if detected_signals else '없음'}",
            f"문서 구조 가용 여부: {'예' if enrichment.get('document_outline_available') else '아니오'}",
            f"heading 후보 가용 여부: {'예' if enrichment.get('heading_candidates_available') else '아니오'}",
        ]
        hints = self._build_hints(
            matched_rule=matched_rule,
            report_nm=report_nm,
            detected_signals=detected_signals,
            enrichment=enrichment,
        )

        return {
            "rcept_no": raw.get("rcept_no"),
            "report_nm": raw.get("report_nm"),
            "rcept_dt": raw.get("rcept_dt"),
            "normalized_category": category,
            "status": "supported",
            "matched_type_rule": matched_rule,
            "type_specific_facts": facts,
            "type_specific_hints": hints,
            "limitations": [
                "타입별 결과는 제목/구조 기반의 보수적 참고 정보입니다.",
                "본문 의미 해석 및 투자 판단으로 사용할 수 없습니다.",
            ],
        }

    def _match_rule(self, *, report_nm: str, category: Any, detected_signals: list[str]) -> str | None:
        if "rights_offering" in detected_signals or "유상증자" in report_nm:
            return "rights_offering_or_capital_increase"
        if "convertible_bond" in detected_signals or "bond_with_warrant" in detected_signals:
            return "convertible_bond_or_bond_with_warrant"
        if (
            category == "ownership_or_major_shareholder"
            or "major_shareholder_change" in detected_signals
            or "최대주주" in report_nm
            or "주요주주" in report_nm
        ):
            return "ownership_or_major_shareholder_change"
        if (
            "supply_contract" in detected_signals
            or category == "contract_or_business"
            and any(keyword in report_nm for keyword in ("공급계약", "단일판매", "계약"))
        ):
            return "supply_or_business_contract"
        if category == "periodic_report" or "periodic_reporting" in detected_signals:
            return "periodic_report"
        return None

    def _build_hints(
        self,
        *,
        matched_rule: str,
        report_nm: str,
        detected_signals: list[str],
        enrichment: dict[str, Any],
    ) -> list[str]:
        hints = [f"제목 확인: {report_nm}"]

        if matched_rule == "ownership_or_major_shareholder_change":
            hints.append("지분/주주 변동 관련 제목 신호 존재 여부를 우선 확인하세요.")
        elif matched_rule == "supply_or_business_contract":
            hints.append("계약 관련 공시는 후속 실적 반영 여부를 별도 확인해야 합니다.")
        elif matched_rule == "periodic_report":
            hints.append("정기보고서 유형으로 분류되어 재무/사업 항목의 후속 정량 검토 대상입니다.")
        elif matched_rule in {"rights_offering_or_capital_increase", "convertible_bond_or_bond_with_warrant"}:
            hints.append("자금조달 관련 제목 신호로 분류되며, 추가 공시 추적이 필요할 수 있습니다.")

        if detected_signals:
            hints.append(f"탐지 신호 목록: {', '.join(detected_signals)}")

        if enrichment:
            heading_count = enrichment.get("heading_candidate_count", 0)
            hints.append(f"heading 후보 수(제한적): {heading_count}")
        else:
            hints.append("문서 구조 enrichment가 없어 제목 기반 정보만 제공됩니다.")

        return hints
