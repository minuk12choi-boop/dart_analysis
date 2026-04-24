from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from services.disclosure_meaning_evaluator import DisclosureMeaningEvaluator
from services.event_price_matcher import EventPriceMatcher
from services.final_report_builder import FinalReportBuilder
from services.market_data_provider import MarketDataProvider
from services.price_assessment_engine import PriceAssessmentEngine
from services.market_chart_builder import MarketChartBuilder


@dataclass(slots=True)
class InvestmentReportBuilder:
    display_card_limit: int = 3
    disclosure_meaning_evaluator: DisclosureMeaningEvaluator = field(default_factory=DisclosureMeaningEvaluator)
    event_price_matcher: EventPriceMatcher = field(default_factory=EventPriceMatcher)
    market_data_provider: MarketDataProvider = field(default_factory=MarketDataProvider.from_env)
    price_assessment_engine: PriceAssessmentEngine = field(default_factory=PriceAssessmentEngine)
    market_chart_builder: MarketChartBuilder = field(default_factory=MarketChartBuilder)

    def build(self, *, validate_payload: dict[str, Any], validate_status_code: int) -> dict[str, Any]:
        request_block = validate_payload.get("input", {}) if isinstance(validate_payload, dict) else {}
        disclosures_data = validate_payload.get("disclosures", {}).get("data", {}) if isinstance(validate_payload, dict) else {}
        normalized_items = disclosures_data.get("normalized_items", []) if isinstance(disclosures_data, dict) else []
        summary = disclosures_data.get("summary", {}) if isinstance(disclosures_data, dict) else {}
        enrichment = disclosures_data.get("document_structure_enrichment", {}) if isinstance(disclosures_data, dict) else {}
        analysis = validate_payload.get("analysis", {}) if isinstance(validate_payload, dict) else {}
        report_preview = validate_payload.get("report_preview", {}) if isinstance(validate_payload, dict) else {}
        type_specific_analysis = validate_payload.get("type_specific_analysis", {}) if isinstance(validate_payload, dict) else {}

        meaning_result = self.disclosure_meaning_evaluator.evaluate(
            normalized_items=normalized_items,
            type_specific_analysis=type_specific_analysis,
            analysis=analysis,
            report_preview=report_preview,
            document_structure_enrichment=enrichment,
        )
        aggregate = meaning_result["aggregate_signal_assessment"]

        first_stock_code = None
        for item in normalized_items:
            raw = item.get("raw", {}) if isinstance(item, dict) else {}
            stock_code = raw.get("stock_code")
            if stock_code:
                first_stock_code = stock_code
                break

        market_data_status = self.market_data_provider.fetch_snapshot(
            corp_code=request_block.get("corp_code"),
            stock_code=first_stock_code,
        )
        price_assessment = self.price_assessment_engine.build(
            market_data_status=market_data_status,
            aggregate_signal_direction=aggregate.get("signal_direction", "insufficient_evidence"),
        )

        display_cards = FinalReportBuilder(card_limit=self.display_card_limit).build(
            validate_payload=validate_payload,
            validate_status_code=validate_status_code,
        ).get("disclosure_cards", [])
        considered_disclosures = [
            {
                "rcept_no": (item.get("raw", {}) if isinstance(item, dict) else {}).get("rcept_no"),
                "report_nm": (item.get("raw", {}) if isinstance(item, dict) else {}).get("report_nm"),
                "rcept_dt": (item.get("raw", {}) if isinstance(item, dict) else {}).get("rcept_dt"),
                "category": (item.get("normalized", {}) if isinstance(item, dict) else {}).get("category"),
                "detected_signals": (item.get("normalized", {}) if isinstance(item, dict) else {}).get("detected_signals", []),
            }
            for item in normalized_items
            if isinstance(item, dict)
        ]
        event_pattern_assessment = self.event_price_matcher.build(
            considered_disclosures=considered_disclosures,
            market_data_status=market_data_status,
        )
        market_chart = self.market_chart_builder.build(market_data_status=market_data_status)

        status = {
            "code": "ok" if validate_status_code in {200, 502} else "error",
            "source_validate_status_code": validate_status_code,
            "message": "공시 기반 투자판단 리포트를 생성했습니다." if validate_status_code in {200, 502} else "검증 단계 오류로 투자판단 리포트가 제한되었습니다.",
        }

        return {
            "request": request_block,
            "status": status,
            "report_meta": {
                "version": "investment_v1",
                "built_from": "validate_response",
                "considered_disclosure_count": len(normalized_items),
                "displayed_disclosure_count": len(display_cards),
                "display_card_limit": self.display_card_limit,
            },
            "window_summary": {
                "requested_window": disclosures_data.get("requested_window") if isinstance(disclosures_data, dict) else None,
                "selected_window": (
                    disclosures_data.get("selected_window")
                    if isinstance(disclosures_data, dict) and disclosures_data.get("selected_window")
                    else request_block.get("window", "1m")
                ),
                "window_label": (
                    disclosures_data.get("window_label")
                    if isinstance(disclosures_data, dict) and disclosures_data.get("window_label")
                    else {"all": "전체", "1m": "최근 1개월", "3m": "최근 3개월", "6m": "최근 6개월", "1y": "최근 1년"}.get(
                        request_block.get("window", "1m"), "최근 1개월"
                    )
                ),
                "total_disclosures": summary.get("total_disclosures", 0) if isinstance(summary, dict) else 0,
                "category_counts": summary.get("category_counts", {}) if isinstance(summary, dict) else {},
                "detected_signal_counts": summary.get("detected_signals", {}) if isinstance(summary, dict) else {},
                "considered_disclosure_count": len(considered_disclosures),
                "displayed_disclosure_count": len(display_cards),
            },
            "aggregate_signal_assessment": aggregate,
            "event_assessment": meaning_result.get("event_assessment", {}),
            "market_data_status": market_data_status,
            "price_assessment": price_assessment,
            "key_evidence": meaning_result.get("key_evidence", []),
            "caution_points": meaning_result.get("caution_points", []),
            "considered_disclosures": considered_disclosures,
            "display_disclosure_cards": display_cards,
            "event_pattern_assessment": event_pattern_assessment,
            "historical_reaction_summary": event_pattern_assessment.get("historical_reaction_summary", {}),
            "prediction_signal": event_pattern_assessment.get("prediction_signal", "insufficient_evidence"),
            "prediction_confidence": event_pattern_assessment.get("prediction_confidence", "low"),
            "prediction_limitations": event_pattern_assessment.get("prediction_limitations", []),
            "market_chart": market_chart,
            "limitations": [
                "투자판단 보조용 구조화 리포트이며 확정적 매수/매도 추천을 제공하지 않습니다.",
                "시장 데이터가 부족하면 가격 구간 산출을 생략합니다.",
                "공시 원문/시장 상황/추가 재무 데이터의 후속 검토가 필요합니다.",
            ],
            "upstream_status": validate_payload.get("upstream_status") if isinstance(validate_payload, dict) else None,
            "cache_status": validate_payload.get("cache_status") if isinstance(validate_payload, dict) else None,
        }
