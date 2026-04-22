from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
import json
import os
import statistics
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from core.env import get_env_float, get_env_int


@dataclass(slots=True)
class KISMarketDataProvider:
    app_key: str
    app_secret: str
    base_url: str
    timeout_seconds: float = 10.0
    max_retries: int = 1
    token_cache_ttl_seconds: int = 60 * 50
    snapshot_cache_ttl_seconds: int = 60

    _token_cache: dict[str, Any] | None = None
    _snapshot_cache: dict[str, tuple[float, dict[str, Any]]] | None = None

    def __post_init__(self) -> None:
        if self._snapshot_cache is None:
            self._snapshot_cache = {}

    @classmethod
    def from_env(cls) -> "KISMarketDataProvider | None":
        app_key = (os.getenv("KIS_APP_KEY") or "").strip()
        app_secret = (os.getenv("KIS_APP_SECRET") or "").strip()
        if not app_key or not app_secret:
            return None
        base_url = (os.getenv("KIS_BASE_URL") or "https://openapi.koreainvestment.com:9443").strip()
        return cls(
            app_key=app_key,
            app_secret=app_secret,
            base_url=base_url,
            timeout_seconds=get_env_float("KIS_TIMEOUT_SECONDS", 10.0, min_value=1.0),
            max_retries=get_env_int("KIS_MAX_RETRIES", 1, min_value=0),
            token_cache_ttl_seconds=get_env_int("KIS_TOKEN_CACHE_TTL_SECONDS", 60 * 50, min_value=30),
            snapshot_cache_ttl_seconds=get_env_int("KIS_SNAPSHOT_CACHE_TTL_SECONDS", 60, min_value=1),
        )

    def fetch_snapshot(self, *, stock_code: str | None) -> dict[str, Any]:
        normalized_code = (stock_code or "").strip()
        if len(normalized_code) != 6 or not normalized_code.isdigit():
            return {
                "configured": True,
                "live_fetch_succeeded": False,
                "insufficient_market_data": True,
                "available_fields": [],
                "unavailable_fields": ["stock_code", "current_price", "recent_low", "recent_high", "recent_volume"],
                "data": {},
                "message": "유효한 국내 6자리 종목코드가 없어 KIS 시세 조회를 수행하지 못했습니다.",
                "errors": [],
            }

        cached = self._cache_get(normalized_code)
        if cached is not None:
            return cached

        token = self._get_access_token()
        if not token:
            return {
                "configured": True,
                "live_fetch_succeeded": False,
                "insufficient_market_data": True,
                "available_fields": [],
                "unavailable_fields": ["current_price", "recent_low", "recent_high", "recent_volume", "volatility_proxy"],
                "data": {},
                "message": "KIS 토큰 발급에 실패해 시세 조회를 수행하지 못했습니다.",
                "errors": ["token_issue"],
            }

        current_quote, current_error = self._fetch_current_quote(token=token, stock_code=normalized_code)
        daily_quotes, daily_error = self._fetch_daily_quotes(token=token, stock_code=normalized_code)

        errors = []
        if current_error:
            errors.append(current_error)
        if daily_error:
            errors.append(daily_error)

        data = self._build_market_data(current_quote=current_quote, daily_quotes=daily_quotes)
        required_fields = ["current_price", "recent_low", "recent_high", "recent_volume"]
        unavailable_fields = [field for field in required_fields if data.get(field) is None]
        if data.get("volatility_proxy") is None:
            unavailable_fields.append("volatility_proxy")
        available_fields = [field for field in ["current_price", "recent_low", "recent_high", "recent_volume", "volatility_proxy"] if data.get(field) is not None]

        payload = {
            "configured": True,
            "live_fetch_succeeded": len(errors) == 0,
            "insufficient_market_data": len([f for f in required_fields if data.get(f) is None]) > 0,
            "available_fields": available_fields,
            "unavailable_fields": unavailable_fields,
            "data": data,
            "message": "KIS 국내주식 시세 데이터를 조회했습니다." if len(errors) == 0 else "KIS 조회 일부 실패로 사용 가능한 필드만 반영했습니다.",
            "errors": errors,
        }
        self._cache_set(normalized_code, payload)
        return payload

    def _get_access_token(self) -> str | None:
        now = time.time()
        if self._token_cache and now < self._token_cache.get("expires_at", 0):
            return str(self._token_cache.get("token") or "") or None

        body = json.dumps(
            {
                "grant_type": "client_credentials",
                "appkey": self.app_key,
                "appsecret": self.app_secret,
            }
        ).encode("utf-8")
        request = Request(
            f"{self.base_url}/oauth2/tokenP",
            data=body,
            headers={"content-type": "application/json"},
            method="POST",
        )

        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
            return None

        token = str(payload.get("access_token") or "").strip()
        if not token:
            return None
        self._token_cache = {
            "token": token,
            "expires_at": now + self.token_cache_ttl_seconds,
        }
        return token

    def _fetch_current_quote(self, *, token: str, stock_code: str) -> tuple[dict[str, Any] | None, str | None]:
        params = {
            "fid_cond_mrkt_div_code": "J",
            "fid_input_iscd": stock_code,
        }
        headers = {
            "authorization": f"Bearer {token}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": "FHKST01010100",
        }
        payload, error = self._request_json(path="/uapi/domestic-stock/v1/quotations/inquire-price", params=params, headers=headers)
        if error:
            return None, error
        output = payload.get("output", {}) if isinstance(payload.get("output"), dict) else {}
        return output, None

    def _fetch_daily_quotes(self, *, token: str, stock_code: str) -> tuple[list[dict[str, Any]], str | None]:
        today = date.today()
        begin = today - timedelta(days=30)
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": stock_code,
            "FID_INPUT_DATE_1": begin.strftime("%Y%m%d"),
            "FID_INPUT_DATE_2": today.strftime("%Y%m%d"),
            "FID_PERIOD_DIV_CODE": "D",
            "FID_ORG_ADJ_PRC": "1",
        }
        headers = {
            "authorization": f"Bearer {token}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": "FHKST03010100",
        }
        payload, error = self._request_json(path="/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice", params=params, headers=headers)
        if error:
            return [], error
        output = payload.get("output2", [])
        if not isinstance(output, list):
            return [], "daily_output_invalid"
        rows = [row for row in output if isinstance(row, dict)]
        return rows, None

    def _request_json(self, *, path: str, params: dict[str, str], headers: dict[str, str]) -> tuple[dict[str, Any], str | None]:
        query = urlencode(params)
        url = f"{self.base_url}{path}?{query}"

        for attempt in range(self.max_retries + 1):
            request = Request(url, headers=headers, method="GET")
            try:
                with urlopen(request, timeout=self.timeout_seconds) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                    return payload if isinstance(payload, dict) else {}, None
            except HTTPError as exc:
                if attempt >= self.max_retries:
                    return {}, f"http_{exc.code}"
            except URLError:
                if attempt >= self.max_retries:
                    return {}, "network_error"
            except (TimeoutError, json.JSONDecodeError):
                if attempt >= self.max_retries:
                    return {}, "decode_or_timeout_error"
        return {}, "unknown_error"

    def _build_market_data(self, *, current_quote: dict[str, Any] | None, daily_quotes: list[dict[str, Any]]) -> dict[str, Any]:
        def _to_float(value: Any) -> float | None:
            if value is None:
                return None
            raw = str(value).replace(",", "").strip()
            if raw == "":
                return None
            try:
                return float(raw)
            except ValueError:
                return None

        current_price = _to_float((current_quote or {}).get("stck_prpr"))
        current_volume = _to_float((current_quote or {}).get("acml_vol"))

        highs = [_to_float(row.get("stck_hgpr")) for row in daily_quotes[:20]]
        lows = [_to_float(row.get("stck_lwpr")) for row in daily_quotes[:20]]
        closes = [_to_float(row.get("stck_clpr")) for row in daily_quotes[:20]]
        volumes = [_to_float(row.get("acml_vol")) for row in daily_quotes[:20]]

        highs = [v for v in highs if isinstance(v, float) and v > 0]
        lows = [v for v in lows if isinstance(v, float) and v > 0]
        closes = [v for v in closes if isinstance(v, float) and v > 0]
        volumes = [v for v in volumes if isinstance(v, float) and v > 0]

        recent_high = max(highs) if highs else None
        recent_low = min(lows) if lows else None
        recent_volume = current_volume if current_volume is not None else (volumes[0] if volumes else None)

        volatility_proxy = None
        if len(closes) >= 5:
            mean_price = statistics.mean(closes)
            if mean_price > 0:
                volatility_proxy = round(statistics.pstdev(closes) / mean_price, 6)

        return {
            "current_price": current_price,
            "recent_low": recent_low,
            "recent_high": recent_high,
            "recent_volume": recent_volume,
            "volatility_proxy": volatility_proxy,
            "market_cap": None,
            "share_count": None,
        }

    def _cache_get(self, stock_code: str) -> dict[str, Any] | None:
        if self._snapshot_cache is None:
            return None
        cached = self._snapshot_cache.get(stock_code)
        if cached is None:
            return None
        expires_at, payload = cached
        if time.time() >= expires_at:
            self._snapshot_cache.pop(stock_code, None)
            return None
        return payload

    def _cache_set(self, stock_code: str, payload: dict[str, Any]) -> None:
        if self._snapshot_cache is None:
            self._snapshot_cache = {}
        self._snapshot_cache[stock_code] = (time.time() + self.snapshot_cache_ttl_seconds, payload)


@dataclass(slots=True)
class MarketDataProvider:
    provider_name: str = "none"

    @classmethod
    def from_env(cls) -> "MarketDataProvider":
        provider_name = (os.getenv("DART_MARKET_DATA_PROVIDER", "none") or "none").strip().lower()
        return cls(provider_name=provider_name or "none")

    def fetch_snapshot(self, *, corp_code: str | None, stock_code: str | None) -> dict[str, Any]:
        if self.provider_name == "kis":
            kis = KISMarketDataProvider.from_env()
            if kis is None:
                return {
                    "provider": "kis",
                    "configured": False,
                    "live_fetch_succeeded": False,
                    "available": False,
                    "insufficient_market_data": True,
                    "available_fields": [],
                    "unavailable_fields": ["current_price", "recent_low", "recent_high", "recent_volume", "volatility_proxy"],
                    "data": {},
                    "message": "KIS_APP_KEY 또는 KIS_APP_SECRET이 설정되지 않아 KIS 시세 조회를 수행하지 못했습니다.",
                    "lookup": {"corp_code": corp_code, "stock_code": stock_code},
                    "errors": ["missing_kis_credentials"],
                }
            payload = kis.fetch_snapshot(stock_code=stock_code)
            return {
                "provider": "kis",
                "configured": payload.get("configured", True),
                "live_fetch_succeeded": payload.get("live_fetch_succeeded", False),
                "available": not payload.get("insufficient_market_data", True),
                "insufficient_market_data": payload.get("insufficient_market_data", True),
                "available_fields": payload.get("available_fields", []),
                "unavailable_fields": payload.get("unavailable_fields", []),
                "data": payload.get("data", {}),
                "message": payload.get("message"),
                "lookup": {"corp_code": corp_code, "stock_code": stock_code},
                "errors": payload.get("errors", []),
            }

        if self.provider_name == "static":
            current_price = get_env_float("DART_MARKET_PRICE_CURRENT", -1.0)
            recent_low = get_env_float("DART_MARKET_PRICE_RECENT_LOW", -1.0)
            recent_high = get_env_float("DART_MARKET_PRICE_RECENT_HIGH", -1.0)
            recent_volume = get_env_float("DART_MARKET_RECENT_VOLUME", -1.0)
            volatility_proxy = get_env_float("DART_MARKET_VOLATILITY_PROXY", -1.0)
            market_cap = get_env_float("DART_MARKET_CAP", -1.0)
            share_count = get_env_float("DART_MARKET_SHARE_COUNT", -1.0)

            values = {
                "current_price": current_price if current_price > 0 else None,
                "recent_low": recent_low if recent_low > 0 else None,
                "recent_high": recent_high if recent_high > 0 else None,
                "recent_volume": recent_volume if recent_volume > 0 else None,
                "volatility_proxy": volatility_proxy if volatility_proxy > 0 else None,
                "market_cap": market_cap if market_cap > 0 else None,
                "share_count": share_count if share_count > 0 else None,
            }
            required_fields = ["current_price", "recent_low", "recent_high", "recent_volume"]
            unavailable_fields = [key for key in required_fields if values.get(key) is None]
            if values.get("volatility_proxy") is None:
                unavailable_fields.append("volatility_proxy")

            return {
                "provider": "static",
                "configured": True,
                "live_fetch_succeeded": True,
                "available": len([k for k in required_fields if values.get(k) is None]) == 0,
                "insufficient_market_data": len([k for k in required_fields if values.get(k) is None]) > 0,
                "available_fields": [key for key, value in values.items() if value is not None],
                "unavailable_fields": unavailable_fields,
                "data": values,
                "message": "환경변수 기반 정적 시장 데이터 스냅샷을 사용합니다.",
                "lookup": {"corp_code": corp_code, "stock_code": stock_code},
                "errors": [],
            }

        return {
            "provider": self.provider_name,
            "configured": False,
            "live_fetch_succeeded": False,
            "available": False,
            "insufficient_market_data": True,
            "available_fields": [],
            "unavailable_fields": ["current_price", "recent_low", "recent_high", "recent_volume", "volatility_proxy"],
            "data": {},
            "message": "시장 데이터 공급자가 설정되지 않아 가격 판단을 제한합니다.",
            "lookup": {"corp_code": corp_code, "stock_code": stock_code},
            "errors": ["provider_not_configured"],
        }
