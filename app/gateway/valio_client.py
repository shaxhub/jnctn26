"""Client for the Valio Aimo mock API: POST /price and POST /availability.

- Chunks product lists into requests of at most 1000 ids.
- Short in-memory TTL cache per (endpoint, date, product) so repeated agent calls do not hammer the
  API (it has undisclosed rate limits).
- Returns one merged dict per product: {"price": {...}|None, "availability": {...}|None}.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import date

import httpx

from .config import settings

MAX_IDS = 1000
_RETRY_STATUSES = {429, 500, 502, 503, 504}
_RETRY_DELAYS = (0.3, 0.6)


@dataclass
class RawOffers:
    time_now: str | None                           # server time from /availability (Helsinki, ISO 8601)
    requested_date: str
    products: dict[str, dict] = field(default_factory=dict)   # id -> {"price": ..., "availability": ...}


class ValioClient:
    def __init__(self, base_url: str | None = None, api_key: str | None = None, ttl_s: int | None = None):
        self.base_url = (base_url or settings.valio_base_url).rstrip("/")
        self.api_key = api_key or settings.valio_api_key
        self.ttl_s = settings.cache_ttl_s if ttl_s is None else ttl_s
        self._cache: dict[tuple, tuple[float, dict]] = {}
        self._time_now: dict[tuple[str, str], tuple[float, str | None]] = {}
        self._lock = threading.Lock()
        self._http = httpx.Client(timeout=20.0, headers={"X-API-Key": self.api_key})

    def _post(self, path: str, customer: str, day: str, ids: list[str]) -> dict:
        if not self.api_key:
            raise RuntimeError("VALIO_API_KEY is not set (copy .env.example to .env)")
        for attempt in range(len(_RETRY_DELAYS) + 1):
            try:
                r = self._http.post(f"{self.base_url}{path}", json={"customer": customer, "requestedDate": day, "products": ids})
                r.raise_for_status()
                return r.json()
            except (httpx.TimeoutException, httpx.TransportError):
                if attempt >= len(_RETRY_DELAYS):
                    raise
                time.sleep(_RETRY_DELAYS[attempt])
            except httpx.HTTPStatusError as e:
                if e.response.status_code not in _RETRY_STATUSES or attempt >= len(_RETRY_DELAYS):
                    raise
                time.sleep(_RETRY_DELAYS[attempt])
        raise RuntimeError("unreachable")  # pragma: no cover

    def _fetch(self, kind: str, ids: list[str], day: str, customer: str) -> dict[str, dict]:
        now = time.monotonic()
        out, missing = {}, []
        with self._lock:
            for pid in ids:
                hit = self._cache.get((customer, kind, day, pid))
                if hit and hit[0] > now:
                    out[pid] = hit[1]
                else:
                    missing.append(pid)
        for i in range(0, len(missing), MAX_IDS):
            chunk = missing[i : i + MAX_IDS]
            try:
                data = self._post(f"/{kind}", customer, day, chunk)
            except httpx.HTTPError:
                with self._lock:
                    if all((customer, kind, day, pid) in self._cache for pid in chunk):
                        for pid in chunk:
                            out[pid] = self._cache[(customer, kind, day, pid)][1]
                        continue
                raise
            fetched_at = time.monotonic()
            with self._lock:
                if kind == "availability":
                    self._time_now[(customer, day)] = (fetched_at + self.ttl_s, data.get("timeNow"))
                for item in data.get("products", []):
                    raw_pid = item.get("productId")
                    if raw_pid is None:
                        continue
                    pid = str(raw_pid)
                    self._cache[(customer, kind, day, pid)] = (fetched_at + self.ttl_s, item)
                    out[pid] = item
        return out

    def get_offers_raw(self, product_ids: list[str], delivery_date: date, customer: str | None = None) -> RawOffers:
        ids = list(dict.fromkeys(str(p) for p in product_ids))
        day = delivery_date.isoformat()
        customer = customer or settings.valio_customer_id
        prices = self._fetch("price", ids, day, customer)
        avail = self._fetch("availability", ids, day, customer)
        with self._lock:
            tn = self._time_now.get((customer, day))
        time_now = tn[1] if tn and tn[0] > time.monotonic() else None
        return RawOffers(time_now=time_now, requested_date=day,
                         products={pid: {"price": prices.get(pid), "availability": avail.get(pid)} for pid in ids})


_client: ValioClient | None = None
_client_lock = threading.Lock()


def get_client() -> ValioClient:
    global _client
    with _client_lock:
        if _client is None:
            _client = ValioClient()
    return _client
