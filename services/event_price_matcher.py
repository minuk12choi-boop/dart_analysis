from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class EventPriceMatcher:
    reaction_window_pre_days: int = 3
    reaction_window_post_days: int = 3

    def build(
        self,
        *,
        considered_disclosures: list[dict[str, Any]],
        market_data_status: dict[str, Any],
    ) -> dict[str, Any]:
        series = market_data_status.get("data", {}).get("recent_daily_series", []) if isinstance(market_data_status.get("data"), dict) else []
        if not isinstance(series, list):
            series = []

        date_to_close: dict[str, float] = {}
        ordered_dates: list[str] = []
        for row in sorted([r for r in series if isinstance(r, dict)], key=lambda item: str(item.get("date") or "")):
            date_key = str(row.get("date") or "")
            close = row.get("close")
            if len(date_key) == 8 and isinstance(close, (int, float)) and close > 0:
                date_to_close[date_key] = float(close)
                ordered_dates.append(date_key)

        if len(ordered_dates) < 8:
            return self._insufficient("이벤트 전후 비교에 필요한 일자별 시세 데이터가 부족합니다.")

        reactions: list[dict[str, Any]] = []
        for disclosure in considered_disclosures[:60]:
            if not isinstance(disclosure, dict):
                continue
            event_day = str(disclosure.get("rcept_dt") or "")
            if len(event_day) != 8:
                continue
            price_context = self._compute_window_move(date_to_close=date_to_close, ordered_dates=ordered_dates, event_day=event_day)
            if price_context is None:
                continue

            reaction_label = self._reaction_label(price_context["post_event_move"])
            signal_impact = self._signal_impact(disclosure.get("category"), disclosure.get("detected_signals", []))
            evidence_notes = self._evidence_notes(disclosure)

            reactions.append(
                {
                    "rcept_no": disclosure.get("rcept_no"),
                    "report_nm": disclosure.get("report_nm"),
                    "event_date": event_day,
                    "event_price_reaction": reaction_label,
                    "matched_price_context": price_context,
                    "disclosure_type_context": {
                        "category": disclosure.get("category") or "other",
                        "signal_impact": signal_impact,
                        "detected_signals": disclosure.get("detected_signals", []),
                    },
                    "evidence_context": evidence_notes,
                    "reaction_limitations": [
                        "공시시각/장중 반영 시차를 분리하지 못한 근접 거래일 윈도우 비교입니다.",
                    ],
                }
            )

        if not reactions:
            return self._insufficient("공시일과 시세일 매칭 가능한 데이터가 부족합니다.")

        positive = sum(1 for row in reactions if row["event_price_reaction"] == "positive")
        negative = sum(1 for row in reactions if row["event_price_reaction"] == "negative")
        neutral = len(reactions) - positive - negative
        avg_post = round(sum(row["matched_price_context"]["post_event_move"] for row in reactions) / len(reactions), 4)

        event_pattern_signal = "mixed"
        if positive >= negative + 2:
            event_pattern_signal = "positive"
        elif negative >= positive + 2:
            event_pattern_signal = "negative"

        confidence = "low"
        if len(reactions) >= 8:
            confidence = "medium"
        if len(reactions) >= 16 and abs(avg_post) >= 0.01:
            confidence = "medium"

        prediction_signal = event_pattern_signal if confidence != "low" else "insufficient_evidence"
        return {
            "status": "ok",
            "reaction_window": {"pre_days": self.reaction_window_pre_days, "post_days": self.reaction_window_post_days},
            "event_price_reaction": reactions[:15],
            "matched_price_context": {
                "matched_event_count": len(reactions),
                "avg_post_event_move": avg_post,
                "positive_reaction_count": positive,
                "negative_reaction_count": negative,
                "neutral_reaction_count": neutral,
            },
            "historical_reaction_pattern": f"양(+) {positive}건 / 음(-) {negative}건 / 중립 {neutral}건",
            "historical_reaction_summary": {
                "sample_size": len(reactions),
                "average_post_event_move": avg_post,
                "dominant_reaction": event_pattern_signal,
            },
            "event_pattern_signal": event_pattern_signal,
            "pattern_confidence": confidence,
            "prediction_signal": prediction_signal,
            "prediction_confidence": confidence,
            "prediction_limitations": [
                "공시와 주가의 인과를 확정하지 않으며, 시장 전체 변동/동일일 타 이벤트를 완전히 분리하지 못합니다.",
                "표본 수가 작거나 반응 폭이 작으면 예측 신호를 insufficient_evidence로 낮춥니다.",
            ],
        }

    def _insufficient(self, message: str) -> dict[str, Any]:
        return {
            "status": "insufficient_pattern_history",
            "reaction_window": {"pre_days": self.reaction_window_pre_days, "post_days": self.reaction_window_post_days},
            "event_price_reaction": [],
            "matched_price_context": {
                "matched_event_count": 0,
                "avg_post_event_move": None,
                "positive_reaction_count": 0,
                "negative_reaction_count": 0,
                "neutral_reaction_count": 0,
            },
            "historical_reaction_pattern": "데이터 부족",
            "historical_reaction_summary": {
                "sample_size": 0,
                "average_post_event_move": None,
                "dominant_reaction": "insufficient_pattern_history",
            },
            "event_pattern_signal": "insufficient_pattern_history",
            "pattern_confidence": "low",
            "prediction_signal": "insufficient_evidence",
            "prediction_confidence": "low",
            "prediction_limitations": [message],
        }

    def _compute_window_move(self, *, date_to_close: dict[str, float], ordered_dates: list[str], event_day: str) -> dict[str, Any] | None:
        if event_day not in date_to_close:
            return None
        idx = ordered_dates.index(event_day)
        pre_idx = idx - self.reaction_window_pre_days
        post_idx = idx + self.reaction_window_post_days
        if pre_idx < 0 or post_idx >= len(ordered_dates):
            return None

        pre_date = ordered_dates[pre_idx]
        post_date = ordered_dates[post_idx]

        pre_close = date_to_close[pre_date]
        event_close = date_to_close[event_day]
        post_close = date_to_close[post_date]
        if min(pre_close, event_close, post_close) <= 0:
            return None

        pre_move = round((event_close - pre_close) / pre_close, 4)
        post_move = round((post_close - event_close) / event_close, 4)
        total_move = round((post_close - pre_close) / pre_close, 4)

        return {
            "pre_date": pre_date,
            "event_date": event_day,
            "post_date": post_date,
            "pre_event_close": pre_close,
            "event_close": event_close,
            "post_event_close": post_close,
            "pre_event_move": pre_move,
            "post_event_move": post_move,
            "total_window_move": total_move,
        }

    def _reaction_label(self, post_move: float) -> str:
        if post_move >= 0.015:
            return "positive"
        if post_move <= -0.015:
            return "negative"
        return "neutral"

    def _signal_impact(self, category: Any, signals: Any) -> str:
        signal_list = [str(item) for item in signals] if isinstance(signals, list) else []
        if any(key in signal_list for key in ["rights_offering", "convertible_bond", "bond_with_warrant", "litigation"]):
            return "risk_heavy"
        if any(key in signal_list for key in ["supply_contract", "facility_investment"]):
            return "growth_related"
        if str(category or "") in {"financing", "legal_or_regulatory"}:
            return "risk_heavy"
        return "neutral"

    def _evidence_notes(self, disclosure: dict[str, Any]) -> list[str]:
        report_nm = disclosure.get("report_nm") or "제목 정보 없음"
        category = disclosure.get("category") or "other"
        signals = disclosure.get("detected_signals") if isinstance(disclosure.get("detected_signals"), list) else []
        return [
            f"공시 제목: {report_nm}",
            f"공시 분류: {category}",
            f"감지 신호: {', '.join([str(item) for item in signals]) if signals else '없음'}",
        ]
