from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from io import BytesIO
from copy import deepcopy
import time
from typing import Any, ClassVar
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import json
import zipfile
import xml.etree.ElementTree as ET

from core.env import get_dart_api_key, get_env_float, get_env_int


class DartClientError(RuntimeError):
    """Base exception for DART client errors."""


class DartAPIRequestError(DartClientError):
    """Raised when DART API request fails or returns an error status."""


@dataclass(slots=True)
class DartClient:
    api_key: str
    base_url: str = "https://opendart.fss.or.kr/api"
    timeout_seconds: float = 20.0
    max_retries: int = 1
    enable_cache: bool = True
    corp_code_cache_ttl_seconds: int = 60 * 60 * 24
    disclosure_list_cache_ttl_seconds: int = 60 * 10
    original_document_cache_ttl_seconds: int = 60 * 10
    _runtime_status: dict[str, Any] = field(init=False, repr=False)

    _CACHE_STORE: ClassVar[dict[str, tuple[float, Any]]] = {}

    def __post_init__(self) -> None:
        self._runtime_status: dict[str, Any] = {
            "cache": {"hits": 0, "misses": 0, "writes": 0, "last_key": None},
            "upstream": {"last_request": None, "last_error": None, "last_retry_count": 0},
        }

    @classmethod
    def from_env(cls) -> "DartClient":
        return cls(
            api_key=get_dart_api_key(),
            timeout_seconds=get_env_float("DART_TIMEOUT_SECONDS", 20.0, min_value=1.0),
            max_retries=get_env_int("DART_MAX_RETRIES", 1, min_value=0),
            corp_code_cache_ttl_seconds=get_env_int("DART_CORP_CODE_CACHE_TTL_SECONDS", 60 * 60 * 24, min_value=1),
            disclosure_list_cache_ttl_seconds=get_env_int("DART_DISCLOSURE_LIST_CACHE_TTL_SECONDS", 60 * 10, min_value=1),
            original_document_cache_ttl_seconds=get_env_int("DART_ORIGINAL_DOCUMENT_CACHE_TTL_SECONDS", 60 * 10, min_value=1),
            enable_cache=get_env_int("DART_ENABLE_CACHE", 1, min_value=0) != 0,
        )

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
        cache_key = "corp_code_records:v1"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

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
        self._cache_set(cache_key, records, ttl_seconds=self.corp_code_cache_ttl_seconds)
        return records


    def build_viewer_url(self, rcept_no: str) -> str:
        return f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"


    def fetch_original_document_payload(self, rcept_no: str) -> dict[str, Any]:
        if not rcept_no:
            raise DartClientError("rcept_no가 필요합니다.")
        cache_key = f"document_payload:{rcept_no}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        params = {
            "crtfc_key": self.api_key,
            "rcept_no": rcept_no,
        }
        content, meta = self._request_bytes_with_meta("/document.xml", params)
        payload = {
            "rcept_no": rcept_no,
            "viewer_url": self.build_viewer_url(rcept_no),
            "content_type": meta.get("content_type", ""),
            "content": content,
        }
        self._cache_set(cache_key, payload, ttl_seconds=self.original_document_cache_ttl_seconds)
        return payload

    def fetch_original_document_metadata(self, rcept_no: str) -> dict[str, Any]:
        payload = self.fetch_original_document_payload(rcept_no=rcept_no)
        return {
            "rcept_no": payload["rcept_no"],
            "viewer_url": payload["viewer_url"],
            "content_type": payload["content_type"],
            "byte_size": len(payload["content"]),
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
        cache_key = f"disclosure_list:{corp_code}:{page_count}:{window_days}:{today.strftime('%Y%m%d')}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached
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
            result = {
                "requested_window": {
                    "bgn_de": params["bgn_de"],
                    "end_de": params["end_de"],
                },
                "status": status,
                "message": message,
                "total_count": 0,
                "items": [],
            }
            self._cache_set(cache_key, result, ttl_seconds=self.disclosure_list_cache_ttl_seconds)
            return result

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

        result = {
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
        self._cache_set(cache_key, result, ttl_seconds=self.disclosure_list_cache_ttl_seconds)
        return result

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
        retryable_http_codes = {429, 500, 502, 503, 504}
        attempts = self.max_retries + 1
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                with urlopen(request, timeout=self.timeout_seconds) as response:
                    content_type = response.headers.get("Content-Type", "")
                    self._runtime_status["upstream"]["last_request"] = {
                        "path": path,
                        "attempt_count": attempt,
                        "timeout_seconds": self.timeout_seconds,
                        "result": "success",
                    }
                    self._runtime_status["upstream"]["last_error"] = None
                    self._runtime_status["upstream"]["last_retry_count"] = max(0, attempt - 1)
                    return response.read(), {"content_type": content_type}
            except HTTPError as exc:
                last_error = exc
                if attempt < attempts and exc.code in retryable_http_codes:
                    continue
                self._runtime_status["upstream"]["last_request"] = {
                    "path": path,
                    "attempt_count": attempt,
                    "timeout_seconds": self.timeout_seconds,
                    "result": "failed",
                }
                self._runtime_status["upstream"]["last_error"] = {
                    "type": "http_error",
                    "code": exc.code,
                    "message": str(exc),
                }
                self._runtime_status["upstream"]["last_retry_count"] = max(0, attempt - 1)
                raise DartAPIRequestError(f"DART API HTTP 오류: {exc.code}") from exc
            except URLError as exc:
                last_error = exc
                if attempt < attempts:
                    continue
                self._runtime_status["upstream"]["last_request"] = {
                    "path": path,
                    "attempt_count": attempt,
                    "timeout_seconds": self.timeout_seconds,
                    "result": "failed",
                }
                self._runtime_status["upstream"]["last_error"] = {
                    "type": "network_error",
                    "message": str(exc.reason),
                }
                self._runtime_status["upstream"]["last_retry_count"] = max(0, attempt - 1)
                raise DartAPIRequestError(f"DART API 네트워크 오류: {exc.reason}") from exc

        raise DartAPIRequestError(f"DART API 요청 실패: {last_error}")

    def snapshot_upstream_status(self) -> dict[str, Any]:
        return {
            "timeout_seconds": self.timeout_seconds,
            "max_retries": self.max_retries,
            **deepcopy(self._runtime_status["upstream"]),
        }

    def snapshot_cache_status(self) -> dict[str, Any]:
        return {
            "enabled": self.enable_cache,
            "corp_code_cache_ttl_seconds": self.corp_code_cache_ttl_seconds,
            "disclosure_list_cache_ttl_seconds": self.disclosure_list_cache_ttl_seconds,
            "original_document_cache_ttl_seconds": self.original_document_cache_ttl_seconds,
            **deepcopy(self._runtime_status["cache"]),
        }

    @classmethod
    def clear_cache(cls) -> None:
        cls._CACHE_STORE.clear()

    def _cache_get(self, key: str) -> Any | None:
        if not self.enable_cache:
            return None
        item = self._CACHE_STORE.get(key)
        self._runtime_status["cache"]["last_key"] = key
        if item is None:
            self._runtime_status["cache"]["misses"] += 1
            return None
        expires_at, value = item
        if time.time() >= expires_at:
            self._runtime_status["cache"]["misses"] += 1
            self._CACHE_STORE.pop(key, None)
            return None
        self._runtime_status["cache"]["hits"] += 1
        return deepcopy(value)

    def _cache_set(self, key: str, value: Any, *, ttl_seconds: int) -> None:
        if not self.enable_cache:
            return
        self._CACHE_STORE[key] = (time.time() + max(1, ttl_seconds), deepcopy(value))
        self._runtime_status["cache"]["writes"] += 1
        self._runtime_status["cache"]["last_key"] = key
