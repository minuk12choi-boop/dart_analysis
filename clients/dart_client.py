from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from io import BytesIO
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import json
import zipfile
import xml.etree.ElementTree as ET

from core.env import get_dart_api_key


class DartClientError(RuntimeError):
    """Base exception for DART client errors."""


class DartAPIRequestError(DartClientError):
    """Raised when DART API request fails or returns an error status."""


@dataclass(slots=True)
class DartClient:
    api_key: str
    base_url: str = "https://opendart.fss.or.kr/api"

    @classmethod
    def from_env(cls) -> "DartClient":
        return cls(api_key=get_dart_api_key())

    def readiness_payload(self) -> dict[str, Any]:
        return {
            "ready": True,
            "mode": "minimal-live-list-fetch",
            "description": "DART API 키 로딩 및 공시목록 최소 조회 경로가 준비되었습니다.",
        }

    def build_lookup_plan(
        self,
        company_name: str | None = None,
        corp_code: str | None = None,
    ) -> dict[str, Any]:
        return {
            "input": {
                "company_name": company_name,
                "corp_code": corp_code,
            },
            "planned_api": "corpCode.xml -> list.json",
            "implemented": True,
            "note": (
                "company_name 입력 시 corpCode.xml 기반 exact 매칭으로 corp_code를 해석합니다. "
                "해석 성공 시 list.json 최소 조회를 수행합니다."
            ),
        }

    def fetch_corp_code_records(self) -> list[dict[str, str]]:
        params = {"crtfc_key": self.api_key}
        raw_zip = self._request_bytes("/corpCode.xml", params)

        try:
            with zipfile.ZipFile(BytesIO(raw_zip)) as archive:
                xml_names = [name for name in archive.namelist() if name.lower().endswith(".xml")]
                if not xml_names:
                    raise DartAPIRequestError("DART corpCode 응답에서 XML 파일을 찾지 못했습니다.")
                xml_bytes = archive.read(xml_names[0])
        except zipfile.BadZipFile as exc:
            raise DartAPIRequestError("DART corpCode 응답 ZIP 파싱에 실패했습니다.") from exc

        try:
            root = ET.fromstring(xml_bytes)
        except ET.ParseError as exc:
            raise DartAPIRequestError("DART corpCode XML 파싱에 실패했습니다.") from exc

        records: list[dict[str, str]] = []
        for node in root.findall("list"):
            records.append(
                {
                    "corp_code": (node.findtext("corp_code") or "").strip(),
                    "corp_name": (node.findtext("corp_name") or "").strip(),
                    "stock_code": (node.findtext("stock_code") or "").strip(),
                    "modify_date": (node.findtext("modify_date") or "").strip(),
                }
            )
        return records


    def build_viewer_url(self, rcept_no: str) -> str:
        return f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"

    def fetch_original_document_metadata(self, rcept_no: str) -> dict[str, Any]:
        if not rcept_no:
            raise DartClientError("rcept_no가 필요합니다.")

        params = {
            "crtfc_key": self.api_key,
            "rcept_no": rcept_no,
        }
        content, meta = self._request_bytes_with_meta("/document.xml", params)
        content_type = meta.get("content_type", "")

        return {
            "rcept_no": rcept_no,
            "viewer_url": self.build_viewer_url(rcept_no),
            "content_type": content_type,
            "byte_size": len(content),
        }

    def fetch_disclosure_list(
        self,
        corp_code: str,
        page_count: int = 5,
        window_days: int = 30,
    ) -> dict[str, Any]:
        if not corp_code:
            raise DartClientError("corp_code가 필요합니다.")

        today = date.today()
        begin_date = today - timedelta(days=window_days)
        params = {
            "crtfc_key": self.api_key,
            "corp_code": corp_code,
            "bgn_de": begin_date.strftime("%Y%m%d"),
            "end_de": today.strftime("%Y%m%d"),
            "page_no": "1",
            "page_count": str(page_count),
        }
        payload = self._request_json("/list.json", params)

        status = payload.get("status")
        message = payload.get("message")

        if status == "013":
            return {
                "requested_window": {
                    "bgn_de": params["bgn_de"],
                    "end_de": params["end_de"],
                },
                "status": status,
                "message": message,
                "total_count": 0,
                "items": [],
            }

        if status != "000":
            raise DartAPIRequestError(f"DART list API 오류(status={status}, message={message})")

        items = payload.get("list", [])
        minimal_items = [
            {
                "rcept_no": item.get("rcept_no"),
                "report_nm": item.get("report_nm"),
                "rcept_dt": item.get("rcept_dt"),
                "corp_code": item.get("corp_code"),
                "corp_name": item.get("corp_name"),
                "stock_code": item.get("stock_code"),
            }
            for item in items
        ]

        return {
            "requested_window": {
                "bgn_de": params["bgn_de"],
                "end_de": params["end_de"],
            },
            "status": status,
            "message": message,
            "total_count": int(payload.get("total_count", 0)),
            "page_count": len(minimal_items),
            "items": minimal_items,
        }

    def _request_json(self, path: str, params: dict[str, str]) -> dict[str, Any]:
        raw = self._request_bytes(path, params)
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise DartAPIRequestError("DART API 응답 JSON 파싱에 실패했습니다.") from exc

    def _request_bytes(self, path: str, params: dict[str, str]) -> bytes:
        content, _ = self._request_bytes_with_meta(path, params)
        return content

    def _request_bytes_with_meta(self, path: str, params: dict[str, str]) -> tuple[bytes, dict[str, str]]:
        query = urlencode(params)
        url = f"{self.base_url}{path}?{query}"
        request = Request(url, headers={"Accept": "*/*"}, method="GET")
        try:
            with urlopen(request, timeout=20) as response:
                content_type = response.headers.get("Content-Type", "")
                return response.read(), {"content_type": content_type}
        except HTTPError as exc:
            raise DartAPIRequestError(f"DART API HTTP 오류: {exc.code}") from exc
        except URLError as exc:
            raise DartAPIRequestError(f"DART API 네트워크 오류: {exc.reason}") from exc
