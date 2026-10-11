"""Validated EIA price series, calendar analytics, and regular weekly samples."""

import hashlib
import math

import numpy as np
import pandas as pd

from .eia import SERIES, UNIT_ALIASES


def build_silver(events: list[dict]) -> tuple[pd.DataFrame, pd.DataFrame]:
    observations, rejected = [], []
    for event in events:
        for row in event["payload"]["response"]["data"]:
            item = {**row, "fetched_at": event["fetched_at"], "event_id": event["event_id"],
                    "capture_id": event["capture_id"]}
            series = SERIES.get(row.get("series"))
            try:
                parsed_date = pd.Timestamp(row["period"])
                if pd.isna(parsed_date) or str(parsed_date.date()) != row["period"]:
                    raise ValueError
                fetched = pd.Timestamp(event["fetched_at"])
                if fetched.tzinfo is None:
                    raise ValueError
            except (ValueError, TypeError, KeyError):
                rejected.append({**item, "reason": "invalid_date_or_ingest_timestamp"})
                continue
            if not series:
                rejected.append({**item, "reason": "unknown_series"})
                continue
            # Resolve revisions BEFORE validating values so withdrawn observations never resurrect.
            observations.append({**item, "price_date": parsed_date, "fetched_at": fetched})
    if not observations:
        raise ValueError("No dated EIA observations available")
    obs = pd.DataFrame(observations).sort_values(["fetched_at", "event_id"])
    obs = obs.drop_duplicates(["price_date", "series"], keep="last")
    valid = []
    for item in obs.to_dict("records"):
        expected = SERIES[item["series"]]
        if item.get("units") not in UNIT_ALIASES[expected.units]:
            rejected.append({**item, "reason": "unit_mismatch"})
            continue
        try:
            value = float(item["value"])
            if not math.isfinite(value) or (expected.column == "jet_fuel_gal" and value <= 0):
                raise ValueError
        except (ValueError, TypeError, KeyError):
            rejected.append({**item, "reason": "missing_or_invalid_price"})
            continue
        valid.append({**item, "numeric_value": value})
    if not valid:
        raise ValueError("No valid EIA observations remain")
    normalized = pd.DataFrame(valid)
    prices = normalized.pivot(index="price_date", columns="series", values="numeric_value")
    prices = prices.rename(columns={s: spec.column for s, spec in SERIES.items()})
    for spec in SERIES.values():
        if spec.column not in prices:
            prices[spec.column] = np.nan
    prices = prices.dropna(subset=["jet_fuel_gal"]).sort_index()
    if prices.empty:
        raise ValueError("No positive jet fuel prices remain")
    prices["crack_spread"] = prices.jet_fuel_gal - prices.wti_spot_bbl / 42.0
    prices["log_return"] = np.log(prices.jet_fuel_gal / prices.jet_fuel_gal.shift())
    # A trading-day annualization assumption; preserve calendar gaps for quality reporting.
    prices["return_gap_days"] = prices.index.to_series().diff().dt.days
    prices["long_return_gap"] = prices.return_gap_days > 4
    prices["rolling_vol_90d"] = prices.log_return.rolling("90D", min_periods=20).std(ddof=1) * np.sqrt(252)
    prices.loc[prices.long_return_gap.rolling("90D").max().astype(bool), "rolling_vol_90d"] = np.nan
    prices["rolling_corr_90d"] = prices.wti_spot_bbl.rolling("90D", min_periods=20).corr(prices.jet_fuel_gal)
    prices["source"] = "EIA"
    prices["is_synthetic"] = False
    prices["jet_region"] = "US Gulf Coast"
    jet_meta = normalized[normalized.series == "EER_EPJK_PF4_RGC_DPG"].set_index("price_date")
    for column in ["fetched_at", "capture_id", "event_id"]:
        prices[column] = jet_meta[column].reindex(prices.index)
    prices["price_id"] = [hashlib.sha256(f"EIA|{dt.date()}|US_GULF".encode()).hexdigest() for dt in prices.index]
    prices.columns.name = None
    return prices.reset_index(), pd.DataFrame(rejected)


def weekly_prices(prices: pd.DataFrame, *, min_weeks: int = 26) -> pd.DataFrame:
    """Last valid observation each complete Friday-ended week; no forward-filled missing weeks."""
    daily = prices.set_index("price_date").sort_index()[["jet_fuel_gal"]]
    if daily.empty or not daily.index.is_unique:
        raise ValueError("Weekly calibration requires unique daily price dates")
    daily["observation_date"] = daily.index
    weekly = daily.resample("W-FRI").last()
    # Do not include a not-yet-ended week. Holiday Fridays may have Thursday's observation.
    weekly = weekly[weekly.index <= daily.index.max()]
    if weekly.jet_fuel_gal.isna().any():
        raise ValueError("Weekly price series contains an empty week; no implicit imputation allowed")
    if len(weekly) < min_weeks:
        raise ValueError(f"At least {min_weeks} complete weekly observations are required")
    weekly["log_return"] = np.log(weekly.jet_fuel_gal / weekly.jet_fuel_gal.shift())
    weekly.index.name = "week_ending"
    return weekly.reset_index()
