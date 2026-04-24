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
        tone = "neutral"
        if any(signal in signals for signal in ["rights_offering", "convertible_bond", "bond_with_warrant", "litigation", "major_shareholder_change"]):
            tone = "cautionary"
        elif "supply_contract" in signals:
            tone = "positive"
        elif category in {"financing", "legal_or_regulatory", "ownership_or_major_shareholder"}:
            tone = "negative"

        plain = (
            f"이 공시는 '{report_nm or '제목 정보 없음'}'에 관한 내용입니다. "
            f"현재 확인된 분류는 '{category}'이며, 제목과 구조 단서로만 보수적으로 해석했습니다."
        )

        annotated_points = [
            {
                "label": "무엇에 대한 공시인가요?",
                "comment": f"제목 기준으로 {report_nm or '정보 없음'} 공시입니다.",
                "color": "green",
            },
            {
                "label": "왜 중요할까요?",
                "comment": f"감지 신호: {', '.join(signals) if signals else '없음'}",
                "color": "green",
            },
            {
                "label": "확인된 단서",
                "comment": f"heading 미리보기 {len(heading_preview)}건 / 텍스트 조각 {len(text_snippets)}건",
                "color": "green",
            },
        ]

        evidence_notes = [
            f"분류: {category}",
            f"신호: {', '.join(signals) if signals else '없음'}",
            f"heading: {heading_preview[:3]}",
            f"텍스트: {text_snippets[:2]}",
        ]

        limitations = [
            "본문 전체 의미 해석이 아닌 제목/구조/안전 추출 기반 설명입니다.",
            "확정적 투자 판단이나 매수·매도 권고를 제공하지 않습니다.",
        ]

        return {
            "plain_explanation": plain,
            "annotated_points": annotated_points,
            "tone_assessment": tone,
            "evidence_notes": evidence_notes,
            "limitations": limitations,
        }
