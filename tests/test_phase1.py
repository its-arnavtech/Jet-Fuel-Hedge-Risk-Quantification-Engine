from contextlib import contextmanager
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

import numpy as np
import pandas as pd

from fuel_hedge.bronze import capture, read_completed
from fuel_hedge.config import Settings, identifier, load_env
from fuel_hedge.eia import EIAClient, EIAError, SERIES
from fuel_hedge.silver import build_silver, weekly_prices

JET = "EER_EPJK_PF4_RGC_DPG"


def row(dt="2025-01-03", series=JET, value="2.5", units=None):
    return {"period": dt, "series": series, "value": value,
            "units": units or SERIES[series].units}


def event(rows, fetched="2025-07-01T00:00:00+00:00", event_id="one"):
    return {"payload": {"response": {"data": rows}}, "fetched_at": fetched,
            "event_id": event_id, "capture_id": "capture"}


@contextmanager
def response(payload):
    yield io.StringIO(json.dumps(payload))


class ConfigTests(unittest.TestCase):
    def test_literals_precedence_and_secret_repr(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            path = Path(directory) / ".env"
            path.write_text('EIA_API_KEY="literal$(secret)"\nDATABRICKS_TOKEN=private\n')
            load_env(path)
            self.assertEqual(Settings.from_env().eia_api_key, "literal$(secret)")
            self.assertNotIn("private", repr(Settings.from_env()))
            os.environ["EIA_API_KEY"] = "process-wins"
            load_env(path)
            self.assertEqual(Settings.from_env().eia_api_key, "process-wins")

    def test_host_and_identifier_validation(self):
        for host in ["http://dbc-a.cloud.databricks.com", "https://evil.com",
                     "https://dbc-a.cloud.databricks.com/path",
                     "https://dbc-a.cloud.databricks.com.evil.com",
                     "https://user:pass@dbc-a.cloud.databricks.com"]:
            with patch.dict(os.environ, {"DATABRICKS_HOST": host}, clear=True):
                with self.assertRaises(ValueError):
                    Settings.from_env()
        with self.assertRaises(ValueError):
            identifier("workspace; DROP SCHEMA gold")


class EIATests(unittest.TestCase):
    def test_pagination_and_echo_redaction(self):
        pages = [
            {"response": {"total": "2", "data": [row()]},
             "request": {"params": {"api_key": "hidden"}}, "note": "hidden"},
            {"response": {"total": "2", "data": [row("2025-01-06")]}}]
        calls = []

        def opener(req, timeout):
            calls.append(req.full_url)
            self.assertEqual(timeout, 30)
            return response(pages.pop(0))

        result = list(EIAClient("hidden", page_size=1, opener=opener, sleeper=lambda _: None)
                      .pages("2025-01-01", "2025-01-10"))
        self.assertEqual([p["offset"] for p in result], [0, 1])
        self.assertNotIn("hidden", json.dumps(result))
        self.assertIn("sort%5B1%5D%5Bcolumn%5D=series", calls[0])

    def test_safe_retry_and_http_error(self):
        attempts, sleeps = [], []

        def opener(req, timeout):
            attempts.append(1)
            raise URLError("https://example.com?api_key=hidden")

        with self.assertRaises(EIAError) as raised:
            list(EIAClient("hidden", retries=2, opener=opener, sleeper=sleeps.append)
                 .pages("2025-01-01", "2025-01-10"))
        self.assertEqual(len(attempts), 3)
        self.assertEqual(sleeps, [1, 2])
        self.assertNotIn("hidden", str(raised.exception))

        def forbidden(req, timeout):
            raise HTTPError(req.full_url, 403, "secret remote message", None, None)

        with self.assertRaisesRegex(EIAError, "HTTP 403"):
            list(EIAClient("hidden", opener=forbidden, sleeper=lambda _: self.fail("no retry"))
                 .pages("2025-01-01", "2025-01-10"))

    def test_invalid_pagination_contract(self):
        for payload in [{"response": {"total": 2, "data": []}},
                        {"response": {"total": 0, "data": []}},
                        {"error": "bad key hidden"},
                        {"response": {"total": 1, "data": [row("2024-01-01")]}}]:
            with self.subTest(payload=payload), self.assertRaises(EIAError):
                list(EIAClient("hidden", opener=lambda *a, **k: response(payload))
                     .pages("2025-01-01", "2025-01-10"))

    def test_duplicate_pages_and_changed_total(self):
        for second in [{"total": 2, "data": [row()]},
                       {"total": 3, "data": [row("2025-01-06")]}]:
            replies = [{"response": {"total": 2, "data": [row()]}}, {"response": second}]
            with self.assertRaises(EIAError):
                list(EIAClient("key", page_size=1,
                               opener=lambda *a, **k: response(replies.pop(0)), sleeper=lambda _: None)
                     .pages("2025-01-01", "2025-01-10"))


class BronzeTests(unittest.TestCase):
    def test_replay_integrity_and_failed_capture_isolation(self):
        page = {"source": "EIA", "fetched_at": datetime.now(timezone.utc).isoformat(),
                "payload": {"response": {"data": [row()]}}}

        class Client:
            def pages(self, start, end):
                yield page

        class FailedClient:
            def pages(self, start, end):
                yield page
                raise EIAError("later page failed")

        with tempfile.TemporaryDirectory() as directory:
            capture(Client(), "2025-01-01", "2025-01-10", directory)
            self.assertEqual(len(read_completed(directory)), 1)
            with self.assertRaises(EIAError):
                capture(FailedClient(), "2025-01-01", "2025-01-10", directory)
            self.assertEqual(len(read_completed(directory)), 1)
            capture(Client(), "2025-01-01", "2025-01-10", directory)
            self.assertEqual(len(read_completed(directory)), 2)
            path = next((Path(directory) / "events").glob("*.json"))
            data = json.loads(path.read_text())
            # Tamper only with a completed event.
            for p in (Path(directory) / "events").glob("*.json"):
                data = json.loads(p.read_text())
                if data["capture_id"] in {e["capture_id"] for e in read_completed(directory)}:
                    data["payload"]["response"]["data"][0]["value"] = "999"
                    p.write_text(json.dumps(data))
                    break
            with self.assertRaisesRegex(ValueError, "integrity"):
                read_completed(directory)


class SilverTests(unittest.TestCase):
    def test_units_latest_revision_sparse_proxy_and_crack(self):
        first = event([row(), row(series="RWTC", value="84"), row("2025-01-06")])
        revised = event([row(value="3.0"), row("2025-01-06", series="RWTC", units="cents")],
                        fetched="2025-07-02T00:00:00+00:00", event_id="two")
        prices, rejected = build_silver([revised, first, first])
        self.assertEqual(len(prices), 2)
        self.assertEqual(prices.iloc[0].jet_fuel_gal, 3)
        self.assertEqual(prices.iloc[0].crack_spread, 1)
        self.assertTrue(np.isnan(prices.iloc[1].wti_spot_bbl))
        self.assertEqual(rejected.iloc[0].reason, "unit_mismatch")
        self.assertAlmostEqual(prices.iloc[1].log_return, np.log(2.5 / 3))
        self.assertFalse(prices.is_synthetic.any())

    def test_withdrawn_latest_value_is_not_resurrected(self):
        old = event([row(), row("2025-01-06")])
        new = event([row(value=None)], fetched="2025-07-02T00:00:00+00:00", event_id="two")
        prices, rejected = build_silver([old, new])
        self.assertEqual(len(prices), 1)
        self.assertEqual(str(prices.iloc[0].price_date.date()), "2025-01-06")
        self.assertEqual(rejected.iloc[0].reason, "missing_or_invalid_price")

    def test_negative_wti_valid_nonpositive_jet_rejected(self):
        prices, rejected = build_silver([event([row(), row(series="RWTC", value="-37"),
                                                    row("2025-01-06", value="0")])])
        self.assertEqual(prices.iloc[0].wti_spot_bbl, -37)
        self.assertEqual(len(rejected), 1)

    def test_calendar_window_and_pearson(self):
        dates = pd.bdate_range("2024-01-01", periods=150)
        rows = []
        for i, dt in enumerate(dates):
            rows.extend([row(str(dt.date()), value=str(2 + i / 100)),
                         row(str(dt.date()), series="RWTC", value=str(40 + i))])
        prices, _ = build_silver([event(rows)])
        self.assertAlmostEqual(prices.iloc[-1].rolling_corr_90d, 1)
        reference = prices.set_index("price_date").log_return.rolling("90D", min_periods=20).std() * np.sqrt(252)
        self.assertAlmostEqual(prices.iloc[-1].rolling_vol_90d, reference.iloc[-1])
        self.assertNotAlmostEqual(prices.iloc[-1].rolling_vol_90d,
                                 prices.log_return.rolling(90).std().iloc[-1] * np.sqrt(252))

    def test_weekly_gaps_and_incomplete_week(self):
        dates = pd.bdate_range("2024-01-01", "2024-08-07")
        prices = pd.DataFrame({"price_date": dates, "jet_fuel_gal": np.arange(len(dates)) + 2})
        weekly = weekly_prices(prices)
        self.assertEqual(str(weekly.iloc[-1].week_ending.date()), "2024-08-02")
        self.assertEqual(weekly.iloc[-1].jet_fuel_gal,
                         prices[prices.price_date == "2024-08-02"].jet_fuel_gal.iloc[0])
        sparse = prices[~prices.price_date.between("2024-04-01", "2024-04-05")]
        with self.assertRaisesRegex(ValueError, "empty week"):
            weekly_prices(sparse)
        with self.assertRaisesRegex(ValueError, "26"):
            weekly_prices(prices.head(5))


if __name__ == "__main__":
    unittest.main()
