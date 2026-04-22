from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.env import get_env_float
import os


@dataclass(slots=True)
class MarketDataProvider:
    provider_name: str = "none"

    @classmethod
    def from_env(cls) -> "MarketDataProvider":
        provider_name = (os.getenv("DART_MARKET_DATA_PROVIDER", "none") or "none").strip().lower()
        return cls(provider_name=provider_name or "none")

    def fetch_snapshot(self, *, corp_code: str | None, stock_code: str | None) -> dict[str, Any]:
        if self.provider_name != "static":
            return {
                "provider": self.provider_name,
                "available": False,
                "insufficient_market_data": True,
                "unavailable_fields": [
                    "current_price",
                    "recent_low",
                    "recent_high",
                    "recent_volume",
                    "volatility_proxy",
                    "market_cap",
                    "share_count",
                ],
                "data": {},
                "message": "시장 데이터 공급자가 설정되지 않아 가격 판단을 제한합니다.",
                "lookup": {"corp_code": corp_code, "stock_code": stock_code},
            }

        current_price = get_env_float("DART_MARKET_PRICE_CURRENT", -1.0)
        recent_low = get_env_float("DART_MARKET_PRICE_RECENT_LOW", -1.0)
        recent_high = get_env_float("DART_MARKET_PRICE_RECENT_HIGH", -1.0)
        recent_volume = get_env_float("DART_MARKET_RECENT_VOLUME", -1.0)
        volatility_proxy = get_env_float("DART_MARKET_VOLATILITY_PROXY", -1.0)
        market_cap = get_env_float("DART_MARKET_CAP", -1.0)
        share_count = get_env_float("DART_MARKET_SHARE_COUNT", -1.0)

        values = {
            "current_price": current_price if current_price > 0 else None,
            "recent_low": recent_low if recent_low > 0 else None,
            "recent_high": recent_high if recent_high > 0 else None,
            "recent_volume": recent_volume if recent_volume > 0 else None,
            "volatility_proxy": volatility_proxy if volatility_proxy > 0 else None,
            "market_cap": market_cap if market_cap > 0 else None,
            "share_count": share_count if share_count > 0 else None,
        }

        unavailable_fields = [key for key, value in values.items() if value is None]
        insufficient = len(unavailable_fields) > 0

        return {
            "provider": "static",
            "available": not insufficient,
            "insufficient_market_data": insufficient,
            "unavailable_fields": unavailable_fields,
            "data": values,
            "message": "환경변수 기반 정적 시장 데이터 스냅샷을 사용합니다.",
            "lookup": {"corp_code": corp_code, "stock_code": stock_code},
        }
