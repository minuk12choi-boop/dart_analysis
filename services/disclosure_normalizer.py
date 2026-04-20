from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any


CATEGORY_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("periodic_report", ("사업보고서", "분기보고서", "반기보고서")),
    ("financing", ("유상증자", "전환사채", "신주인수권부사채", "교환사채", "자금조달", "채권발행")),
    ("ownership_or_major_shareholder", ("최대주주", "주요주주", "대량보유")),
    ("governance", ("임원", "이사", "감사", "주주총회", "정관")),
    ("legal_or_regulatory", ("소송", "횡령", "배임", "거래정지", "회생", "검찰")),
    ("contract_or_business", ("공급계약", "단일판매", "투자", "시설", "영업양수도", "신규사업")),
    ("treasury_share_or_shareholder_return", ("자기주식", "자사주", "배당", "소각")),
]

SIGNAL_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("periodic_reporting", ("사업보고서", "분기보고서", "반기보고서")),
    ("rights_offering", ("유상증자",)),
    ("convertible_bond", ("전환사채",)),
    ("bond_with_warrant", ("신주인수권부사채",)),
    ("major_shareholder_change", ("최대주주", "주요주주", "대량보유")),
    ("litigation", ("소송",)),
    ("supply_contract", ("공급계약", "단일판매")),
]


@dataclass(slots=True)
class DisclosureNormalizer:
    def normalize_items(self, raw_items: list[dict[str, Any]]) -> dict[str, Any]:
        normalized_items: list[dict[str, Any]] = []
        category_counter: Counter[str] = Counter()
        signal_counter: Counter[str] = Counter()

        for item in raw_items:
            report_nm = (item.get("report_nm") or "").strip()
            category = self.classify_category(report_nm)
            signals = self.detect_signals(report_nm)

            normalized_item = {
                "raw": {
                    "rcept_no": item.get("rcept_no"),
                    "report_nm": item.get("report_nm"),
                    "rcept_dt": item.get("rcept_dt"),
                    "corp_code": item.get("corp_code"),
                    "corp_name": item.get("corp_name"),
                    "stock_code": item.get("stock_code"),
                },
                "normalized": {
                    "category": category,
                    "detected_signals": signals,
                },
            }
            normalized_items.append(normalized_item)
            category_counter[category] += 1
            for signal in signals:
                signal_counter[signal] += 1

        return {
            "items": normalized_items,
            "summary": {
                "total_disclosures": len(normalized_items),
                "category_counts": dict(category_counter),
                "detected_signals": dict(signal_counter),
            },
        }

    def classify_category(self, report_nm: str) -> str:
        for category, keywords in CATEGORY_RULES:
            if any(keyword in report_nm for keyword in keywords):
                return category
        return "other"

    def detect_signals(self, report_nm: str) -> list[str]:
        detected: list[str] = []
        for signal, keywords in SIGNAL_RULES:
            if any(keyword in report_nm for keyword in keywords):
                detected.append(signal)
        return detected
