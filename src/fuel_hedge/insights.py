"""Historical hedge evidence. Real prices; costs use a reference 1.5B gal carrier.

No Spark or I/O. Production simulation functions and defaults are unchanged.
"""

import math

import numpy as np
import pandas as pd

from fuel_hedge.simulation import SimulationConfig, calibrate, price_paths

RATIOS = (0., .2, .4, .6, .8)
PROXIES = {"HO": "heating_oil_gal", "WTI": "wti_gal", "BRENT": "brent_gal"}
KEYS = {
    "market_decomposition": ["price_date"],
    "proxy_return_correlation": ["price_date"],
    "proxy_effectiveness_annual": ["year", "proxy"],
    "hedge_backtest_windows": ["window_start", "hedge_ratio"],
    "calibration_history": ["week_ending"],
    "forecast_backtest": ["window_start", "drift_model"],
    "return_tail_frequency": ["threshold"],
}


def pct_rank(values):
    """SQL PERCENT_RANK: ties share minimum rank; NULL is excluded."""
    # Canonical rank keys make mathematically tied converted prices independent of wire/Arrow ULPs.
    values = pd.Series(values).round(12)
    n = values.count()
    return (values.rank(method="min") - 1) / (n - 1) if n > 1 else values * 0


def market_prices(daily):
    frame = daily.copy()
    frame["price_date"] = pd.to_datetime(frame.price_date)
    frame = frame.sort_values("price_date").reset_index(drop=True)
    if frame.empty or not frame.price_date.is_unique:
        raise ValueError("Unique nonempty daily prices required")
    for col in ["jet_fuel_gal", "wti_spot_bbl", "brent_spot_bbl", "heating_oil_gal", "crack_spread"]:
        frame[col] = pd.to_numeric(frame[col])
    frame["wti_gal"] = frame.wti_spot_bbl / 42
    frame["brent_gal"] = frame.brent_spot_bbl / 42
    np.testing.assert_allclose(frame.crack_spread, frame.jet_fuel_gal - frame.wti_gal,
                               atol=1e-9, rtol=0, equal_nan=True)
    for name in ["jet", "crack"]:
        col = "jet_fuel_gal" if name == "jet" else "crack_spread"
        frame[f"{name}_pct_rank_full_history"] = pct_rank(frame[col])
    return frame


def return_correlations(market):
    prices = market.set_index("price_date")
    cols = ["jet_fuel_gal", *PROXIES.values()]
    # A missing or nonpositive price breaks that leg; never bridge a proxy observation gap.
    returns = np.log(prices[cols].where(prices[cols] > 0)).diff()
    gap = prices.index.to_series().diff().dt.days.gt(4)
    if "long_return_gap" in prices:
        gap |= prices.long_return_gap.astype(str).str.lower().eq("true")
    result = pd.DataFrame(index=prices.index)
    for proxy, col in PROXIES.items():
        # Reindex before rolling so dates with missing pairs still evaluate the calendar window.
        pair = returns[["jet_fuel_gal", col]].where(returns[["jet_fuel_gal", col]].notna().all(axis=1))
        # SQL RANGE BETWEEN INTERVAL 90 DAYS PRECEDING AND CURRENT ROW includes both endpoints.
        corr = pair.jet_fuel_gal.rolling("90D", closed="both", min_periods=20).corr(pair[col])
        corr[gap.rolling("90D", closed="both").max().astype(bool)] = np.nan
        result[f"ret_corr_jet_{proxy.lower()}_90d"] = corr
    result["price_level_corr_jet_wti_90d"] = pd.to_numeric(prices.rolling_corr_90d)
    return result.reset_index()


def weekly_proxy_returns(market):
    prices = market.set_index("price_date")[["jet_fuel_gal", *PROXIES.values()]]
    # Resample each leg using its last actual observation; retain empty weeks as NULL.
    weekly = prices.resample("W-FRI").last()
    weekly = weekly.loc[weekly.index <= prices.index.max()]
    return np.log(weekly.where(weekly > 0)).diff()


def proxy_effectiveness(market):
    returns = weekly_proxy_returns(market)
    rows = []
    groups = [(str(year), group) for year, group in returns.groupby(returns.index.year)]
    groups.append(("ALL", returns))
    for year, group in groups:
        for proxy, col in PROXIES.items():
            pair = group[["jet_fuel_gal", col]].dropna()
            corr = pair.jet_fuel_gal.corr(pair[col]) if len(pair) >= 2 else np.nan
            var = pair[col].var()
            rows.append(dict(year=year, proxy=proxy, n_weeks=len(pair), corr=corr,
                             r2=corr**2, min_var_beta=pair.jet_fuel_gal.cov(pair[col])/var
                             if var > 0 else np.nan, meets_80pct_r2=bool(corr**2 >= .8)))
    return pd.DataFrame(rows)


def regular_weekly(weekly):
    frame = weekly[["week_ending", "jet_fuel_gal"]].copy()
    frame["week_ending"] = pd.to_datetime(frame.week_ending)
    frame["jet_fuel_gal"] = pd.to_numeric(frame.jet_fuel_gal)
    frame = frame.sort_values("week_ending").reset_index(drop=True)
    if (frame.empty or not frame.week_ending.is_unique
            or frame.week_ending.diff().dropna().dt.days.ne(7).any()
            or not frame.week_ending.dt.dayofweek.eq(4).all()
            or not np.isfinite(frame.jet_fuel_gal).all() or frame.jet_fuel_gal.le(0).any()):
        raise ValueError("Positive consecutive Friday weekly prices required; missing week")
    return frame


def hedge_windows(weekly):
    weekly = regular_weekly(weekly)
    rows = []
    for i in range(len(weekly)-52):
        s0 = float(weekly.jet_fuel_gal.iloc[i])
        average = float(weekly.jet_fuel_gal.iloc[i+1:i+53].mean())
        for ratio in RATIOS:
            forward = s0 * math.exp(.04)
            rows.append(dict(window_start=weekly.week_ending.iloc[i], hedge_ratio=ratio, s0=s0,
                             forward=forward, realized_avg=average,
                             savings_per_gal=average-forward, hedge_won=average > forward,
                             budget_overrun_b=1.5*(ratio*forward+(1-ratio)*average-s0),
                             is_latest_complete=i == len(weekly)-53))
    result = pd.DataFrame(rows)
    if result.empty:
        raise ValueError("At least 53 weeks needed for a purchase window")
    result["window_pct_rank"] = result.groupby("hedge_ratio").savings_per_gal.transform(pct_rank)
    return result


def calibration_history(weekly):
    weekly = regular_weekly(weekly)
    rows = []
    for i, row in weekly.iterrows():
        # Require a full year of source history, even though calibrate permits 26 observations.
        if (row.week_ending-weekly.week_ending.iloc[0]).days < 364:
            continue
        calibration = calibrate(weekly.iloc[:i+1])
        rows.append(dict(week_ending=row.week_ending, mu=calibration["mu"],
                         sigma=calibration["sigma"], is_current=i == len(weekly)-1))
    result = pd.DataFrame(rows)
    if result.empty:
        raise ValueError("Full-year calibration history required")
    result["mu_pct_rank"] = pct_rank(result.mu)
    result["sigma_pct_rank"] = pct_rank(result.sigma)
    return result


def window_config(s0, mu, sigma, index, n_paths=10_000, seed=20261021):
    if not 0 <= seed < 2**32 or not 0 <= index < 2**31:
        raise ValueError("Seed/window index out of range")
    # Window/path entropy is encoded in path IDs; retain even the zero window word.
    return SimulationConfig(s0=float(s0), mu=float(mu), sigma=float(sigma), n_paths=n_paths,
                            seed=int(seed))


def window_path_ids(path_ids, index):
    """SeedSequence([base, encoded_id]) expands to [base, window, path]."""
    ids = np.asarray(path_ids, dtype=np.int64)
    if (ids < 0).any() or (ids >= 2**31).any() or not 0 <= index < 2**32:
        raise ValueError("Window/path identity out of range")
    return ids*2**32+index


def forecast_window(row, index, n_paths=10_000, seed=20261021):
    rows = []
    config = window_config(row["s0"], 0., row["sigma"], index, n_paths, seed)
    common_paths = price_paths(window_path_ids(np.arange(n_paths), index), config)[:, 1:]
    for model, mu in [("EWM", row["mu"]), ("MARTINGALE", 0.), ("RISK_FREE", .04)]:
        # Exact GBM drift rescaling shares shocks, avoids recomputing 3 identical RNG streams.
        average = (common_paths*np.exp(mu*np.arange(1, 53)/52)).mean(axis=1)
        p05, p50, p95 = np.quantile(average, [.05, .5, .95])
        actual = row["realized_avg"]
        rows.append(dict(window_start=row["week_ending"], drift_model=model, p05=p05, p50=p50,
                         p95=p95, mean=float(average.mean()), realized_avg=actual,
                         inside_band=bool(p05 <= actual <= p95), below_p05=bool(actual < p05),
                         above_p95=bool(actual > p95), log_err_p50=math.log(p50/actual),
                         high_drift=bool(row["mu"] > .5), mu_ewm=row["mu"], n_paths=n_paths,
                         window_index=index, base_seed=seed))
    return pd.DataFrame(rows)


def forecast_inputs(history, windows):
    base = windows.loc[windows.hedge_ratio.eq(0), ["window_start", "s0", "realized_avg"]]
    return history.merge(base, left_on="week_ending", right_on="window_start").sort_values("week_ending").reset_index(drop=True)


def tail_frequency(market):
    returns = weekly_proxy_returns(market).jet_fuel_gal.dropna()
    z = (returns-returns.mean()) / returns.std(ddof=1)
    rows = []
    for threshold in [2, 3, 4]:
        observed = float(z.abs().gt(threshold).mean())
        normal = math.erfc(threshold/math.sqrt(2))
        rows.append(dict(threshold=threshold, observed_share=observed, normal_share=normal,
                         ratio=observed/normal, excess_kurtosis=returns.kurt(), skew=returns.skew(),
                         n_weeks=len(returns)))
    return pd.DataFrame(rows)


def deterministic_tables(daily, weekly):
    market = market_prices(daily)
    return {
        "market_decomposition": market[["price_date", "jet_fuel_gal", "wti_gal", "crack_spread",
                                         "heating_oil_gal", "brent_gal", "jet_pct_rank_full_history",
                                         "crack_pct_rank_full_history"]],
        "proxy_return_correlation": return_correlations(market),
        "proxy_effectiveness_annual": proxy_effectiveness(market),
        "hedge_backtest_windows": hedge_windows(weekly),
        "calibration_history": calibration_history(weekly),
        "return_tail_frequency": tail_frequency(market),
    }
