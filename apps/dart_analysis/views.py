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
                    },
                }
                analysis = evaluator.evaluate(
                    summary=normalized_block["summary"],
                    normalized_items=normalized_block["items"],
                )
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
                },
                status=502,
            )

        xml_parse_diagnostics = xml_inspection.get("xml_parse_diagnostics")
        xml_fallback_inspection = xml_inspection.get("xml_fallback_inspection")
        markup_fallback_inspection = xml_inspection.get("markup_fallback_inspection")

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
                "notes": [
                    "현재 단계는 XML 구조 메타데이터(root tag/최상위 child)까지만 제공합니다.",
                    "본문 텍스트/섹션 의미 해석은 아직 구현하지 않았습니다.",
                ],
            }
        )
