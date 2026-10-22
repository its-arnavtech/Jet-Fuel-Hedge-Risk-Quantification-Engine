"""Independently reconcile every insight column; live is the default, offline explicit."""

import argparse
from datetime import datetime, timezone
import hashlib
import inspect
import json
from pathlib import Path

import numpy as np
import pandas as pd

from fuel_hedge.config import Settings, load_env
from fuel_hedge.databricks import workspace_client
from fuel_hedge.insights import KEYS
from insights_oracle import reference_forecast, reference_tables
from verify_phase1 import query


def compare(actual, expected, keys, name):
    actual, expected = actual.copy(), expected.copy()
    if len(actual) != len(expected) or actual.duplicated(keys).any():
        raise ValueError(f"{name}: row count or grain mismatch")
    for col in keys:
        if col in ["price_date", "window_start", "week_ending"]:
            actual[col], expected[col] = pd.to_datetime(actual[col]), pd.to_datetime(expected[col])
        if col == "year":
            actual[col], expected[col] = actual[col].astype(str), expected[col].astype(str)
        if col in ["hedge_ratio", "threshold"]:
            actual[col] = pd.to_numeric(actual[col])
    actual, expected = actual.sort_values(keys).reset_index(drop=True), expected.sort_values(keys).reset_index(drop=True)
    pd.testing.assert_frame_equal(actual[keys], expected[keys], check_dtype=False)
    errors = {}
    for col in expected:
        if col in keys:
            continue
        if pd.api.types.is_bool_dtype(expected[col]):
            a = actual[col].astype(str).str.lower().eq("true")
            if not a.equals(expected[col]):
                raise ValueError(f"{name}.{col}: boolean mismatch")
        elif pd.api.types.is_numeric_dtype(expected[col]):
            a = pd.to_numeric(actual[col]).to_numpy(float)
            b = expected[col].to_numpy(float)
            np.testing.assert_allclose(a, b, atol=1e-9, rtol=0, equal_nan=True, err_msg=f"{name}.{col}")
            diff = np.abs(a-b)
            errors[col] = float(np.nanmax(diff)) if np.isfinite(diff).any() else 0.
        else:
            if actual[col].astype(str).tolist() != expected[col].astype(str).tolist():
                raise ValueError(f"{name}.{col}: value mismatch")
    return dict(rows=len(actual), columns=list(expected), max_absolute_errors=errors)


def findings(tables, risk, fan, routes, dim):
    market = tables["market_decomposition"].sort_values("price_date").copy()
    market["price_date"] = pd.to_datetime(market.price_date)
    last = market.iloc[-1]
    prior = market[market.price_date <= last.price_date-pd.DateOffset(years=1)].iloc[-1]
    delta = last.jet_fuel_gal-prior.jet_fuel_gal
    base = market[market.price_date.dt.year < last.price_date.year].crack_spread.mean()
    c = tables["proxy_return_correlation"].iloc[-1]
    annual = tables["proxy_effectiveness_annual"]
    pivot = annual[annual.year.astype(str).ne("ALL")].pivot(index="year", columns="proxy", values="r2")
    bt = tables["hedge_backtest_windows"]
    zero = bt[bt.hedge_ratio.eq(0)]
    high = bt[bt.hedge_ratio.eq(.8)]
    current = tables["calibration_history"].iloc[-1]
    forecast = tables["forecast_backtest"]
    coverage = {}
    for model, group in forecast.groupby("drift_model"):
        high_drift = group[group.high_drift.astype(str).str.lower().eq("true")]
        coverage[model] = dict(coverage=float(group.inside_band.astype(str).str.lower().eq("true").mean()),
            below_p05=float(group.below_p05.astype(str).str.lower().eq("true").mean()),
            high_drift_below=float(high_drift.below_p05.astype(str).str.lower().eq("true").mean()),
            log_rmse=float(np.sqrt(np.mean(group.log_err_p50**2))), windows=len(group))
    tail = tables["return_tail_frequency"].set_index("threshold").loc[3]
    r0 = risk[risk.hedge_ratio.eq(0)].iloc[0]
    r8 = risk[risk.hedge_ratio.eq(.8)].iloc[0]
    b767 = dim[dim.aircraft_type.eq("B767")]
    scheduled = dim.avg_fuel_burn_gal*dim.daily_frequencies
    ratio = zero.realized_avg/zero.s0-1
    latest = zero[zero.is_latest_complete.astype(str).str.lower().eq("true")].iloc[0]
    route8 = routes[routes.hedge_ratio.eq(.8)]
    return {"F1":dict(jet_change=delta, wti_change=last.wti_gal-prior.wti_gal,
        crack_change=last.crack_spread-prior.crack_spread, crack_share=(last.crack_spread-prior.crack_spread)/delta,
        crack=last.crack_spread, crack_multiple=last.crack_spread/base, historical_crack_mean=base,
        jet_rank=last.jet_pct_rank_full_history, crack_rank=last.crack_pct_rank_full_history),
        "F2":dict(price_level=c.price_level_corr_jet_wti_90d, returns_wti=c.ret_corr_jet_wti_90d,
                  returns_ho=c.ret_corr_jet_ho_90d),
        "F3":dict(ho_wins=int((pivot.HO > pivot.WTI).sum()), years=len(pivot),
                  wti_effective=int((pivot.WTI >= .8).sum()), full_sample_r2=annual[annual.year.eq("ALL")].set_index("proxy").r2.to_dict()),
        "F4":dict(jet_change=delta, wti_change=last.wti_gal-prior.wti_gal, ho_change=last.heating_oil_gal-prior.heating_oil_gal),
        "F5":dict(windows=len(zero), win_rate=float(zero.hedge_won.astype(str).str.lower().eq("true").mean()),
                  mean_savings=float(zero.savings_per_gal.mean()), p95_unhedged=float(zero.budget_overrun_b.quantile(.95)),
                  p95_80=float(high.budget_overrun_b.quantile(.95)), worst_unhedged=float(zero.budget_overrun_b.max()),
                  worst_80=float(high.budget_overrun_b.max()), expected_hedge_cost_b=float(high.budget_overrun_b.mean()-zero.budget_overrun_b.mean())),
        "F6":dict(latest_savings=float(latest.savings_per_gal), latest_rank=float(latest.window_pct_rank), window_start=str(latest.window_start)),
        "F7":dict(mu=float(current.mu), sigma=float(current.sigma), mu_rank=float(current.mu_pct_rank),
                  sigma_rank=float(current.sigma_pct_rank), calibrations=len(tables["calibration_history"]),
                  median_mu=float(tables["calibration_history"].mu.median())),
        "F8":coverage,
        "F9":dict(ratio=float(tail.ratio), excess_kurtosis=float(tail.excess_kurtosis), skew=float(tail["skew"]),
                  observed_share=float(tail.observed_share), normal_share=float(tail.normal_share)),
        "F10":dict(simulation_hedge_change_b=float(r8.mean_cost_b-r0.mean_cost_b),
                   historical_hedge_change_b=float(high.budget_overrun_b.mean()-zero.budget_overrun_b.mean()),
                   mean_cost_b=float(r0.mean_cost_b), spot_run_rate_b=float(last.jet_fuel_gal*1.5),
                   mean_vs_spot=float(r0.mean_cost_b/(last.jet_fuel_gal*1.5)-1),
                   cvar_unhedged=float(r0.cvar_95_b), cvar_80=float(r8.cvar_95_b),
                   terminal_median=float(fan.sort_values("step").iloc[-1].p50_price_gal),
                   historical_p95_move=float(ratio.quantile(.95)), historical_median_move=float(ratio.median())),
        "F11":dict(break_even=float(np.expm1(.04)), minus30_cost_b=float(1.5*.8*last.jet_fuel_gal*(np.exp(.04)-.7)),
                   plus50_cost_b=float(1.5*.8*last.jet_fuel_gal*(np.exp(.04)-1.5))),
        "F12":dict(b767_departures=int(b767.daily_frequencies.sum()), departures=int(dim.daily_frequencies.sum()),
                   b767_gallon_share=float((b767.avg_fuel_burn_gal*b767.daily_frequencies).sum()/scheduled.sum()),
                   route_savings_80_m=float(route8.hedge_savings_usd.sum()/1e6))}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--offline", action="store_true", help="Validate local development extracts; never claims live success")
    args = parser.parse_args()
    source_id = None
    if args.offline:
        daily = pd.read_csv("artifacts/silver/fuel_prices.csv")
        weekly = pd.read_csv("artifacts/silver/weekly_fuel_prices.csv")
        folder = Path("artifacts/insights_local")
        actual = {name: pd.read_csv(folder/f"{name}.csv") for name in KEYS}
        risk, fan = pd.read_csv("artifacts/risk_metrics.csv"), pd.read_csv("artifacts/price_fan.csv")
        routes, dim = pd.read_csv(folder/"route_fuel_costs.csv"), pd.read_csv(folder/"dim_route.csv")
    else:
        load_env()
        settings = Settings.from_env()
        client = workspace_client(settings)
        def sql(statement):
            return query(client, settings.warehouse_id, statement)
        gold, silver = f"{settings.catalog}.jet_fuel_gold", f"{settings.catalog}.jet_fuel_silver"
        ready = sql(f"SELECT * FROM {gold}.reporting_readiness")
        if len(ready) != 1 or not all(ready.iloc[0][c] == "true" for c in ["analytics_ready", "risk_ready", "insights_ready"]):
            raise ValueError("All reporting flags must be ready")
        source_id = ready.iloc[0].source_pipeline_run_id
        insight_publication = sql(f"SELECT * FROM {gold}.insights_publication_ready")
        if len(insight_publication) != 1 or insight_publication.iloc[0].insights_ready != "true":
            raise ValueError("Insight registry is not ready")
        daily, weekly = sql(f"SELECT * FROM {silver}.fuel_prices"), sql(f"SELECT * FROM {silver}.weekly_fuel_prices")
        actual = {n: sql(f"SELECT * FROM {gold}.{n}_current") for n in KEYS}
        for name, frame in actual.items():
            if (frame.empty or not frame.insights_run_id.eq(insight_publication.iloc[0].insights_run_id).all()
                    or not frame.source_pipeline_run_id.eq(source_id).all()
                    or frame.created_ts.isna().any() or not frame.is_synthetic.eq("false").all()):
                raise ValueError("Invalid insight lineage/source flags: "+name)
        risk, fan = sql(f"SELECT * FROM {gold}.risk_metrics_current"), sql(f"SELECT * FROM {gold}.price_fan_current")
        routes, dim = sql(f"SELECT * FROM {gold}.route_fuel_costs_current"), sql(f"SELECT * FROM {gold}.dim_route")
        for frame in [risk, fan, routes, dim]:
            for col in frame:
                if col not in ["year"]:
                    try:
                        frame[col] = pd.to_numeric(frame[col])
                    except (ValueError, TypeError):
                        pass
        simulation = sql(f"SELECT * FROM {gold}.latest_simulation_run").iloc[0]
        current = actual["calibration_history"].loc[lambda f: f.is_current.eq("true")].iloc[0]
        np.testing.assert_allclose([float(current.mu), float(current.sigma)], [float(simulation.mu), float(simulation.sigma)], rtol=0, atol=1e-9)
    expected = reference_tables(daily, weekly)
    checks = {n: compare(actual[n], f, KEYS[n], n) for n, f in expected.items()}
    inputs = expected["calibration_history"].merge(expected["hedge_backtest_windows"].loc[lambda f: f.hedge_ratio.eq(0)],
        left_on="week_ending", right_on="window_start").sort_values("week_ending").reset_index(drop=True)
    forecasts = []
    oracle_cache = Path("artifacts/insights_oracle")
    oracle_cache.mkdir(parents=True, exist_ok=True)
    oracle_version = inspect.getsource(reference_forecast).encode()
    for i, row in enumerate(inputs.to_dict("records")):
        signature = hashlib.sha256(oracle_version+json.dumps(row, sort_keys=True, default=str).encode()).hexdigest()
        cache_file = oracle_cache/f"{i:04d}_{signature}.csv"
        if cache_file.exists():
            frame = pd.read_csv(cache_file)
        else:
            frame = reference_forecast(row, i)
            frame.to_csv(cache_file, index=False)
        forecasts.append(frame)
        if i % 100 == 0:
            print(f"Independent forecast verification {i+1}/{len(inputs)}", flush=True)
    expected["forecast_backtest"] = pd.concat(forecasts, ignore_index=True)
    checks["forecast_backtest"] = compare(actual["forecast_backtest"], expected["forecast_backtest"], KEYS["forecast_backtest"], "forecast_backtest")
    numbers = findings(expected, risk, fan, routes, dim)
    if not args.offline:
        after = sql(f"SELECT * FROM {gold}.reporting_readiness")
        pd.testing.assert_frame_equal(ready, after)
        pd.testing.assert_frame_equal(insight_publication, sql(f"SELECT * FROM {gold}.insights_publication_ready"))
        folder = Path("artifacts/insights_gold")
        folder.mkdir(parents=True, exist_ok=True)
        for n, f in actual.items():
            f.to_csv(folder/f"{n}.csv", index=False)
        for n, f in [("route_fuel_costs", routes), ("dim_route", dim), ("risk_metrics", risk), ("price_fan", fan)]:
            f.to_csv(folder/f"{n}.csv", index=False)
        sql(f"SELECT * FROM {gold}.cost_histogram_current").to_csv(folder/"cost_histogram.csv", index=False)
        sql(f"SELECT * FROM {gold}.v_hedge_mtm").to_csv(folder/"hedge_mtm.csv", index=False)
        sql(f"SELECT * FROM {gold}.v_hedge_sensitivity").to_csv(folder/"hedge_sensitivity.csv", index=False)
    evidence = dict(checked_at=datetime.now(timezone.utc).isoformat(), passed=True,
        live_verified=not args.offline, source="local development extracts" if args.offline else "live SQL Silver/Gold",
        source_pipeline_run_id=source_id, price_as_of=str(daily.price_date.max()),
        insights_run_id=None if args.offline else insight_publication.iloc[0].insights_run_id,
        deterministic_tolerance=1e-9, mc_value_tolerance=1e-9, checks=checks, findings=numbers,
        expected_value_deviations={"F7": f"Ranks/counts use all {len(expected['calibration_history'])} valid historical calibrations; {len(inputs)} have completed forward outcomes. Full-history current mu rank differs from a completed-window-only reference."})
    path = Path("docs/evidence/phase5_offline_verification.json" if args.offline else "docs/evidence/phase5_verification.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(evidence, indent=2, default=str, allow_nan=False), encoding="utf-8")
    print(json.dumps({k:v for k,v in evidence.items() if k != "checks"}, indent=2, default=str))


if __name__ == "__main__":
    main()
