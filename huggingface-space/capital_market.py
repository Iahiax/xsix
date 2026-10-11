"""Read real Capital.com market candles and place only explicitly enabled demo orders."""

from __future__ import annotations

import json
import os
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

_ORIGINS = {
    "demo": "https://demo-api-capital.backend-capital.com",
}
_RESOLUTIONS = {"MINUTE", "MINUTE_5", "MINUTE_15", "MINUTE_30", "HOUR", "HOUR_4", "DAY", "WEEK"}


class CapitalMarketError(RuntimeError):
    """Safe provider error; never contains credentials or raw response bodies."""


class CapitalMarketClient:
    def __init__(self, env: dict[str, str] | None = None, timeout: float = 8.0):
        self._env = os.environ if env is None else env
        self._timeout = timeout
        self._session: tuple[str, str, float] | None = None

    @property
    def mode(self) -> str:
        return self._env.get("CAPITAL_API_MODE", "").strip().lower()

    def _credentials(self) -> tuple[str, str, str, str]:
        mode = self.mode
        if mode != "demo":
            raise CapitalMarketError("اضبط CAPITAL_API_MODE على demo لبيانات الحساب التجريبي.")
        api_key = self._env.get("CAPITAL_API_KEY", "").strip()
        identifier = self._env.get("CAPITAL_IDENTIFIER", "").strip()
        password = self._env.get("CAPITAL_PASSWORD", "")
        if not api_key or not identifier or not password:
            raise CapitalMarketError("بيانات Capital.com غير مهيأة في أسرار Space.")
        return mode, _ORIGINS[mode], api_key, identifier, password

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str | int] | None = None,
        body: dict[str, Any] | None = None,
        authenticated: bool = True,
        allow_demo_order: bool = False,
    ) -> tuple[dict[str, Any], dict[str, str]]:
        mode, origin, api_key, identifier, password = self._credentials()
        if method == "POST" and path == "/positions":
            if mode != "demo" or not allow_demo_order:
                raise CapitalMarketError("إرسال الأوامر محصور بحساب Capital.com التجريبي وبعد تفعيل الحماية.")
        elif method != "GET" and path != "/session":
            raise CapitalMarketError("طريقة الطلب غير مسموحة لهذا الموصل.")

        query = f"?{urlencode(params)}" if params else ""
        headers = {"X-CAP-API-KEY": api_key, "Accept": "application/json"}
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode("utf-8")
        if authenticated and path != "/session":
            cst, security_token = self._authenticate(mode, origin, api_key, identifier, password)
            headers["CST"] = cst
            headers["X-SECURITY-TOKEN"] = security_token
        request = Request(f"{origin}/api/v1{path}{query}", data=data, headers=headers, method=method)
        try:
            with urlopen(request, timeout=self._timeout) as response:
                payload = json.loads(response.read().decode("utf-8") or "{}")
                if not isinstance(payload, dict):
                    raise CapitalMarketError("أعاد Capital.com استجابة غير صالحة.")
                response_headers = {key.lower(): value for key, value in response.headers.items()}
                return payload, response_headers
        except HTTPError as error:
            if error.code in (401, 403):
                self._session = None
                raise CapitalMarketError("رفض Capital.com بيانات الدخول أو صلاحية الحساب.") from None
            if error.code == 429:
                raise CapitalMarketError("بلغ الاتصال حد الطلبات؛ انتظر قبل إعادة المحاولة.") from None
            raise CapitalMarketError(f"تعذر جلب بيانات Capital.com (HTTP {error.code}).") from None
        except (URLError, TimeoutError, json.JSONDecodeError):
            raise CapitalMarketError("تعذر الاتصال الآمن بـCapital.com أو قراءة استجابته.") from None

    def _authenticate(
        self, mode: str, origin: str, api_key: str, identifier: str, password: str
    ) -> tuple[str, str]:
        now = time.monotonic()
        if self._session and self._session[2] > now:
            return self._session[0], self._session[1]
        payload, headers = self._request(
            "POST",
            "/session",
            body={"identifier": identifier, "password": password, "encryptedPassword": False},
            authenticated=False,
        )
        cst = headers.get("cst")
        security_token = headers.get("x-security-token")
        if not cst or not security_token:
            raise CapitalMarketError("لم يصدر Capital.com رموز جلسة صالحة.")
        self._session = (cst, security_token, now + 8 * 60)
        return cst, security_token

    @staticmethod
    def _side_prices(value: Any) -> tuple[float, float, float] | None:
        if not isinstance(value, dict):
            return None
        bid, ask = value.get("bid"), value.get("ask")
        try:
            bid_number, ask_number = float(bid), float(ask)
        except (TypeError, ValueError):
            return None
        if bid_number <= 0 or ask_number <= 0 or ask_number < bid_number:
            return None
        return bid_number, ask_number, (bid_number + ask_number) / 2

    def search_markets(self, search_term: str) -> list[dict[str, Any]]:
        query = search_term.strip()
        if not query or len(query) > 80:
            raise CapitalMarketError("أدخل رمز سوق أو اسماً صالحاً.")
        payload, _ = self._request("GET", "/markets", params={"searchTerm": query})
        markets = payload.get("markets")
        return markets if isinstance(markets, list) else []

    def market_quote(self, epic: str) -> dict[str, Any]:
        if not epic or len(epic) > 64 or any(char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-." for char in epic):
            raise CapitalMarketError("رمز السوق Epic غير صالح.")
        payload, _ = self._request("GET", f"/markets/{epic}")
        market = payload.get("market")
        snapshot = market.get("snapshot") if isinstance(market, dict) else None
        if not isinstance(snapshot, dict):
            raise CapitalMarketError("لم يُرجع Capital.com عرض سعر لحظياً صالحاً.")
        market_status = snapshot.get("marketStatus")
        if market_status != "TRADEABLE":
            raise CapitalMarketError("السوق مغلق أو غير قابل للتداول حالياً.")
        try:
            bid, ask = float(snapshot.get("bid")), float(snapshot.get("offer"))
        except (TypeError, ValueError):
            raise CapitalMarketError("عرض السعر الحالي لا يحتوي سعري bid وoffer صالحين.") from None
        if bid <= 0 or ask < bid:
            raise CapitalMarketError("عرض السعر الحالي غير صالح.")
        return {
            "epic": epic,
            "bid": bid,
            "ask": ask,
            "mid": (bid + ask) / 2,
            "spread": ask - bid,
            "update_time": snapshot.get("updateTime"),
            "market_status": market_status,
            "source": "Capital.com demo API",
        }

    def fetch_candles(
        self, epic: str, resolution: str = "HOUR", max_bars: int = 500
    ) -> list[dict[str, Any]]:
        if not epic or len(epic) > 64 or any(char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-." for char in epic):
            raise CapitalMarketError("رمز السوق Epic غير صالح.")
        if resolution not in _RESOLUTIONS:
            raise CapitalMarketError("الإطار الزمني غير مدعوم من Capital.com.")
        if not 100 <= int(max_bars) <= 1_000:
            raise CapitalMarketError("عدد الشموع يجب أن يكون بين 100 و1000.")
        payload, _ = self._request(
            "GET",
            f"/prices/{epic}",
            params={"resolution": resolution, "max": int(max_bars)},
        )
        prices = payload.get("prices")
        if not isinstance(prices, list):
            raise CapitalMarketError("لم يُرجع Capital.com سلسلة أسعار تاريخية.")
        candles: list[dict[str, Any]] = []
        for item in prices:
            if not isinstance(item, dict):
                continue
            sides = [self._side_prices(item.get(f"{part}Price")) for part in ("open", "high", "low", "close")]
            if any(side is None for side in sides):
                continue
            open_side, high_side, low_side, close_side = sides
            assert open_side and high_side and low_side and close_side
            timestamp = item.get("snapshotTimeUTC") or item.get("snapshotTime")
            if not isinstance(timestamp, str):
                continue
            volume = item.get("lastTradedVolume")
            try:
                volume_value = None if volume is None else float(volume)
            except (TypeError, ValueError):
                volume_value = None
            candles.append(
                {
                    "timestamp": timestamp,
                    "open": open_side[2],
                    "high": high_side[2],
                    "low": low_side[2],
                    "close": close_side[2],
                    "volume": volume_value,
                    "spread": close_side[1] - close_side[0],
                    "bid_close": close_side[0],
                    "ask_close": close_side[1],
                }
            )
        candles.sort(key=lambda candle: candle["timestamp"])
        if len(candles) < 60:
            raise CapitalMarketError("أعاد المصدر أقل من 60 شمعة صالحة؛ لا يمكن تشغيل التحليل.")
        return candles

    def submit_demo_order(
        self,
        *,
        epic: str,
        direction: str,
        size: float,
        stop_level: float,
        profit_level: float,
    ) -> dict[str, Any]:
        if self.mode != "demo" or self._env.get("CAPITAL_DEMO_EXECUTION_ENABLED", "").lower() != "true":
            raise CapitalMarketError("تنفيذ أوامر العرض التجريبي غير مفعّل.")
        if direction not in {"BUY", "SELL"}:
            raise CapitalMarketError("اتجاه الصفقة غير صالح.")
        try:
            size_value, stop_value, profit_value = float(size), float(stop_level), float(profit_level)
        except (TypeError, ValueError):
            raise CapitalMarketError("حجم الصفقة ووقف الخسارة والهدف مطلوبة.") from None
        try:
            max_size = float(self._env.get("CAPITAL_DEMO_MAX_ORDER_SIZE", "0.01"))
        except (TypeError, ValueError):
            raise CapitalMarketError("حد حجم أمر Demo المضبوط غير صالح.") from None
        if not 0 < size_value <= max_size:
            raise CapitalMarketError("حجم الصفقة يتجاوز الحد الأقصى المضبوط للحساب التجريبي.")
        if stop_value <= 0 or profit_value <= 0:
            raise CapitalMarketError("يجب إرسال وقف خسارة وهدف صالحين.")
        payload, _ = self._request(
            "POST",
            "/positions",
            body={
                "epic": epic,
                "direction": direction,
                "size": size_value,
                "guaranteedStop": False,
                "stopLevel": stop_value,
                "profitLevel": profit_value,
            },
            allow_demo_order=True,
        )
        reference = payload.get("dealReference")
        if not isinstance(reference, str) or not reference:
            raise CapitalMarketError("لم يُرجع Capital.com مرجع تأكيد للطلب.")
        confirmation, _ = self._request("GET", f"/confirms/{reference}")
        return {
            "deal_reference_suffix": reference[-6:],
            "status": confirmation.get("dealStatus"),
            "confirmed": confirmation.get("dealStatus") == "ACCEPTED",
            "mode": "demo",
        }


capital_market_client = CapitalMarketClient()
