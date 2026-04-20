from __future__ import annotations

import os
from unittest.mock import patch

from django.test import Client, TestCase

from clients.dart_client import DartAPIRequestError, DartClient
from services.company_resolver import CompanyNameResolver
from services.disclosure_normalizer import DisclosureNormalizer


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
        mock_fetch.assert_called_once_with(corp_code="00126380", page_count=5)

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
