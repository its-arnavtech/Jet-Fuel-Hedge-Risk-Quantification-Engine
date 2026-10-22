"""Offline development extracts. NEVER represents these as a live Gold publication."""

import json
from pathlib import Path
import time

import numpy as np
import pandas as pd

from fuel_hedge.insights import deterministic_tables, forecast_inputs, forecast_window
from fuel_hedge.operations import synthetic_operations
from fuel_hedge.simulation import SimulationConfig, calibrate, cost_distribution, price_paths


def local_operations(daily):
    daily = daily.copy()
    daily["price_date"] = pd.to_datetime(daily.price_date)
    ops = synthetic_operations(daily.price_date.max().date())
    flights = ops["flights"].loc[lambda f: ~f.cancelled].copy()
    flights["flight_date"] = pd.to_datetime(flights.flight_date)
    flights = flights.merge(ops["routes"], on="route_id")
    flights = pd.merge_asof(flights.sort_values("flight_date"), daily.sort_values("price_date"),
                            left_on="flight_date", right_on="price_date")
    flights["cost_month"] = flights.flight_date.dt.to_period("M").dt.to_timestamp()
    flights["cost"] = flights.avg_fuel_burn_gal*flights.jet_fuel_gal
    fact = flights.groupby(["route_id", "aircraft_type", "cost_month"]).agg(
        monthly_gallons=("avg_fuel_burn_gal", "sum"), monthly_flights=("flight_id", "size"),
        unhedged_cost_usd=("cost", "sum")).reset_index()
    start = pd.Timestamp(ops["flights"].flight_date.min())
    locked = daily[daily.price_date <= start].iloc[-1].jet_fuel_gal*np.exp(.04)
    fact = fact.merge(pd.DataFrame({"hedge_ratio": [0., .2, .4, .6, .8]}), how="cross")
    fact["hedged_cost_usd"] = fact.hedge_ratio*locked*fact.monthly_gallons+(1-fact.hedge_ratio)*fact.unhedged_cost_usd
    fact["hedge_savings_usd"] = fact.unhedged_cost_usd-fact.hedged_cost_usd
    marks = ops["hedge_positions"][["underlying", "locked_price_gal"]].copy()
    latest = daily.iloc[-1]
    spots = dict(JET_FUEL=float(latest.jet_fuel_gal), WTI=float(latest.wti_spot_bbl)/42,
                 HEATING_OIL=float(latest.heating_oil_gal))
    marks["current_spot_gal"] = marks.underlying.map(spots)
    marks["pnl_per_gallon"] = marks.current_spot_gal-marks.locked_price_gal
    marks["hedge_status"] = np.where(marks.pnl_per_gallon > 0, "IN_THE_MONEY", np.where(marks.pnl_per_gallon < 0, "OUT_OF_MONEY", "AT_THE_MONEY"))
    return fact, ops["routes"], marks


def main():
    out = Path("artifacts/insights_local")
    out.mkdir(parents=True, exist_ok=True)
    daily = pd.read_csv("artifacts/silver/fuel_prices.csv")
    weekly = pd.read_csv("artifacts/silver/weekly_fuel_prices.csv")
    tables = deterministic_tables(daily, weekly)
    for name, frame in tables.items():
        frame.to_csv(out/f"{name}.csv", index=False)
    inputs = forecast_inputs(tables["calibration_history"], tables["hedge_backtest_windows"])
    cache = out/"windows"
    cache.mkdir(exist_ok=True)
    begun = time.monotonic()
    results = []
    for i, row in enumerate(inputs.to_dict("records")):
        target = cache/f"{i:04d}.csv"
        if target.exists():
            result = pd.read_csv(target)
        else:
            result = forecast_window(row, i)
            result.to_csv(target, index=False)
        results.append(result)
        if i % 50 == 0:
            print(f"Offline walk-forward {i+1}/{len(inputs)}; {time.monotonic()-begun:.1f}s", flush=True)
    pd.concat(results).to_csv(out/"forecast_backtest.csv", index=False)
    routes, dim, marks = local_operations(daily)
    routes.to_csv(out/"route_fuel_costs.csv", index=False)
    dim.to_csv(out/"dim_route.csv", index=False)
    marks.to_csv(out/"hedge_mtm.csv", index=False)
    sensitivity = pd.DataFrame([dict(hedge_ratio=h, price_change_pct=p,
        unhedged_cost_b=1.5*float(daily.iloc[-1].jet_fuel_gal)*(1+p/100),
        hedged_cost_b=1.5*float(daily.iloc[-1].jet_fuel_gal)*(h*np.exp(.04)+(1-h)*(1+p/100)))
        for h in [0., .2, .4, .6, .8] for p in [-30, -15, 0, 15, 30, 50]])
    sensitivity.to_csv(out/"hedge_sensitivity.csv", index=False)
    calibration = calibrate(weekly)
    config = SimulationConfig(s0=float(daily.iloc[-1].jet_fuel_gal), mu=calibration["mu"], sigma=calibration["sigma"])
    # Actual local simulation for histogram bins, never reconstruct counts from illustrative curves.
    costs = cost_distribution(price_paths(np.arange(config.n_paths), config), config)
    histogram = []
    for ratio in [0., .8]:
        counts, edges = np.histogram(costs[ratio], bins=50)
        histogram.extend(dict(hedge_ratio=ratio, bin=i, bin_lower_cost_b=edges[i],
                              bin_upper_cost_b=edges[i+1], path_count=int(count)) for i, count in enumerate(counts))
    pd.DataFrame(histogram).to_csv(out/"cost_histogram.csv", index=False)
    (out/"provenance.json").write_text(json.dumps(dict(source="local Silver CSVs; NOT live Gold",
        price_as_of=daily.price_date.max(), n_paths=10000, base_seed=20261021,
        forecast_windows=len(inputs), simulation_histogram_seed=config.seed), indent=2), encoding="utf-8")
    print("Offline extracts complete", flush=True)


if __name__ == "__main__":
    main()
