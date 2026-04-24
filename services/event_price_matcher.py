from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class EventPriceMatcher:
    def build(
        self,
        *,
        considered_disclosures: list[dict[str, Any]],
        market_data_status: dict[str, Any],
    ) -> dict[str, Any]:
        series = market_data_status.get("data", {}).get("recent_daily_series", []) if isinstance(market_data_status.get("data"), dict) else []
        if not isinstance(series, list):
            series = []

        if len(series) < 5:
            return {
                "status": "insufficient_pattern_history",
                "reaction_window": {"pre_days": 3, "post_days": 3},
                "event_price_reaction": [],
                "historical_reaction_pattern": "데이터 부족",
                "event_pattern_signal": "insufficient_pattern_history",
                "pattern_confidence": "low",
                "prediction_signal": "insufficient_evidence",
                "prediction_confidence": "low",
                "prediction_limitations": [
                    "이벤트 전후 비교에 필요한 일자별 시세 데이터가 부족합니다.",
                ],
            }

        date_to_close: dict[str, float] = {}
        for row in series:
            if not isinstance(row, dict):
                continue
            date_key = str(row.get("date") or "")
            close = row.get("close")
            if date_key and isinstance(close, (int, float)) and close > 0:
                date_to_close[date_key] = float(close)

        reactions = []
        for disclosure in considered_disclosures[:30]:
            date_str = str(disclosure.get("rcept_dt") or "")
            if len(date_str) != 8:
                continue
            event_day = f"{date_str[:4]}{date_str[4:6]}{date_str[6:8]}"
            move = self._compute_simple_move(date_to_close=date_to_close, event_day=event_day)
            if move is None:
                continue
            reactions.append(
                {
                    "rcept_no": disclosure.get("rcept_no"),
                    "report_nm": disclosure.get("report_nm"),
                    "event_date": event_day,
                    "pre_event_move": move["pre_event_move"],
                    "post_event_move": move["post_event_move"],
                    "matched_price_context": move,
                    "reaction_limitations": ["근접 거래일 기준 단순 전후 비교입니다."],
                }
            )

        if not reactions:
            return {
                "status": "insufficient_pattern_history",
                "reaction_window": {"pre_days": 3, "post_days": 3},
                "event_price_reaction": [],
                "historical_reaction_pattern": "이벤트 매칭 실패",
                "event_pattern_signal": "insufficient_pattern_history",
                "pattern_confidence": "low",
                "prediction_signal": "insufficient_evidence",
                "prediction_confidence": "low",
                "prediction_limitations": ["공시일과 시세일 매칭 가능한 데이터가 부족합니다."],
            }

        positive = sum(1 for row in reactions if row["post_event_move"] > 0)
        negative = sum(1 for row in reactions if row["post_event_move"] < 0)
        signal = "mixed"
        if positive > negative:
            signal = "positive"
        elif negative > positive:
            signal = "negative"

        confidence = "medium" if len(reactions) >= 3 else "low"

        return {
            "status": "ok",
            "reaction_window": {"pre_days": 3, "post_days": 3},
            "event_price_reaction": reactions[:10],
            "historical_reaction_pattern": f"양(+) {positive}건 / 음(-) {negative}건",
            "event_pattern_signal": signal,
            "pattern_confidence": confidence,
            "prediction_signal": signal if confidence != "low" else "insufficient_evidence",
            "prediction_confidence": confidence,
            "prediction_limitations": [
                "표본 수가 제한적이며 이벤트 외 요인(시장 전체 변동 등)을 완전히 분리하지 못합니다.",
                "통계적 확정 예측이 아닌 참고용 패턴 요약입니다.",
            ],
        }

    def _compute_simple_move(self, *, date_to_close: dict[str, float], event_day: str) -> dict[str, Any] | None:
        keys = sorted(date_to_close.keys())
        if event_day not in keys:
            return None
        idx = keys.index(event_day)
        if idx - 1 < 0 or idx + 1 >= len(keys):
            return None
        pre_close = date_to_close[keys[idx - 1]]
        event_close = date_to_close[keys[idx]]
        post_close = date_to_close[keys[idx + 1]]
        if pre_close <= 0 or event_close <= 0:
            return None
        pre_move = round((event_close - pre_close) / pre_close, 4)
        post_move = round((post_close - event_close) / event_close, 4)
        return {
            "pre_event_close": pre_close,
            "event_close": event_close,
            "post_event_close": post_close,
            "pre_event_move": pre_move,
            "post_event_move": post_move,
        }
