from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class DisclosureExplanationBuilder:
    def build(
        self,
        *,
        report_nm: str,
        category: str,
        detected_signals: list[str],
        heading_preview: list[str],
        text_snippets: list[str],
    ) -> dict[str, Any]:
        signals = detected_signals or []
        tone = "중립"
        tone_reason = "제목/구조 단서만으로는 방향성을 확정하기 어렵습니다."
        if any(signal in signals for signal in ["rights_offering", "convertible_bond", "bond_with_warrant", "litigation", "major_shareholder_change"]):
            tone = "주의"
            tone_reason = "희석/법률/지배구조 관련 신호가 포함되어 보수적 해석이 필요합니다."
        elif "supply_contract" in signals:
            tone = "관찰 필요"
            tone_reason = "계약 공시는 존재하나 실제 실적 반영 여부는 후속 분기 확인이 필요합니다."

        plain = (
            f"'{report_nm or '제목 정보 없음'}' 공시를 구조 단서 중심으로 해석했습니다. "
            f"현재 분류는 '{category or 'other'}'이며, 본문 전체 의미 파싱이 아니므로 과대해석을 피해야 합니다."
        )

        annotated_points = [
            {
                "label": "공시 성격",
                "comment": f"공시 분류는 '{category or 'other'}'로 분류되었습니다.",
                "color": "green",
            },
            {
                "label": "핵심 신호",
                "comment": f"감지 신호: {', '.join(signals) if signals else '없음'}",
                "color": "green",
            },
            {
                "label": "구조 단서 범위",
                "comment": f"heading {len(heading_preview)}건 / 텍스트 조각 {len(text_snippets)}건을 근거로 요약했습니다.",
                "color": "green",
            },
        ]

        evidence_groups = {
            "heading_evidence": heading_preview[:5],
            "text_evidence": text_snippets[:5],
            "signal_evidence": signals,
        }

        limitations = [
            "원문 전체 문맥 해석이 아닌 제목/구조/안전 텍스트 추출 기반 설명입니다.",
            "수치·계약 규모·법적 쟁점의 정밀 검토는 원문 전문 확인이 필요합니다.",
            "매수·매도 같은 확정적 투자 권고를 제공하지 않습니다.",
        ]

        return {
            "plain_explanation": plain,
            "annotated_points": annotated_points,
            "tone_assessment": {"label": tone, "reason": tone_reason},
            "evidence_notes": [
                f"분류: {category or 'other'}",
                f"신호: {', '.join(signals) if signals else '없음'}",
            ],
            "evidence_groups": evidence_groups,
            "limitations": limitations,
        }
