from __future__ import annotations

import os
from unittest.mock import patch

from django.test import Client, TestCase

from clients.dart_client import DartAPIRequestError, DartClient
from services.company_resolver import CompanyNameResolver
from services.disclosure_normalizer import DisclosureNormalizer
from services.document_xml_inspector import DocumentXMLInspectionError, DocumentXMLInspector
from services.document_heading_candidates_builder import DocumentHeadingCandidatesBuilder
from services.document_outline_builder import DocumentOutlineBuilder
from services.document_zip_inspector import DocumentZipInspectionError, DocumentZipInspector
from services.first_pass_evaluator import FirstPassEvaluator


def _build_test_zip_payload() -> bytes:
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("20260417000682.xml", "<ROOT><HEAD/><BODY/></ROOT>")
    return buffer.getvalue()


def _build_invalid_xml_zip_payload() -> bytes:
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("20260417000682.xml", '<?xml version="1.0" encoding="utf-8"?>\n<ROOT><HEAD/>\x01<BODY/></ROOT>')
    return buffer.getvalue()


def _build_unrecoverable_invalid_xml_zip_payload() -> bytes:
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("20260417000682.xml", '<?xml version="1.0" encoding="utf-8"?>\n<ROOT><HEAD></ROOT>')
    return buffer.getvalue()


def _build_non_markup_invalid_xml_zip_payload() -> bytes:
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("20260417000682.xml", "this is not markup and not xml")
    return buffer.getvalue()


def _build_markup_with_heading_candidates_invalid_xml_zip_payload() -> bytes:
    import io
    import zipfile

    xml_like = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        "<document>"
        "<document-name>테스트 문서</document-name>"
        "<body><section-1><title>요약 정보</title><p>본문</p></section-1>"
        "<section-2><title>재무 상태</title></section-2>"
        "</body>"
    )  # 의도적으로 closing tag 누락

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("20260417000682.xml", xml_like)
    return buffer.getvalue()


class DisclosureNormalizerTests(TestCase):
    def setUp(self) -> None:
        self.normalizer = DisclosureNormalizer()

    def test_normalize_items_preserves_raw_and_adds_category_and_signals(self):
        raw_items = [
            {
                "rcept_no": "1",
                "report_nm": "유상증자 결정",
                "rcept_dt": "20260101",
                "corp_code": "00126380",
                "corp_name": "테스트",
                "stock_code": "005930",
            }
        ]

        result = self.normalizer.normalize_items(raw_items)

        self.assertEqual(result["summary"]["total_disclosures"], 1)
        item = result["items"][0]
        self.assertEqual(item["raw"]["rcept_no"], "1")
        self.assertEqual(item["normalized"]["category"], "financing")
        self.assertIn("rights_offering", item["normalized"]["detected_signals"])

    def test_category_classification(self):
        self.assertEqual(self.normalizer.classify_category("사업보고서 제출"), "periodic_report")
        self.assertEqual(self.normalizer.classify_category("소송 등의 제기"), "legal_or_regulatory")
        self.assertEqual(self.normalizer.classify_category("분류 불가 제목"), "other")

    def test_signal_detection_from_title(self):
        signals = self.normalizer.detect_signals("전환사채권발행결정 및 소송 등의 제기")
        self.assertIn("convertible_bond", signals)
        self.assertIn("litigation", signals)


class DartClientDocumentAccessTests(TestCase):
    def test_viewer_url_generation_from_rcept_no(self):
        client = DartClient(api_key="dummy")
        url = client.build_viewer_url("20260101000001")
        self.assertEqual(url, "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260101000001")


class DocumentZipInspectorTests(TestCase):
    def setUp(self) -> None:
        self.inspector = DocumentZipInspector()

    def test_successful_zip_inspection_from_mock_payload(self):
        result = self.inspector.inspect(_build_test_zip_payload())

        self.assertTrue(result["is_zip"])
        self.assertEqual(result["entry_count"], 1)
        names = [entry["name"] for entry in result["entries"]]
        self.assertIn("20260417000682.xml", names)

    def test_non_zip_payload_failure_path(self):
        with self.assertRaises(DocumentZipInspectionError):
            self.inspector.inspect(b"not-a-zip")


class DocumentXMLInspectorTests(TestCase):
    def setUp(self) -> None:
        self.inspector = DocumentXMLInspector()

    def test_successful_xml_inspection_from_single_xml_zip(self):
        result = self.inspector.inspect(_build_test_zip_payload())
        self.assertTrue(result["parsing_succeeded"])
        self.assertTrue(result["selected_entry_is_xml"])
        self.assertEqual(result["selected_entry_name"], "20260417000682.xml")
        self.assertEqual(result["root_tag"], "ROOT")
        self.assertEqual(result["top_level_child_count"], 2)
        self.assertIsNone(result["xml_parse_diagnostics"])
        self.assertIsNone(result["xml_fallback_inspection"])
        self.assertIsNone(result["markup_fallback_inspection"])

    def test_xml_parse_failure_with_fallback_sanitize_success_path(self):
        result = self.inspector.inspect(_build_invalid_xml_zip_payload())

        self.assertFalse(result["parsing_succeeded"])
        self.assertIsNone(result["root_tag"])
        diagnostics = result["xml_parse_diagnostics"]
        self.assertEqual(diagnostics["selected_entry_name"], "20260417000682.xml")
        self.assertIsNotNone(diagnostics["parser_line"])
        self.assertIsNotNone(diagnostics["parser_column"])
        self.assertIn("ROOT", diagnostics["sanitized_excerpt"])
        self.assertIsNotNone(diagnostics["xml_declaration_text"])

        fallback = result["xml_fallback_inspection"]
        self.assertTrue(fallback["fallback_parsing_succeeded"])
        self.assertTrue(fallback["sanitization_applied"])
        self.assertEqual(fallback["root_tag"], "ROOT")
        self.assertEqual(fallback["top_level_child_count"], 2)
        self.assertGreaterEqual(len(fallback["sanitization_rules_applied"]), 1)
        self.assertIsNone(result["markup_fallback_inspection"])

    def test_xml_parse_failure_with_markup_fallback_success_path(self):
        result = self.inspector.inspect(_build_unrecoverable_invalid_xml_zip_payload())
        self.assertFalse(result["parsing_succeeded"])
        self.assertFalse(result["xml_fallback_inspection"]["fallback_parsing_succeeded"])
        self.assertFalse(result["xml_fallback_inspection"]["sanitization_applied"])
        self.assertTrue(result["markup_fallback_inspection"]["markup_fallback_attempted"])
        self.assertTrue(result["markup_fallback_inspection"]["markup_fallback_succeeded"])
        self.assertTrue(result["markup_fallback_inspection"]["document_appears_markup_like"])
        self.assertGreater(len(result["markup_fallback_inspection"]["first_unique_tag_names"]), 0)

    def test_xml_parse_failure_with_markup_fallback_failure_path(self):
        with self.assertRaises(DocumentXMLInspectionError) as exc_info:
            self.inspector.inspect(_build_non_markup_invalid_xml_zip_payload())

        diagnostics = exc_info.exception.diagnostics
        fallback = exc_info.exception.fallback_inspection
        markup_fallback = exc_info.exception.markup_fallback_inspection
        self.assertEqual(diagnostics["selected_entry_name"], "20260417000682.xml")
        self.assertFalse(fallback["fallback_parsing_succeeded"])
        self.assertFalse(markup_fallback["markup_fallback_succeeded"])
        self.assertFalse(markup_fallback["document_appears_markup_like"])
        self.assertIsNotNone(markup_fallback["markup_fallback_error_message"])


class DocumentOutlineBuilderTests(TestCase):
    def setUp(self) -> None:
        self.builder = DocumentOutlineBuilder()

    def test_build_from_markup_fallback_success(self):
        markup_fallback = {
            "markup_fallback_attempted": True,
            "markup_fallback_succeeded": True,
            "first_unique_tag_names": ["document", "summary", "body", "section-1", "table", "p", "title", "cover"],
            "first_opening_tags": ["document", "summary", "body", "section-1", "title", "p"],
            "shallow_tag_sequence": ["document", "summary", "body"],
            "tag_counts": {
                "document": 1,
                "summary": 1,
                "body": 1,
                "cover": 1,
                "section-1": 2,
                "table": 3,
                "p": 5,
                "title": 1,
            },
        }

        outline = self.builder.build(markup_fallback)
        self.assertTrue(outline["outline_available"])
        self.assertTrue(outline["has_body"])
        self.assertTrue(outline["has_cover"])
        self.assertTrue(outline["has_summary"])
        self.assertTrue(outline["has_title_tags"])
        self.assertEqual(outline["section_tag_names"], ["section-1"])
        self.assertEqual(outline["section_tag_total_count"], 2)
        self.assertEqual(outline["table_like_tag_total_count"], 3)
        self.assertEqual(outline["paragraph_like_tag_total_count"], 5)
        self.assertNotIn("semantic_sections", outline)


class DocumentHeadingCandidatesBuilderTests(TestCase):
    def setUp(self) -> None:
        self.builder = DocumentHeadingCandidatesBuilder()

    def test_build_from_markup_heading_candidates_success(self):
        markup_fallback = {
            "markup_fallback_attempted": True,
            "markup_fallback_succeeded": True,
            "heading_like_tag_names_used": ["title", "document-name"],
            "heading_candidates": [
                {"source_tag": "title", "text": "요약 정보", "text_length": 5},
                {"source_tag": "title", "text": "요약 정보", "text_length": 5},
                {"source_tag": "document-name", "text": "테스트 문서", "text_length": 6},
            ],
        }

        result = self.builder.build(markup_fallback)
        self.assertTrue(result["extraction_attempted"])
        self.assertTrue(result["extraction_succeeded"])
        self.assertEqual(result["heading_candidate_count"], 3)
        self.assertEqual(result["deduplicated_heading_candidate_count"], 2)
        self.assertEqual(len(result["heading_candidates"]), 2)
        self.assertNotIn("semantic_labels", result)

    def test_build_from_markup_heading_candidates_empty_path(self):
        markup_fallback = {
            "markup_fallback_attempted": True,
            "markup_fallback_succeeded": True,
            "heading_like_tag_names_used": [],
            "heading_candidates": [],
        }
        result = self.builder.build(markup_fallback)
        self.assertTrue(result["extraction_attempted"])
        self.assertTrue(result["extraction_succeeded"])
        self.assertEqual(result["heading_candidate_count"], 0)
        self.assertEqual(result["deduplicated_heading_candidate_count"], 0)


class FirstPassEvaluatorTests(TestCase):
    def setUp(self) -> None:
        self.evaluator = FirstPassEvaluator()

    def test_financing_heavy_case_produces_risk_flags(self):
        summary = {
            "total_disclosures": 2,
            "category_counts": {"financing": 2},
            "detected_signals": {"rights_offering": 1, "convertible_bond": 1},
        }
        result = self.evaluator.evaluate(summary=summary, normalized_items=[])

        flags = [flag["flag"] for flag in result["risk_flags"]]
        self.assertIn("financing_related_signal", flags)

    def test_litigation_case_produces_risk_flags(self):
        summary = {
            "total_disclosures": 1,
            "category_counts": {"legal_or_regulatory": 1},
            "detected_signals": {"litigation": 1},
        }
        result = self.evaluator.evaluate(summary=summary, normalized_items=[])

        flags = [flag["flag"] for flag in result["risk_flags"]]
        self.assertIn("legal_or_regulatory_signal", flags)

    def test_supply_contract_case_produces_positive_non_final_flag(self):
        summary = {
            "total_disclosures": 1,
            "category_counts": {"contract_or_business": 1},
            "detected_signals": {"supply_contract": 1},
        }
        result = self.evaluator.evaluate(summary=summary, normalized_items=[])

        flags = [flag["flag"] for flag in result["positive_flags"]]
        self.assertIn("business_event_detected", flags)
        self.assertIn("확정적 개선 판단은 보류", result["evaluation_summary"])

    def test_periodic_only_case_produces_neutral_flag(self):
        summary = {
            "total_disclosures": 1,
            "category_counts": {"periodic_report": 1},
            "detected_signals": {"periodic_reporting": 1},
        }
        result = self.evaluator.evaluate(summary=summary, normalized_items=[])

        flags = [flag["flag"] for flag in result["neutral_flags"]]
        self.assertIn("periodic_reporting_only", flags)


class DartValidationViewTests(TestCase):
    def setUp(self) -> None:
        self.client = Client()
        self.env_patcher = patch.dict(os.environ, {"DART_API_KEY": "test-key"}, clear=False)
        self.env_patcher.start()
        self.addCleanup(self.env_patcher.stop)

    @patch("apps.dart_analysis.views.DartClient.fetch_disclosure_list")
    @patch("apps.dart_analysis.views.CompanyNameResolver.resolve")
    def test_company_name_exact_resolution_success(self, mock_resolve, mock_fetch):
        mock_resolve.return_value = {
            "status": "resolved",
            "company_name": "삼성전자",
            "resolved_corp_code": "00126380",
            "resolved_corp_name": "삼성전자",
            "candidates": [{"corp_code": "00126380", "corp_name": "삼성전자", "stock_code": "005930"}],
            "match_rule": "exact_company_name",
        }
        mock_fetch.return_value = {
            "requested_window": {"bgn_de": "20260101", "end_de": "20260131"},
            "status": "000",
            "message": "정상",
            "total_count": 1,
            "items": [
                {
                    "rcept_no": "20260101000001",
                    "report_nm": "사업보고서",
                    "rcept_dt": "20260101",
                    "corp_code": "00126380",
                    "corp_name": "삼성전자",
                    "stock_code": "005930",
                }
            ],
        }

        response = self.client.get("/api/v1/dart/validate", {"company_name": "삼성전자"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["resolution"]["status"], "resolved")
        self.assertEqual(payload["input"]["corp_code"], "00126380")
        self.assertEqual(payload["disclosures"]["data"]["summary"]["total_disclosures"], 1)
        self.assertIn("implemented", payload["analysis"])
        mock_fetch.assert_called_once_with(corp_code="00126380", page_count=5)

    @patch("apps.dart_analysis.views.DartClient.fetch_disclosure_list")
    @patch("apps.dart_analysis.views.CompanyNameResolver.resolve")
    def test_unresolved_company_name_returns_structured_error(self, mock_resolve, mock_fetch):
        mock_resolve.return_value = {
            "status": "unresolved",
            "company_name": "없는회사",
            "resolved_corp_code": None,
            "resolved_corp_name": None,
            "candidates": [],
            "match_rule": "exact_company_name",
        }

        response = self.client.get("/api/v1/dart/validate", {"company_name": "없는회사"})

        self.assertEqual(response.status_code, 404)
        payload = response.json()
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "unresolved_company_name")
        mock_fetch.assert_not_called()

    @patch("apps.dart_analysis.views.DartClient.fetch_disclosure_list")
    @patch("apps.dart_analysis.views.CompanyNameResolver.resolve")
    def test_ambiguous_company_name_returns_structured_error(self, mock_resolve, mock_fetch):
        mock_resolve.return_value = {
            "status": "ambiguous",
            "company_name": "중복회사",
            "resolved_corp_code": None,
            "resolved_corp_name": None,
            "candidates": [
                {"corp_code": "00000001", "corp_name": "중복회사", "stock_code": ""},
                {"corp_code": "00000002", "corp_name": "중복회사", "stock_code": ""},
            ],
            "match_rule": "exact_company_name",
        }

        response = self.client.get("/api/v1/dart/validate", {"company_name": "중복회사"})

        self.assertEqual(response.status_code, 409)
        payload = response.json()
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "ambiguous_company_name")
        mock_fetch.assert_not_called()

    @patch("apps.dart_analysis.views.DartClient.fetch_disclosure_list")
    def test_direct_corp_code_behavior_is_preserved(self, mock_fetch):
        mock_fetch.return_value = {
            "requested_window": {"bgn_de": "20260101", "end_de": "20260131"},
            "status": "000",
            "message": "정상",
            "total_count": 1,
            "items": [
                {
                    "rcept_no": "20260101000001",
                    "report_nm": "유상증자 결정",
                    "rcept_dt": "20260101",
                    "corp_code": "00126380",
                    "corp_name": "테스트",
                    "stock_code": "005930",
                }
            ],
        }

        response = self.client.get("/api/v1/dart/validate", {"corp_code": "00126380"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["resolution"]["status"], "skipped")
        self.assertEqual(
            payload["disclosures"]["data"]["normalized_items"][0]["normalized"]["category"],
            "financing",
        )
        self.assertIn("risk_flags", payload["analysis"])
        self.assertIn("document_structure_signals", payload["analysis"])
        self.assertIn("document_structure_hints", payload["analysis"])
        self.assertIn("document_structure_enrichment", payload["disclosures"]["data"])
        mock_fetch.assert_called_once_with(corp_code="00126380", page_count=5)

    @patch("apps.dart_analysis.views.DartClient.fetch_original_document_payload")
    @patch("apps.dart_analysis.views.DartClient.fetch_disclosure_list")
    def test_validate_document_structure_enrichment_success_with_mock(self, mock_fetch_list, mock_fetch_doc):
        mock_fetch_list.return_value = {
            "requested_window": {"bgn_de": "20260101", "end_de": "20260131"},
            "status": "000",
            "message": "정상",
            "total_count": 1,
            "items": [
                {
                    "rcept_no": "20260101000001",
                    "report_nm": "사업보고서",
                    "rcept_dt": "20260101",
                    "corp_code": "00126380",
                    "corp_name": "테스트",
                    "stock_code": "005930",
                }
            ],
        }
        mock_fetch_doc.return_value = {
            "rcept_no": "20260101000001",
            "viewer_url": "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260101000001",
            "content_type": "application/zip",
            "content": _build_markup_with_heading_candidates_invalid_xml_zip_payload(),
        }

        response = self.client.get("/api/v1/dart/validate", {"corp_code": "00126380"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()

        enrichment = payload["disclosures"]["data"]["document_structure_enrichment"]
        self.assertTrue(enrichment["enabled"])
        self.assertEqual(enrichment["max_items_per_response"], 1)
        self.assertEqual(enrichment["attempted_item_count"], 1)
        self.assertEqual(len(enrichment["items"]), 1)
        signals = payload["analysis"]["document_structure_signals"]
        hints = payload["analysis"]["document_structure_hints"]
        self.assertTrue(signals["available"])
        self.assertTrue(hints["available"])
        self.assertIn("hint_flags", hints)
        self.assertIn("heading_candidates_present", hints["hint_flags"])
        self.assertIn("heading_candidate_count_preview", signals)
        self.assertIn("informational_notes", hints)
        self.assertNotIn("semantic_labels", signals)
        self.assertNotIn("semantic_labels", hints)
        item = enrichment["items"][0]
        self.assertTrue(item["inspection_attempted"])
        self.assertIn(item["status"], {"enriched", "no_structure_signal"})
        self.assertIn("heading_candidate_count", item)
        self.assertIn("heading_candidates_preview", item)
        self.assertNotIn("semantic_labels", item)

    @patch("apps.dart_analysis.views.DartClient.fetch_original_document_payload")
    @patch("apps.dart_analysis.views.DartClient.fetch_disclosure_list")
    def test_validate_document_structure_enrichment_failure_is_tolerated(self, mock_fetch_list, mock_fetch_doc):
        mock_fetch_list.return_value = {
            "requested_window": {"bgn_de": "20260101", "end_de": "20260131"},
            "status": "000",
            "message": "정상",
            "total_count": 1,
            "items": [
                {
                    "rcept_no": "20260101000001",
                    "report_nm": "사업보고서",
                    "rcept_dt": "20260101",
                    "corp_code": "00126380",
                    "corp_name": "테스트",
                    "stock_code": "005930",
                }
            ],
        }
        mock_fetch_doc.side_effect = DartAPIRequestError("DART API 네트워크 오류: 테스트")

        response = self.client.get("/api/v1/dart/validate", {"corp_code": "00126380"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        enrichment = payload["disclosures"]["data"]["document_structure_enrichment"]
        self.assertEqual(enrichment["attempted_item_count"], 1)
        self.assertEqual(enrichment["items"][0]["status"], "document_fetch_failed")
        self.assertIn("error", enrichment["items"][0])
        signals = payload["analysis"]["document_structure_signals"]
        hints = payload["analysis"]["document_structure_hints"]
        self.assertTrue(signals["available"])
        self.assertEqual(signals["enriched_item_count"], 0)
        self.assertFalse(signals["document_structure_available"])
        self.assertTrue(hints["available"])
        self.assertNotIn("semantic_labels", hints)

    def test_resolver_does_not_guess_non_exact_match(self):
        client = DartClient(api_key="dummy")
        resolver = CompanyNameResolver(dart_client=client)

        with patch.object(
            DartClient,
            "fetch_corp_code_records",
            return_value=[
                {"corp_code": "00126380", "corp_name": "삼성전자(주)", "stock_code": "005930", "modify_date": "20260101"}
            ],
        ):
            result = resolver.resolve("삼성전자")

        self.assertEqual(result["status"], "unresolved")

    def test_invalid_corp_code_returns_validation_error(self):
        response = self.client.get("/api/v1/dart/validate", {"corp_code": "123"})

        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "invalid_input")

    def test_missing_dart_api_key_returns_structured_error(self):
        with patch.dict(os.environ, {"DART_API_KEY": ""}, clear=False):
            response = self.client.get("/api/v1/dart/validate", {"company_name": "테스트"})

        self.assertEqual(response.status_code, 500)
        payload = response.json()
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "missing_dart_api_key")

    @patch("apps.dart_analysis.views.DartClient.fetch_disclosure_list")
    def test_live_fetch_failure_returns_structured_error(self, mock_fetch):
        mock_fetch.side_effect = DartAPIRequestError("DART API 네트워크 오류: 테스트")

        response = self.client.get("/api/v1/dart/validate", {"corp_code": "00126380"})

        self.assertEqual(response.status_code, 502)
        payload = response.json()
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "dart_list_fetch_failed")

    @patch("apps.dart_analysis.views.DartClient.fetch_original_document_payload")
    def test_original_document_fetch_success_with_mock(self, mock_fetch_doc):
        mock_fetch_doc.return_value = {
            "rcept_no": "20260101000001",
            "viewer_url": "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260101000001",
            "content_type": "application/zip",
            "content": _build_test_zip_payload(),
        }

        response = self.client.get("/api/v1/dart/document", {"rcept_no": "20260101000001"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["document_access"]["rcept_no"], "20260101000001")
        self.assertIn("zip_inspection", payload)
        self.assertIn("xml_inspection", payload)
        self.assertIn("xml_parse_diagnostics", payload)
        self.assertIn("xml_fallback_inspection", payload)
        self.assertIn("markup_fallback_inspection", payload)
        self.assertIn("document_outline", payload)
        self.assertIn("document_heading_candidates", payload)
        self.assertIsNone(payload["xml_parse_diagnostics"])
        self.assertIsNone(payload["xml_fallback_inspection"])
        self.assertIsNone(payload["markup_fallback_inspection"])
        self.assertIsNone(payload["document_outline"])
        self.assertIsNone(payload["document_heading_candidates"])

    @patch("apps.dart_analysis.views.DartClient.fetch_original_document_payload")
    def test_original_document_fetch_failure_returns_structured_error(self, mock_fetch_doc):
        mock_fetch_doc.side_effect = DartAPIRequestError("DART API 네트워크 오류: 테스트")

        response = self.client.get("/api/v1/dart/document", {"rcept_no": "20260101000001"})

        self.assertEqual(response.status_code, 502)
        payload = response.json()
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "original_document_fetch_failed")
        self.assertIn("markup_fallback_inspection", payload)
        self.assertIn("document_outline", payload)
        self.assertIn("document_heading_candidates", payload)
        self.assertIsNone(payload["markup_fallback_inspection"])
        self.assertIsNone(payload["document_outline"])
        self.assertIsNone(payload["document_heading_candidates"])

    @patch("apps.dart_analysis.views.DartClient.fetch_original_document_payload")
    def test_original_document_zip_inspection_failure_returns_structured_error(self, mock_fetch_doc):
        mock_fetch_doc.return_value = {
            "rcept_no": "20260101000001",
            "viewer_url": "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260101000001",
            "content_type": "application/octet-stream",
            "content": b"not-a-zip",
        }

        response = self.client.get("/api/v1/dart/document", {"rcept_no": "20260101000001"})

        self.assertEqual(response.status_code, 502)
        payload = response.json()
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "original_document_zip_inspection_failed")
        self.assertIn("markup_fallback_inspection", payload)
        self.assertIn("document_outline", payload)
        self.assertIn("document_heading_candidates", payload)
        self.assertIsNone(payload["markup_fallback_inspection"])
        self.assertIsNone(payload["document_outline"])
        self.assertIsNone(payload["document_heading_candidates"])

    @patch("apps.dart_analysis.views.DartClient.fetch_original_document_payload")
    def test_original_document_xml_fallback_success_returns_structured_response(self, mock_fetch_doc):
        mock_fetch_doc.return_value = {
            "rcept_no": "20260101000001",
            "viewer_url": "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260101000001",
            "content_type": "application/zip",
            "content": _build_invalid_xml_zip_payload(),
        }

        response = self.client.get("/api/v1/dart/document", {"rcept_no": "20260101000001"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertIn("xml_parse_diagnostics", payload)
        self.assertIsNone(payload["xml_inspection"]["root_tag"])
        self.assertIsNotNone(payload["xml_parse_diagnostics"]["parser_line"])
        self.assertIsNotNone(payload["xml_parse_diagnostics"]["parser_column"])
        self.assertIn("sanitized_excerpt", payload["xml_parse_diagnostics"])
        self.assertIn("xml_fallback_inspection", payload)
        self.assertTrue(payload["xml_fallback_inspection"]["fallback_parsing_succeeded"])
        self.assertEqual(payload["xml_fallback_inspection"]["root_tag"], "ROOT")
        self.assertIn("markup_fallback_inspection", payload)
        self.assertIn("document_outline", payload)
        self.assertIn("document_heading_candidates", payload)
        self.assertIsNone(payload["markup_fallback_inspection"])
        self.assertIsNone(payload["document_outline"])
        self.assertIsNone(payload["document_heading_candidates"])

    @patch("apps.dart_analysis.views.DartClient.fetch_original_document_payload")
    def test_original_document_markup_fallback_success_returns_structured_response(self, mock_fetch_doc):
        mock_fetch_doc.return_value = {
            "rcept_no": "20260101000001",
            "viewer_url": "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260101000001",
            "content_type": "application/zip",
            "content": _build_unrecoverable_invalid_xml_zip_payload(),
        }

        response = self.client.get("/api/v1/dart/document", {"rcept_no": "20260101000001"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertIn("xml_parse_diagnostics", payload)
        self.assertIn("xml_fallback_inspection", payload)
        self.assertIn("markup_fallback_inspection", payload)
        self.assertIn("document_outline", payload)
        self.assertIn("document_heading_candidates", payload)
        self.assertFalse(payload["xml_fallback_inspection"]["fallback_parsing_succeeded"])
        self.assertTrue(payload["markup_fallback_inspection"]["markup_fallback_succeeded"])
        self.assertTrue(payload["document_outline"]["outline_available"])
        self.assertIn("section_tag_names", payload["document_outline"])
        self.assertNotIn("semantic_sections", payload["document_outline"])
        self.assertTrue(payload["document_heading_candidates"]["extraction_attempted"])
        self.assertTrue(payload["document_heading_candidates"]["extraction_succeeded"])

    @patch("apps.dart_analysis.views.DartClient.fetch_original_document_payload")
    def test_original_document_heading_candidates_extraction_returns_raw_candidates(self, mock_fetch_doc):
        mock_fetch_doc.return_value = {
            "rcept_no": "20260101000001",
            "viewer_url": "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260101000001",
            "content_type": "application/zip",
            "content": _build_markup_with_heading_candidates_invalid_xml_zip_payload(),
        }

        response = self.client.get("/api/v1/dart/document", {"rcept_no": "20260101000001"})
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("document_heading_candidates", payload)
        heading_block = payload["document_heading_candidates"]
        self.assertTrue(heading_block["extraction_attempted"])
        self.assertTrue(heading_block["extraction_succeeded"])
        self.assertGreaterEqual(heading_block["heading_candidate_count"], 2)
        self.assertGreaterEqual(heading_block["deduplicated_heading_candidate_count"], 2)
        self.assertIn("title", heading_block["heading_like_tag_names_used"])
        self.assertNotIn("semantic_labels", heading_block)

    @patch("apps.dart_analysis.views.DartClient.fetch_original_document_payload")
    def test_original_document_xml_inspection_failure_returns_structured_error(self, mock_fetch_doc):
        mock_fetch_doc.return_value = {
            "rcept_no": "20260101000001",
            "viewer_url": "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260101000001",
            "content_type": "application/zip",
            "content": _build_non_markup_invalid_xml_zip_payload(),
        }

        response = self.client.get("/api/v1/dart/document", {"rcept_no": "20260101000001"})

        self.assertEqual(response.status_code, 502)
        payload = response.json()
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "original_document_xml_inspection_failed")
        self.assertTrue(
            {
                "document_access",
                "zip_inspection",
                "xml_inspection",
                "xml_parse_diagnostics",
                "xml_fallback_inspection",
                "markup_fallback_inspection",
                "document_outline",
                "document_heading_candidates",
            }.issubset(set(payload.keys()))
        )
        self.assertIn("xml_parse_diagnostics", payload)
        self.assertIsNone(payload["xml_inspection"])
        self.assertIn("xml_fallback_inspection", payload)
        self.assertIn("markup_fallback_inspection", payload)
        self.assertIn("document_outline", payload)
        self.assertIn("document_heading_candidates", payload)
        self.assertFalse(payload["xml_fallback_inspection"]["fallback_parsing_succeeded"])
        self.assertFalse(payload["markup_fallback_inspection"]["markup_fallback_succeeded"])
        self.assertFalse(payload["document_outline"]["outline_available"])
        self.assertFalse(payload["document_heading_candidates"]["extraction_succeeded"])

    @patch("apps.dart_analysis.views.DartClient.fetch_disclosure_list")
    def test_response_shape_is_preserved(self, mock_fetch):
        mock_fetch.return_value = {
            "requested_window": {"bgn_de": "20260101", "end_de": "20260131"},
            "status": "000",
            "message": "정상",
            "total_count": 1,
            "items": [
                {
                    "rcept_no": "20260101000001",
                    "report_nm": "사업보고서",
                    "rcept_dt": "20260101",
                    "corp_code": "00126380",
                    "corp_name": "테스트",
                    "stock_code": "005930",
                }
            ],
        }

        response = self.client.get("/api/v1/dart/validate", {"corp_code": "00126380"})
        payload = response.json()

        self.assertIn("input", payload)
        self.assertIn("resolution", payload)
        self.assertIn("dart_client", payload)
        self.assertIn("lookup_plan", payload)
        self.assertIn("disclosures", payload)
        self.assertIn("analysis", payload)
        self.assertIn("document_structure_signals", payload["analysis"])
        self.assertIn("document_structure_hints", payload["analysis"])
        self.assertIn("raw_items", payload["disclosures"]["data"])
        self.assertIn("normalized_items", payload["disclosures"]["data"])
        self.assertIn("summary", payload["disclosures"]["data"])
        self.assertIn("original_document_access", payload["disclosures"]["data"])
        self.assertIn("document_structure_enrichment", payload["disclosures"]["data"])
