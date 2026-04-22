from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class PriceAssessmentEngine:
    def build(
        self,
        *,
        market_data_status: dict[str, Any],
        aggregate_signal_direction: str,
    ) -> dict[str, Any]:
        if market_data_status.get("insufficient_market_data", True):
            return {
                "price_assessment_status": "insufficient_market_data",
                "pricing_method": "none",
                "entry_zone": None,
                "exit_zone": None,
                "risk_cut_zone": None,
                "pricing_limitations": [
                    "시장 데이터가 부족해 가격 구간을 산출하지 않았습니다.",
                    "임의 추정 가격은 제공하지 않습니다.",
                ],
            }

        data = market_data_status.get("data", {}) if isinstance(market_data_status.get("data"), dict) else {}
        recent_low = data.get("recent_low")
        recent_high = data.get("recent_high")
        current_price = data.get("current_price")
        if not all(isinstance(v, (int, float)) and v > 0 for v in [recent_low, recent_high, current_price]):
            return {
                "price_assessment_status": "insufficient_market_data",
                "pricing_method": "none",
                "entry_zone": None,
                "exit_zone": None,
                "risk_cut_zone": None,
                "pricing_limitations": [
                    "가격/범위 입력값이 불완전해 구간 산출을 중단했습니다.",
                ],
            }

        if recent_high <= recent_low:
            return {
                "price_assessment_status": "insufficient_market_data",
                "pricing_method": "none",
                "entry_zone": None,
                "exit_zone": None,
                "risk_cut_zone": None,
                "pricing_limitations": [
                    "최근 고가/저가 관계가 유효하지 않아 구간 산출을 중단했습니다.",
                ],
            }

        band = recent_high - recent_low
        volatility_proxy = data.get("volatility_proxy")
        adjustment = 1.0
        pricing_method = "recent_range_based_heuristic"
        if isinstance(volatility_proxy, (int, float)) and volatility_proxy > 0:
            pricing_method = "volatility_aware_recent_range_heuristic"
            adjustment = min(1.3, max(0.7, 1.0 + (volatility_proxy - 0.03)))

        band = band * adjustment
        entry_low = round(recent_low + band * 0.1, 2)
        entry_high = round(recent_low + band * 0.3, 2)
        exit_low = round(recent_low + band * 0.7, 2)
        exit_high = round(recent_high, 2)
        risk_cut = round(recent_low - band * 0.05, 2)

        if aggregate_signal_direction == "negative":
            entry_low = round(recent_low, 2)
            entry_high = round(recent_low + band * 0.15, 2)
            exit_low = round(recent_low + band * 0.45, 2)
            exit_high = round(recent_low + band * 0.6, 2)

        return {
            "price_assessment_status": "estimated_with_market_data",
            "pricing_method": pricing_method,
            "entry_zone": {
                "min": entry_low,
                "max": entry_high,
                "basis": "최근 저가~고가 구간 하단 비중",
            },
            "exit_zone": {
                "min": exit_low,
                "max": exit_high,
                "basis": "최근 저가~고가 구간 상단 비중",
            },
            "risk_cut_zone": {
                "value": risk_cut,
                "basis": "최근 저가 하향 이탈 보수 기준",
            },
            "pricing_limitations": [
                "이 구간은 최근 범위 기반 휴리스틱이며 내재가치 평가가 아닙니다.",
                "공시 이벤트 후 실제 변동성 확대 시 재산출이 필요합니다.",
            ],
        }
