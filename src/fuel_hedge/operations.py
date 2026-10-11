"""Deterministic, explicitly synthetic airline operations and linear hedge marks."""

from datetime import date, timedelta
import hashlib
import math

import pandas as pd

HEDGE_RATIOS = (0.0, 0.2, 0.4, 0.6, 0.8)


def synthetic_operations(as_of: date, days: int = 365) -> dict[str, pd.DataFrame]:
    if not 1 <= days <= 730:
        raise ValueError("Synthetic operations require 1–730 days")
    start = as_of - timedelta(days=days - 1)
    specs = [
        ("ATL", "JFK", 760, "A321", 2.3, 2100, 4, "domestic_short"),
        ("ATL", "LAX", 1946, "B757", 4.8, 5200, 3, "domestic_long"),
        ("DAL", "HOU", 239, "B737", 1.1, 900, 5, "domestic_short"),
        ("DAL", "DEN", 651, "B737", 2.1, 1800, 3, "domestic_short"),
        ("JFK", "LHR", 3451, "B767", 7.2, 11500, 2, "international"),
        ("LAX", "SEA", 954, "A321", 2.6, 2300, 3, "domestic_short"),
        ("DEN", "SFO", 967, "B737", 2.6, 2250, 2, "domestic_short"),
        ("ATL", "CDG", 4394, "B767", 8.8, 14500, 1, "international"),
    ]
    routes, flights = [], []
    for origin, destination, miles, aircraft, hours, burn, freq, category in specs:
        route_id = f"{origin}_{destination}_{aircraft}"
        routes.append({
            "route_id": route_id, "origin": origin, "destination": destination,
            "distance_miles": miles, "aircraft_type": aircraft, "avg_block_hours": hours,
            "avg_fuel_burn_gal": float(burn), "avg_load_factor": 0.84,
            "daily_frequencies": freq, "route_category": category,
            "effective_dt": start.isoformat(), "expiry_dt": (as_of + timedelta(days=1)).isoformat(),
            "source": "SYNTHETIC_BTS_STYLE", "is_synthetic": True,
        })
        for day in range(days):
            dt = start + timedelta(days=day)
            for flight_no in range(freq):
                flight_id = f"{route_id}_{dt.isoformat()}_{flight_no:02d}"
                cancelled = int(hashlib.sha256(flight_id.encode()).hexdigest()[:8], 16) % 41 == 0
                flights.append({"flight_id": flight_id, "route_id": route_id,
                                "flight_date": dt.isoformat(), "cancelled": cancelled,
                                "source": "SYNTHETIC_BTS_STYLE", "is_synthetic": True})
    positions = []
    for i, (underlying, locked) in enumerate([("JET_FUEL", 2.8), ("WTI", 1.7), ("HEATING_OIL", 2.6)]):
        positions.append({
            "position_id": f"SYNTHETIC_{i:03d}", "position_date": start.isoformat(),
            "instrument_type": "futures", "underlying": underlying,
            "contract_gallons": 2_000_000, "locked_price_gal": locked,
            "hedge_ratio": 0.2, "expiry_dt": (as_of + timedelta(days=180)).isoformat(),
            "premium_paid_usd": 0.0, "broker_id": "SYNTHETIC_BROKER",
            "source": "SYNTHETIC_POSITION", "is_synthetic": True,
        })
    return {"routes": pd.DataFrame(routes), "flights": pd.DataFrame(flights),
            "hedge_positions": pd.DataFrame(positions)}


def linear_hedge_mark(instrument: str, underlying: str, gallons: float,
                      locked_price_gal: float, spots: dict[str, float]) -> float | None:
    if instrument not in {"futures", "swap"}:
        raise ValueError("Only linear futures/swap marks are supported; options require valuation inputs")
    column = {"JET_FUEL": "jet_fuel_gal", "WTI": "wti_spot_bbl", "HEATING_OIL": "heating_oil_gal"}
    if underlying not in column or not math.isfinite(gallons) or gallons <= 0:
        raise ValueError("Unsupported underlying or invalid notional")
    if not math.isfinite(locked_price_gal):
        raise ValueError("Invalid locked price")
    spot = spots.get(column[underlying])
    if spot is None or not math.isfinite(spot):
        return None
    if underlying == "WTI":
        spot /= 42.0
    return (spot - locked_price_gal) * gallons


def scenario_cost(gallons: float, spot: float, locked: float, hedge_ratio: float) -> float:
    if not all(math.isfinite(v) for v in [gallons, spot, locked, hedge_ratio]):
        raise ValueError("Scenario inputs must be finite")
    if gallons < 0 or spot <= 0 or locked <= 0 or not 0 <= hedge_ratio <= 1:
        raise ValueError("Invalid scenario inputs")
    return gallons * (hedge_ratio * locked + (1 - hedge_ratio) * spot)
