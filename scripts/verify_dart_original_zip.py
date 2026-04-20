from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from clients.dart_client import DartAPIRequestError, DartClient
from core.env import MissingDartApiKeyError
from services.document_zip_inspector import DocumentZipInspectionError, DocumentZipInspector


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fetch one real DART disclosure and inspect original document ZIP entries.",
    )
    parser.add_argument("--corp-code", default="00126380", help="DART corp_code (8 digits)")
    parser.add_argument("--page-count", type=int, default=5, help="Number of list items to request")
    parser.add_argument("--window-days", type=int, default=365, help="Recent window in days")
    return parser


def run(corp_code: str, page_count: int, window_days: int) -> dict[str, Any]:
    client = DartClient.from_env()

    disclosure_list = client.fetch_disclosure_list(
        corp_code=corp_code,
        page_count=page_count,
        window_days=window_days,
    )
    items = disclosure_list.get("items", [])
    if not items:
        return {
            "selected_corp_code": corp_code,
            "selected_rcept_no": None,
            "download_succeeded": False,
            "valid_zip": False,
            "zip_entry_count": 0,
            "zip_entry_names": [],
            "message": "조회 기간 내 공시 항목이 없습니다.",
        }

    rcept_no = items[0].get("rcept_no")
    if not rcept_no:
        return {
            "selected_corp_code": corp_code,
            "selected_rcept_no": None,
            "download_succeeded": False,
            "valid_zip": False,
            "zip_entry_count": 0,
            "zip_entry_names": [],
            "message": "조회된 공시 항목에 rcept_no가 없습니다.",
        }

    payload = client.fetch_original_document_payload(rcept_no=str(rcept_no))
    inspector = DocumentZipInspector()

    try:
        zip_result = inspector.inspect(payload["content"])
        valid_zip = True
        entry_count = zip_result.get("entry_count", 0)
        entry_names = [entry.get("name") for entry in zip_result.get("entries", [])]
        message = "원문 payload 다운로드 및 ZIP 검사에 성공했습니다."
    except DocumentZipInspectionError as exc:
        valid_zip = False
        entry_count = 0
        entry_names = []
        message = f"원문 payload는 다운로드되었지만 ZIP 검사에 실패했습니다: {exc}"

    return {
        "selected_corp_code": corp_code,
        "selected_rcept_no": str(rcept_no),
        "download_succeeded": True,
        "valid_zip": valid_zip,
        "zip_entry_count": entry_count,
        "zip_entry_names": entry_names,
        "message": message,
    }


def main() -> int:
    args = build_parser().parse_args()
    try:
        result = run(
            corp_code=args.corp_code,
            page_count=args.page_count,
            window_days=args.window_days,
        )
    except MissingDartApiKeyError as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    except DartAPIRequestError as exc:
        print(
            json.dumps(
                {
                    "error": "DART API 호출 실패",
                    "detail": str(exc),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
