from __future__ import annotations

import json
from typing import Any

from django.http import HttpRequest, JsonResponse
from django.views import View

from clients.dart_client import DartAPIRequestError, DartClient
from core.env import MissingDartApiKeyError
from services.company_resolver import CompanyNameResolver
from services.disclosure_normalizer import DisclosureNormalizer
from services.first_pass_evaluator import FirstPassEvaluator
from services.document_heading_candidates_builder import DocumentHeadingCandidatesBuilder
from services.document_outline_builder import DocumentOutlineBuilder
from services.document_zip_inspector import DocumentZipInspectionError, DocumentZipInspector
from services.document_xml_inspector import DocumentXMLInspectionError, DocumentXMLInspector


class DartValidationView(View):
    http_method_names = ["get", "post"]

    def _read_input(self, request: HttpRequest) -> tuple[str | None, str | None]:
        company_name = request.GET.get("company_name")
        corp_code = request.GET.get("corp_code")

        if request.method == "POST":
            try:
                payload: dict[str, Any] = json.loads(request.body.decode("utf-8") or "{}")
            except json.JSONDecodeError:
                payload = {}
            company_name = payload.get("company_name", company_name)
            corp_code = payload.get("corp_code", corp_code)

        company_name = company_name.strip() if isinstance(company_name, str) else None
        corp_code = corp_code.strip() if isinstance(corp_code, str) else None
        if company_name == "":
            company_name = None
        if corp_code == "":
            corp_code = None
        return company_name, corp_code

    def _validate_input(self, company_name: str | None, corp_code: str | None) -> str | None:
        if not company_name and not corp_code:
            return "company_name 또는 corp_code 중 하나는 반드시 입력해야 합니다."
        if corp_code and len(corp_code) != 8:
            return "corp_code는 8자리 문자열이어야 합니다."
        return None

    def dispatch(self, request: HttpRequest, *args: Any, **kwargs: Any) -> JsonResponse:
        company_name, corp_code = self._read_input(request)
        input_error = self._validate_input(company_name, corp_code)
        if input_error:
            return JsonResponse(
                {
                    "ok": False,
                    "error": {
                        "code": "invalid_input",
                        "message": input_error,
                    },
                    "input": {
                        "company_name": company_name,
                        "corp_code": corp_code,
                    },
                },
                status=400,
            )

        try:
            client = DartClient.from_env()
        except MissingDartApiKeyError as exc:
            return JsonResponse(
                {
                    "ok": False,
                    "error": {
                        "code": "missing_dart_api_key",
                        "message": str(exc),
                    },
                    "input": {
                        "company_name": company_name,
                        "corp_code": corp_code,
                    },
                },
                status=500,
            )

        resolution: dict[str, Any] = {
            "status": "skipped",
            "reason": "corp_code 직접 입력이 우선 적용되었습니다.",
            "resolved_corp_code": corp_code,
            "resolved_corp_name": None,
            "candidates": [],
            "match_rule": None,
        }

        if not corp_code and company_name:
            resolver = CompanyNameResolver(dart_client=client)
            try:
                resolution = resolver.resolve(company_name)
            except DartAPIRequestError as exc:
                return JsonResponse(
                    {
                        "ok": False,
                        "error": {
                            "code": "company_resolution_failed",
                            "message": str(exc),
                        },
                        "input": {
                            "company_name": company_name,
                            "corp_code": corp_code,
                        },
                    },
                    status=502,
                )

            if resolution["status"] == "resolved":
                corp_code = resolution["resolved_corp_code"]
            elif resolution["status"] == "unresolved":
                return JsonResponse(
                    {
                        "ok": False,
                        "error": {
                            "code": "unresolved_company_name",
                            "message": "입력한 company_name을 공식 corpCode 데이터에서 안전하게 확인하지 못했습니다.",
                        },
                        "input": {
                            "company_name": company_name,
                            "corp_code": None,
                        },
                        "resolution": resolution,
                    },
                    status=404,
                )
            elif resolution["status"] == "ambiguous":
                return JsonResponse(
                    {
                        "ok": False,
                        "error": {
                            "code": "ambiguous_company_name",
                            "message": "동일한 회사명이 여러 corp_code와 매칭되어 안전하게 단일 선택할 수 없습니다.",
                        },
                        "input": {
                            "company_name": company_name,
                            "corp_code": None,
                        },
                        "resolution": resolution,
                    },
                    status=409,
                )

        normalizer = DisclosureNormalizer()
        evaluator = FirstPassEvaluator()

        analysis: dict[str, Any] = {
            "implemented": False,
            "basis": {"source": "disclosure_list_metadata_only", "fields": []},
            "risk_flags": [],
            "positive_flags": [],
            "neutral_flags": [],
            "document_structure_signals": {
                "available": False,
                "reason": "document_structure_enrichment가 생성되지 않았습니다.",
            },
            "document_structure_hints": {
                "available": False,
                "hint_flags": [],
                "informational_notes": ["document_structure_signals가 없어 구조 힌트를 생성하지 않았습니다."],
            },
            "notes": ["corp_code 확인 전에는 1차 규칙 평가를 수행하지 않습니다."],
            "evaluation_summary": "평가 대상을 확인한 뒤 1차 규칙 평가가 수행됩니다.",
        }

        disclosures: dict[str, Any] = {
            "attempted": False,
            "reason": "corp_code가 확인되어야 최소 live 공시 목록 조회를 수행합니다.",
            "data": None,
        }

        if corp_code:
            try:
                disclosure_data = client.fetch_disclosure_list(corp_code=corp_code, page_count=5)
                normalized_block = normalizer.normalize_items(disclosure_data.get("items", []))
                disclosures = {
                    "attempted": True,
                    "reason": None,
                    "data": {
                        "requested_window": disclosure_data.get("requested_window"),
                        "status": disclosure_data.get("status"),
                        "message": disclosure_data.get("message"),
                        "total_count": disclosure_data.get("total_count"),
                        "raw_items": disclosure_data.get("items", []),
                        "normalized_items": normalized_block["items"],
                        "summary": normalized_block["summary"],
                        "original_document_access": _build_original_document_access(
                            client=client,
                            raw_items=disclosure_data.get("items", []),
                        ),
                        "document_structure_enrichment": _build_document_structure_enrichment(
                            client=client,
                            raw_items=disclosure_data.get("items", []),
                            max_items=1,
                        ),
                    },
                }
                analysis = evaluator.evaluate(
                    summary=normalized_block["summary"],
                    normalized_items=normalized_block["items"],
                )
                analysis["document_structure_signals"] = _build_document_structure_signals(
                    disclosures["data"]["document_structure_enrichment"]
                )
                analysis["document_structure_hints"] = _build_document_structure_hints(
                    analysis["document_structure_signals"]
                )
                analysis["notes"] = [
                    *analysis.get("notes", []),
                    "document_structure_hints는 구조 신호 기반의 정보성 힌트이며 의미 해석/투자 판단을 포함하지 않습니다.",
                ]
            except DartAPIRequestError as exc:
                return JsonResponse(
                    {
                        "ok": False,
                        "error": {
                            "code": "dart_list_fetch_failed",
                            "message": str(exc),
                        },
                        "input": {
                            "company_name": company_name,
                            "corp_code": corp_code,
                        },
                        "resolution": resolution,
                    },
                    status=502,
                )

        return JsonResponse(
            {
                "ok": True,
                "message": "초기 DART 수직 슬라이스 검증이 완료되었습니다.",
                "input": {
                    "company_name": company_name,
                    "corp_code": corp_code,
                },
                "resolution": resolution,
                "dart_client": client.readiness_payload(),
                "lookup_plan": client.build_lookup_plan(
                    company_name=company_name,
                    corp_code=corp_code,
                ),
                "disclosures": disclosures,
                "analysis": analysis,
            }
        )

    get = dispatch
    post = dispatch


def _build_original_document_access(client: DartClient, raw_items: list[dict[str, Any]]) -> dict[str, Any]:
    links = []
    for item in raw_items:
        rcept_no = item.get("rcept_no")
        if not rcept_no:
            continue
        links.append(
            {
                "rcept_no": rcept_no,
                "viewer_url": client.build_viewer_url(str(rcept_no)),
            }
        )
    return {
        "supported": True,
        "fetch_endpoint": "/api/v1/dart/document",
        "items": links,
    }


def _build_document_structure_enrichment(
    *,
    client: DartClient,
    raw_items: list[dict[str, Any]],
    max_items: int,
) -> dict[str, Any]:
    candidates = [item for item in raw_items if item.get("rcept_no")]
    target_items = candidates[:max_items]
    enriched_items: list[dict[str, Any]] = []

    for item in target_items:
        rcept_no = str(item["rcept_no"])
        result: dict[str, Any] = {
            "rcept_no": rcept_no,
            "inspection_attempted": True,
            "status": "unknown",
            "document_outline_available": False,
            "heading_candidates_available": False,
            "heading_candidate_count": 0,
            "heading_candidates_preview": [],
            "section_like_tags_exist": False,
            "table_like_structure_present": False,
            "has_cover_like_structure": False,
            "has_body_like_structure": False,
            "has_summary_like_structure": False,
            "error": None,
        }

        try:
            payload = client.fetch_original_document_payload(rcept_no=rcept_no)
        except DartAPIRequestError as exc:
            result["status"] = "document_fetch_failed"
            result["error"] = {"code": "document_fetch_failed", "message": str(exc)}
            enriched_items.append(result)
            continue

        zip_inspector = DocumentZipInspector()
        try:
            zip_inspector.inspect(payload["content"])
        except DocumentZipInspectionError as exc:
            result["status"] = "zip_inspection_failed"
            result["error"] = {"code": "zip_inspection_failed", "message": str(exc)}
            enriched_items.append(result)
            continue

        xml_inspector = DocumentXMLInspector()
        try:
            xml_inspection = xml_inspector.inspect(payload["content"])
            markup_fallback = xml_inspection.get("markup_fallback_inspection")
        except DocumentXMLInspectionError as exc:
            markup_fallback = getattr(exc, "markup_fallback_inspection", None)

        outline = DocumentOutlineBuilder().build(markup_fallback)
        heading_candidates = DocumentHeadingCandidatesBuilder().build(markup_fallback)

        if isinstance(outline, dict):
            result["document_outline_available"] = bool(outline.get("outline_available"))
            result["section_like_tags_exist"] = (outline.get("section_tag_total_count") or 0) > 0
            result["table_like_structure_present"] = (outline.get("table_like_tag_total_count") or 0) > 0
            result["has_cover_like_structure"] = bool(outline.get("has_cover"))
            result["has_body_like_structure"] = bool(outline.get("has_body"))
            result["has_summary_like_structure"] = bool(outline.get("has_summary"))

        if isinstance(heading_candidates, dict):
            dedup_count = int(heading_candidates.get("deduplicated_heading_candidate_count", 0))
            result["heading_candidate_count"] = dedup_count
            result["heading_candidates_available"] = dedup_count > 0
            result["heading_candidates_preview"] = [
                candidate.get("text")
                for candidate in heading_candidates.get("heading_candidates", [])[:5]
                if isinstance(candidate, dict) and candidate.get("text")
            ]

        result["status"] = "enriched" if result["document_outline_available"] or result["heading_candidates_available"] else "no_structure_signal"
        enriched_items.append(result)

    return {
        "enabled": True,
        "max_items_per_response": max_items,
        "attempted_item_count": len(target_items),
        "skipped_item_count_due_to_limit": max(0, len(candidates) - len(target_items)),
        "items": enriched_items,
        "notes": [
            "문서 구조 enrichment는 제한된 건수에만 시도됩니다.",
            "의미 해석 없이 구조 신호만 제공합니다.",
        ],
    }


def _build_document_structure_signals(enrichment: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(enrichment, dict):
        return {
            "available": False,
            "reason": "document_structure_enrichment가 없습니다.",
        }

    items = [item for item in enrichment.get("items", []) if isinstance(item, dict)]
    enriched_items = [item for item in items if item.get("status") == "enriched"]

    heading_available_count = sum(1 for item in items if item.get("heading_candidates_available"))
    section_like_count = sum(1 for item in items if item.get("section_like_tags_exist"))
    table_like_count = sum(1 for item in items if item.get("table_like_structure_present"))
    cover_like_count = sum(1 for item in items if item.get("has_cover_like_structure"))
    body_like_count = sum(1 for item in items if item.get("has_body_like_structure"))
    summary_like_count = sum(1 for item in items if item.get("has_summary_like_structure"))

    heading_candidate_count_preview = [
        {
            "rcept_no": item.get("rcept_no"),
            "heading_candidate_count": item.get("heading_candidate_count", 0),
        }
        for item in items[:3]
    ]
    heading_text_preview = [
        {
            "rcept_no": item.get("rcept_no"),
            "heading_candidates_preview": item.get("heading_candidates_preview", [])[:3],
        }
        for item in items
        if item.get("heading_candidates_preview")
    ][:3]

    return {
        "available": True,
        "derived_from": "document_structure_enrichment",
        "attempted_item_count": enrichment.get("attempted_item_count", 0),
        "enriched_item_count": len(enriched_items),
        "heading_candidates_available_count": heading_available_count,
        "section_like_structure_count": section_like_count,
        "table_like_structure_count": table_like_count,
        "cover_like_structure_count": cover_like_count,
        "body_like_structure_count": body_like_count,
        "summary_like_structure_count": summary_like_count,
        "document_structure_available": len(enriched_items) > 0,
        "document_heading_candidates_available": heading_available_count > 0,
        "section_like_structure_present": section_like_count > 0,
        "table_heavy_document_present": table_like_count > 0,
        "heading_candidate_count_preview": heading_candidate_count_preview,
        "heading_text_preview": heading_text_preview,
        "notes": [
            "문서 구조 신호 집계는 의미 해석 없이 구조 수준으로만 제공됩니다.",
        ],
    }


def _build_document_structure_hints(document_structure_signals: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(document_structure_signals, dict) or not document_structure_signals.get("available"):
        return {
            "available": False,
            "hint_flags": [],
            "informational_notes": ["document_structure_signals가 없어 구조 힌트를 생성하지 않았습니다."],
        }

    hint_flags: list[str] = []
    if document_structure_signals.get("document_structure_available"):
        hint_flags.append("structured_document_detected")
    if document_structure_signals.get("document_heading_candidates_available"):
        hint_flags.append("heading_candidates_present")
    if document_structure_signals.get("section_like_structure_present"):
        hint_flags.append("section_like_structure_present")
    if document_structure_signals.get("table_heavy_document_present"):
        hint_flags.append("table_heavy_structure_present")
    if (
        document_structure_signals.get("cover_like_structure_count", 0) > 0
        and document_structure_signals.get("body_like_structure_count", 0) > 0
        and document_structure_signals.get("summary_like_structure_count", 0) > 0
    ):
        hint_flags.append("cover_body_summary_like_structure_present")

    return {
        "available": True,
        "derived_from": "analysis.document_structure_signals",
        "hint_flags": hint_flags,
        "attempted_item_count": document_structure_signals.get("attempted_item_count", 0),
        "enriched_item_count": document_structure_signals.get("enriched_item_count", 0),
        "heading_candidates_available_count": document_structure_signals.get("heading_candidates_available_count", 0),
        "section_like_structure_count": document_structure_signals.get("section_like_structure_count", 0),
        "table_like_structure_count": document_structure_signals.get("table_like_structure_count", 0),
        "cover_like_structure_count": document_structure_signals.get("cover_like_structure_count", 0),
        "body_like_structure_count": document_structure_signals.get("body_like_structure_count", 0),
        "summary_like_structure_count": document_structure_signals.get("summary_like_structure_count", 0),
        "heading_candidate_count_preview": document_structure_signals.get("heading_candidate_count_preview", [])[:3],
        "heading_text_preview_available": len(document_structure_signals.get("heading_text_preview", [])) > 0,
        "informational_notes": [
            "구조 힌트는 heading/section/table/cover/body/summary 존재 여부를 정보성으로만 표시합니다.",
            "구조 힌트는 사업 의미나 투자 판단을 직접 나타내지 않습니다.",
        ],
    }


class DartOriginalDocumentView(View):
    http_method_names = ["get"]

    def get(self, request: HttpRequest, *args: Any, **kwargs: Any) -> JsonResponse:
        rcept_no = (request.GET.get("rcept_no") or "").strip()
        if not rcept_no:
            return JsonResponse(
                {
                    "ok": False,
                    "error": {
                        "code": "invalid_input",
                        "message": "rcept_no는 필수입니다.",
                    },
                    "input": {"rcept_no": rcept_no or None},
                },
                status=400,
            )

        try:
            client = DartClient.from_env()
        except MissingDartApiKeyError as exc:
            return JsonResponse(
                {
                    "ok": False,
                    "error": {
                        "code": "missing_dart_api_key",
                        "message": str(exc),
                    },
                    "input": {"rcept_no": rcept_no},
                },
                status=500,
            )

        try:
            payload = client.fetch_original_document_payload(rcept_no=rcept_no)
        except DartAPIRequestError as exc:
            return JsonResponse(
                {
                    "ok": False,
                    "error": {
                        "code": "original_document_fetch_failed",
                        "message": str(exc),
                    },
                    "input": {"rcept_no": rcept_no},
                    "document_access": None,
                    "zip_inspection": None,
                    "xml_inspection": None,
                    "xml_parse_diagnostics": None,
                    "xml_fallback_inspection": None,
                    "markup_fallback_inspection": None,
                    "document_outline": None,
                    "document_heading_candidates": None,
                },
                status=502,
            )

        document_access = {
            "rcept_no": payload["rcept_no"],
            "viewer_url": payload["viewer_url"],
            "content_type": payload["content_type"],
            "byte_size": len(payload["content"]),
        }

        inspector = DocumentZipInspector()
        try:
            zip_inspection = inspector.inspect(payload["content"])
        except DocumentZipInspectionError as exc:
            return JsonResponse(
                {
                    "ok": False,
                    "error": {
                        "code": "original_document_zip_inspection_failed",
                        "message": str(exc),
                    },
                    "input": {"rcept_no": rcept_no},
                    "document_access": document_access,
                    "zip_inspection": None,
                    "xml_inspection": None,
                    "xml_parse_diagnostics": None,
                    "xml_fallback_inspection": None,
                    "markup_fallback_inspection": None,
                    "document_outline": None,
                    "document_heading_candidates": None,
                },
                status=502,
            )

        xml_inspector = DocumentXMLInspector()
        try:
            xml_inspection = xml_inspector.inspect(payload["content"])
        except DocumentXMLInspectionError as exc:
            return JsonResponse(
                {
                    "ok": False,
                    "error": {
                        "code": "original_document_xml_inspection_failed",
                        "message": str(exc),
                    },
                    "input": {"rcept_no": rcept_no},
                    "document_access": document_access,
                    "zip_inspection": zip_inspection,
                    "xml_inspection": None,
                    "xml_parse_diagnostics": exc.diagnostics,
                    "xml_fallback_inspection": exc.fallback_inspection,
                    "markup_fallback_inspection": getattr(exc, "markup_fallback_inspection", None),
                    "document_outline": DocumentOutlineBuilder().build(getattr(exc, "markup_fallback_inspection", None)),
                    "document_heading_candidates": DocumentHeadingCandidatesBuilder().build(
                        getattr(exc, "markup_fallback_inspection", None)
                    ),
                },
                status=502,
            )

        xml_parse_diagnostics = xml_inspection.get("xml_parse_diagnostics")
        xml_fallback_inspection = xml_inspection.get("xml_fallback_inspection")
        markup_fallback_inspection = xml_inspection.get("markup_fallback_inspection")
        document_outline = DocumentOutlineBuilder().build(markup_fallback_inspection)
        document_heading_candidates = DocumentHeadingCandidatesBuilder().build(markup_fallback_inspection)

        return JsonResponse(
            {
                "ok": True,
                "input": {"rcept_no": rcept_no},
                "document_access": document_access,
                "zip_inspection": zip_inspection,
                "xml_inspection": {
                    "parsing_succeeded": xml_inspection["parsing_succeeded"],
                    "selected_entry_is_xml": xml_inspection["selected_entry_is_xml"],
                    "selected_entry_name": xml_inspection["selected_entry_name"],
                    "root_tag": xml_inspection["root_tag"],
                    "namespace_uri": xml_inspection["namespace_uri"],
                    "top_level_child_tags": xml_inspection["top_level_child_tags"],
                    "top_level_child_count": xml_inspection["top_level_child_count"],
                    "message": xml_inspection["message"],
                },
                "xml_parse_diagnostics": xml_parse_diagnostics,
                "xml_fallback_inspection": xml_fallback_inspection,
                "markup_fallback_inspection": markup_fallback_inspection,
                "document_outline": document_outline,
                "document_heading_candidates": document_heading_candidates,
                "notes": [
                    "현재 단계는 XML 구조 메타데이터(root tag/최상위 child)까지만 제공합니다.",
                    "본문 텍스트/섹션 의미 해석은 아직 구현하지 않았습니다.",
                ],
            }
        )
