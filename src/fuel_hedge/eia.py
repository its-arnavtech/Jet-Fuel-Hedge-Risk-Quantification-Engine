"""EIA API v2 petroleum spot client with bounded, credential-safe requests."""

from dataclasses import dataclass
from datetime import date, datetime, timezone
import json
import socket
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ENDPOINT = "https://api.eia.gov/v2/petroleum/pri/spt/data/"


@dataclass(frozen=True)
class Series:
    column: str
    units: str
    region: str


SERIES = {
    "EER_EPJK_PF4_RGC_DPG": Series("jet_fuel_gal", "Dollars per Gallon", "US Gulf Coast"),
    "RWTC": Series("wti_spot_bbl", "Dollars per Barrel", "Cushing Oklahoma"),
    "RBRTE": Series("brent_spot_bbl", "Dollars per Barrel", "Europe Brent"),
    "EER_EPD2F_PF4_Y35NY_DPG": Series("heating_oil_gal", "Dollars per Gallon", "New York Harbor"),
}


class EIAError(RuntimeError):
    """Safe error message which never includes request URLs or remote response bodies."""


def sanitize(value, secret: str):
    """EIA echoes api_key in the response. Strip credentials before persisting Bronze."""
    if isinstance(value, dict):
        return {k: sanitize(v, secret) for k, v in value.items()
                if k.lower().replace("-", "_") not in {"api_key", "apikey", "token", "authorization"}}
    if isinstance(value, list):
        return [sanitize(v, secret) for v in value]
    if isinstance(value, str) and secret:
        return value.replace(secret, "[REDACTED]")
    return value


class EIAClient:
    def __init__(self, api_key: str, *, timeout: float = 30, retries: int = 3,
                 page_size: int = 5000, opener=urlopen, sleeper=time.sleep):
        if not api_key.strip():
            raise ValueError("EIA_API_KEY is required for real price ingestion")
        if not 1 <= page_size <= 5000 or not 0 <= retries <= 8 or timeout <= 0:
            raise ValueError("Invalid EIA request limits")
        self._api_key = api_key
        self.timeout, self.retries, self.page_size = timeout, retries, page_size
        self._opener, self._sleep = opener, sleeper

    def _get(self, params: list[tuple[str, str]]) -> dict:
        url = ENDPOINT + "?" + urlencode([("api_key", self._api_key), *params])
        for attempt in range(self.retries + 1):
            try:
                req = Request(url, headers={"User-Agent": "jet-fuel-hedge-engine/0.1"})
                with self._opener(req, timeout=self.timeout) as response:
                    payload = json.load(response)
                if not isinstance(payload, dict) or "error" in payload:
                    raise EIAError("EIA returned an API error or invalid response")
                return sanitize(payload, self._api_key)
            except HTTPError as exc:
                if exc.code not in {429, 500, 502, 503, 504} or attempt == self.retries:
                    raise EIAError(f"EIA request failed (HTTP {exc.code})") from None
            except (URLError, TimeoutError, socket.timeout, OSError):
                if attempt == self.retries:
                    raise EIAError("EIA request failed after bounded network retries") from None
            except (ValueError, UnicodeError):
                raise EIAError("EIA returned malformed JSON") from None
            self._sleep(min(2 ** attempt, 30))
        raise EIAError("EIA request failed")

    def pages(self, start: str, end: str):
        start_dt, end_dt = date.fromisoformat(start), date.fromisoformat(end)
        if start_dt > end_dt:
            raise ValueError("start must be on or before end")
        offset = 0
        total_expected = None
        previous_keys = set()
        while True:
            params = [
                ("frequency", "daily"), ("data[0]", "value"),
                ("start", start), ("end", end), ("offset", str(offset)),
                ("length", str(self.page_size)),
                ("sort[0][column]", "period"), ("sort[0][direction]", "asc"),
                ("sort[1][column]", "series"), ("sort[1][direction]", "asc"),
                *(("facets[series][]", series) for series in SERIES),
            ]
            payload = self._get(params)
            response = payload.get("response", {})
            try:
                total = int(response["total"])
                rows = response["data"]
                if total < 0 or not isinstance(rows, list) or len(rows) > self.page_size:
                    raise ValueError
            except (KeyError, TypeError, ValueError):
                raise EIAError("EIA response lacks a valid total/data contract") from None
            if total_expected is not None and total != total_expected:
                raise EIAError("EIA total changed during pagination; retry the capture")
            total_expected = total
            if total == 0:
                raise EIAError("EIA returned no observations for the requested date range")
            if not rows:
                raise EIAError("EIA pagination ended before the advertised total")
            keys = set()
            for row in rows:
                if not isinstance(row, dict) or not isinstance(row.get("period"), str):
                    raise EIAError("EIA returned a malformed observation")
                key = (row["period"], row.get("series"))
                if not start <= row["period"] <= end or row.get("series") not in SERIES:
                    raise EIAError("EIA returned an out-of-contract date or series")
                if key in keys or key in previous_keys:
                    raise EIAError("EIA returned duplicate observations across pages")
                keys.add(key)
            previous_keys.update(keys)
            yield {
                "source": "EIA", "endpoint": ENDPOINT, "frequency": "daily",
                "start": start, "end": end, "offset": offset,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "payload": payload,
            }
            offset += len(rows)
            if offset >= total:
                if offset != total:
                    raise EIAError("EIA returned more observations than advertised")
                return
            self._sleep(0.25)
