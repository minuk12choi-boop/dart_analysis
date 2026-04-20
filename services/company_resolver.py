from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from clients.dart_client import DartClient


@dataclass(slots=True)
class CompanyNameResolver:
    dart_client: DartClient

    def resolve(self, company_name: str) -> dict[str, Any]:
        normalized_input = self._normalize(company_name)
        records = self.dart_client.fetch_corp_code_records()
        exact_matches = [
            record
            for record in records
            if self._normalize(record.get("corp_name", "")) == normalized_input
        ]

        if len(exact_matches) == 1:
            match = exact_matches[0]
            return {
                "status": "resolved",
                "company_name": company_name,
                "resolved_corp_code": match.get("corp_code"),
                "resolved_corp_name": match.get("corp_name"),
                "candidates": [self._candidate_payload(match)],
                "match_rule": "exact_company_name",
            }

        if len(exact_matches) > 1:
            return {
                "status": "ambiguous",
                "company_name": company_name,
                "resolved_corp_code": None,
                "resolved_corp_name": None,
                "candidates": [self._candidate_payload(item) for item in exact_matches],
                "match_rule": "exact_company_name",
            }

        return {
            "status": "unresolved",
            "company_name": company_name,
            "resolved_corp_code": None,
            "resolved_corp_name": None,
            "candidates": [],
            "match_rule": "exact_company_name",
        }

    def _normalize(self, value: str) -> str:
        # 최소/명시적 정규화: 앞뒤 공백 제거만 수행
        return value.strip()

    def _candidate_payload(self, record: dict[str, Any]) -> dict[str, Any]:
        return {
            "corp_code": record.get("corp_code"),
            "corp_name": record.get("corp_name"),
            "stock_code": record.get("stock_code"),
        }
