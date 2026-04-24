from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class MarketChartBuilder:
    """시장 스냅샷의 일봉 데이터를 기반으로 차트용 구조 데이터를 생성한다."""

    def build(self, *, market_data_status: dict[str, Any]) -> dict[str, Any]:
        raw_series = market_data_status.get("data", {}).get("recent_daily_series", []) if isinstance(market_data_status.get("data"), dict) else []
        daily_points = self._normalize_daily_series(raw_series)

        monthly_points = self._aggregate_by_period(daily_points, period="month")
        yearly_points = self._aggregate_by_period(daily_points, period="year")

        timeframe_map = {
            "일봉": self._build_available_block("day", daily_points),
            "월봉": self._build_available_block("month", monthly_points),
            "년봉": self._build_available_block("year", yearly_points),
            "5분": self._build_unavailable_block("intraday_unavailable", "현재 데이터 경로에서는 5분봉을 제공하지 않습니다."),
            "15분": self._build_unavailable_block("intraday_unavailable", "현재 데이터 경로에서는 15분봉을 제공하지 않습니다."),
            "30분": self._build_unavailable_block("intraday_unavailable", "현재 데이터 경로에서는 30분봉을 제공하지 않습니다."),
            "60분": self._build_unavailable_block("intraday_unavailable", "현재 데이터 경로에서는 60분봉을 제공하지 않습니다."),
        }

        available_timeframes = [name for name, payload in timeframe_map.items() if payload.get("status") == "available"]

        return {
            "supported_timeframes": ["일봉", "월봉", "년봉", "5분", "15분", "30분", "60분"],
            "default_timeframe": "일봉",
            "selected_timeframe": "일봉",
            "available_timeframes": available_timeframes,
            "timeframes": timeframe_map,
            # 하위 호환(기존 UI/테스트)
            "series": [
                {"date": p["date"], "open": p["open"], "high": p["high"], "low": p["low"], "close": p["close"], "volume": p["volume"]}
                for p in daily_points
            ],
            "limitations": [
                "월봉/년봉은 일봉 집계 데이터로 생성합니다.",
                "분봉(5/15/30/60)은 현재 공급 경로 미지원으로 상태만 제공합니다.",
                "가용하지 않은 프레임은 추정/가짜 데이터로 채우지 않습니다.",
            ],
        }

    def _build_available_block(self, timeframe_type: str, points: list[dict[str, Any]]) -> dict[str, Any]:
        if not points:
            return {
                "status": "unavailable",
                "reason_code": "insufficient_market_series",
                "message": "해당 시간프레임을 구성할 시계열 데이터가 부족합니다.",
                "chart_type": "candlestick_like",
                "points": [],
            }

        return {
            "status": "available",
            "reason_code": None,
            "message": None,
            "chart_type": "candlestick_like",
            "timeframe_type": timeframe_type,
            "points": points[-120:],
        }

    def _build_unavailable_block(self, reason_code: str, message: str) -> dict[str, Any]:
        return {
            "status": "unavailable",
            "reason_code": reason_code,
            "message": message,
            "chart_type": "candlestick_like",
            "points": [],
        }

    def _normalize_daily_series(self, series: list[dict[str, Any]]) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for row in series:
            if not isinstance(row, dict):
                continue
            date_key = str(row.get("date") or "")
            if len(date_key) != 8 or not date_key.isdigit():
                continue
            open_price = self._to_float(row.get("open"))
            high_price = self._to_float(row.get("high"))
            low_price = self._to_float(row.get("low"))
            close_price = self._to_float(row.get("close"))
            volume = self._to_float(row.get("volume"))

            if close_price is None:
                continue
            if open_price is None:
                open_price = close_price
            if high_price is None:
                high_price = max(open_price, close_price)
            if low_price is None:
                low_price = min(open_price, close_price)

            normalized.append(
                {
                    "date": date_key,
                    "open": round(open_price, 4),
                    "high": round(max(high_price, open_price, close_price), 4),
                    "low": round(min(low_price, open_price, close_price), 4),
                    "close": round(close_price, 4),
                    "volume": round(volume, 4) if volume is not None else None,
                }
            )

        normalized.sort(key=lambda item: item["date"])
        return normalized

    def _aggregate_by_period(self, daily_points: list[dict[str, Any]], *, period: str) -> list[dict[str, Any]]:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for point in daily_points:
            date_key = point["date"]
            bucket = date_key[:6] if period == "month" else date_key[:4]
            grouped[bucket].append(point)

        aggregated: list[dict[str, Any]] = []
        for bucket in sorted(grouped.keys()):
            rows = grouped[bucket]
            if not rows:
                continue
            open_price = rows[0]["open"]
            close_price = rows[-1]["close"]
            high_price = max(row["high"] for row in rows)
            low_price = min(row["low"] for row in rows)
            volume_total = sum(row["volume"] or 0 for row in rows)
            aggregated.append(
                {
                    "date": bucket,
                    "open": round(open_price, 4),
                    "high": round(high_price, 4),
                    "low": round(low_price, 4),
                    "close": round(close_price, 4),
                    "volume": round(volume_total, 4),
                }
            )
        return aggregated

    def _to_float(self, value: Any) -> float | None:
        if value is None:
            return None
        try:
            raw = str(value).replace(",", "").strip()
            if raw == "":
                return None
            return float(raw)
        except ValueError:
            return None
