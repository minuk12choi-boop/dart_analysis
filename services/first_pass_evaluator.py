from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class FirstPassEvaluator:
    def evaluate(
        self,
        *,
        summary: dict[str, Any],
        normalized_items: list[dict[str, Any]],
    ) -> dict[str, Any]:
        total_disclosures = int(summary.get("total_disclosures", 0))
        category_counts: dict[str, int] = {
            key: int(value)
            for key, value in (summary.get("category_counts") or {}).items()
        }
        detected_signals: dict[str, int] = {
            key: int(value)
            for key, value in (summary.get("detected_signals") or {}).items()
        }

        risk_flags: list[dict[str, Any]] = []
        positive_flags: list[dict[str, Any]] = []
        neutral_flags: list[dict[str, Any]] = []
        notes: list[str] = [
            "현재 평가는 공시 목록 메타데이터(report_nm 등) 기반 1차 규칙 평가입니다.",
            "공시 본문 미파싱 상태이므로 사실 확정이 아닌 주의 신호 중심으로 해석해야 합니다.",
        ]

        financing_related = (
            detected_signals.get("rights_offering", 0)
            + detected_signals.get("convertible_bond", 0)
            + detected_signals.get("bond_with_warrant", 0)
        )
        if financing_related > 0:
            severity = "high" if financing_related >= 2 else "medium"
            risk_flags.append(
                {
                    "flag": "financing_related_signal",
                    "severity": severity,
                    "reason": "유상증자/전환사채/BW 관련 제목 기반 신호가 확인되었습니다.",
                    "evidence_count": financing_related,
                }
            )

        litigation_count = detected_signals.get("litigation", 0)
        legal_count = category_counts.get("legal_or_regulatory", 0)
        if litigation_count > 0 or legal_count > 0:
            risk_flags.append(
                {
                    "flag": "legal_or_regulatory_signal",
                    "severity": "high" if litigation_count > 0 else "medium",
                    "reason": "소송/법률·규제 관련 공시 제목 신호가 확인되었습니다.",
                    "evidence_count": max(litigation_count, legal_count),
                }
            )

        ownership_count = category_counts.get("ownership_or_major_shareholder", 0)
        owner_signal_count = detected_signals.get("major_shareholder_change", 0)
        if ownership_count > 0 or owner_signal_count > 0:
            risk_flags.append(
                {
                    "flag": "ownership_or_control_change_attention",
                    "severity": "medium",
                    "reason": "주요주주/지배구조 변동 관련 제목 기반 신호가 확인되었습니다.",
                    "evidence_count": max(ownership_count, owner_signal_count),
                }
            )

        supply_contract_count = detected_signals.get("supply_contract", 0)
        business_event_count = category_counts.get("contract_or_business", 0)
        if supply_contract_count > 0 or business_event_count > 0:
            positive_flags.append(
                {
                    "flag": "business_event_detected",
                    "severity": "low",
                    "reason": "공급계약/사업 관련 이벤트 공시가 확인되었습니다(최종 성과 판단 아님).",
                    "evidence_count": max(supply_contract_count, business_event_count),
                }
            )
            notes.append("계약/사업 이벤트는 후속 실적 반영 여부 확인이 필요합니다.")

        periodic_count = category_counts.get("periodic_report", 0)
        if periodic_count > 0 and not risk_flags and not positive_flags:
            neutral_flags.append(
                {
                    "flag": "periodic_reporting_only",
                    "severity": "low",
                    "reason": "현재 범위에서는 정기보고 성격의 정보성 공시가 중심입니다.",
                    "evidence_count": periodic_count,
                }
            )

        if total_disclosures == 0:
            neutral_flags.append(
                {
                    "flag": "no_recent_disclosures_in_window",
                    "severity": "low",
                    "reason": "조회 기간 내 확인된 공시가 없습니다.",
                    "evidence_count": 0,
                }
            )

        if not risk_flags and not positive_flags and not neutral_flags:
            neutral_flags.append(
                {
                    "flag": "insufficient_title_signals",
                    "severity": "low",
                    "reason": "제목 기반 규칙으로 분류 가능한 신호가 제한적입니다.",
                    "evidence_count": total_disclosures,
                }
            )

        return {
            "implemented": True,
            "basis": {
                "source": "disclosure_list_metadata_only",
                "fields": [
                    "report_nm",
                    "rcept_no",
                    "rcept_dt",
                    "corp_code",
                    "corp_name",
                    "stock_code",
                ],
                "total_disclosures": total_disclosures,
                "category_counts": category_counts,
                "detected_signals": detected_signals,
            },
            "risk_flags": risk_flags,
            "positive_flags": positive_flags,
            "neutral_flags": neutral_flags,
            "notes": notes,
            "evaluation_summary": self._build_summary(
                risk_flags=risk_flags,
                positive_flags=positive_flags,
                neutral_flags=neutral_flags,
            ),
        }

    def _build_summary(
        self,
        *,
        risk_flags: list[dict[str, Any]],
        positive_flags: list[dict[str, Any]],
        neutral_flags: list[dict[str, Any]],
    ) -> str:
        if risk_flags:
            return "제목 기반 1차 평가에서 주의가 필요한 리스크 신호가 확인되었습니다."
        if positive_flags:
            return "사업 이벤트 신호가 있으나 확정적 개선 판단은 보류해야 합니다."
        if neutral_flags:
            return "현재는 정보성/중립 신호가 중심이며 추가 근거 확인이 필요합니다."
        return "현재 1차 평가에서 의미 있는 신호를 확정하기 어렵습니다."
