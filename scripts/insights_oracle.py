"""Independent verification equations. Does not import the insights implementation.

Deliberately uses scalar calendar masks, explicit covariance and direct path equations
instead of production rolling/GBM helpers. This is an audit oracle, not a publisher.
"""

import math

import numpy as np
import pandas as pd


def rank(series):
    a = np.around(np.asarray(series, float), decimals=12)
    finite = a[np.isfinite(a)]
    return [float(np.sum(finite < x))/max(len(finite)-1, 1) if np.isfinite(x) else np.nan for x in a]


def reference_tables(daily, weekly):
    d = daily.copy().sort_values("price_date").reset_index(drop=True)
    d["price_date"] = pd.to_datetime(d.price_date)
    for c in ["jet_fuel_gal", "crack_spread", "wti_spot_bbl", "brent_spot_bbl", "heating_oil_gal", "rolling_corr_90d"]:
        d[c] = pd.to_numeric(d[c])
    w = weekly.copy().sort_values("week_ending").reset_index(drop=True)
    w["week_ending"] = pd.to_datetime(w.week_ending)
    w["jet_fuel_gal"] = pd.to_numeric(w.jet_fuel_gal)
    d["wti_gal"], d["brent_gal"] = d.wti_spot_bbl/42, d.brent_spot_bbl/42
    market = d[["price_date", "jet_fuel_gal", "wti_gal", "crack_spread", "heating_oil_gal", "brent_gal"]].copy()
    market["jet_pct_rank_full_history"] = rank(d.jet_fuel_gal)
    market["crack_pct_rank_full_history"] = rank(d.crack_spread)
    prices = d.set_index("price_date")[["jet_fuel_gal", "heating_oil_gal", "wti_gal", "brent_gal"]]
    logs = np.log(prices.where(prices > 0))
    rets = logs-logs.shift(1)
    gap = prices.index.to_series().diff().dt.days.gt(4)
    gap |= d.set_index("price_date").long_return_gap.astype(str).str.lower().eq("true")
    corr_rows = []
    for dt in prices.index:
        mask = (prices.index >= dt-pd.Timedelta(days=90)) & (prices.index <= dt)
        row = dict(price_date=dt)
        for proxy, col in [("ho", "heating_oil_gal"), ("wti", "wti_gal"), ("brent", "brent_gal")]:
            pair = rets.loc[mask, ["jet_fuel_gal", col]].dropna().to_numpy()
            row[f"ret_corr_jet_{proxy}_90d"] = float(np.corrcoef(pair.T)[0, 1]) if len(pair) >= 20 and not gap.loc[mask].any() else np.nan
        corr_rows.append(row)
    correlations = pd.DataFrame(corr_rows)
    correlations["price_level_corr_jet_wti_90d"] = d.rolling_corr_90d
    wp = prices.resample("W-FRI").last().loc[:prices.index.max()]
    lr = np.log(wp.where(wp > 0))
    wr = lr-lr.shift(1)
    annual = []
    for year in [*sorted(set(wr.index.year)), "ALL"]:
        group = wr if year == "ALL" else wr[wr.index.year == year]
        for proxy, col in [("HO", "heating_oil_gal"), ("WTI", "wti_gal"), ("BRENT", "brent_gal")]:
            a = group[["jet_fuel_gal", col]].dropna().to_numpy()
            correlation = np.corrcoef(a.T)[0, 1] if len(a) > 1 else np.nan
            beta = np.cov(a.T, ddof=1)[0, 1]/np.var(a[:, 1], ddof=1) if len(a) > 1 and np.var(a[:, 1]) > 0 else np.nan
            annual.append(dict(year=str(year), proxy=proxy, n_weeks=len(a), corr=correlation,
                               r2=correlation**2, min_var_beta=beta, meets_80pct_r2=bool(correlation**2 >= .8)))
    windows = []
    for i in range(len(w)-52):
        initial = float(w.jet_fuel_gal.iloc[i])
        average = sum(float(v) for v in w.jet_fuel_gal.iloc[i+1:i+53])/52
        f = initial*math.exp(.04)
        for h in [0., .2, .4, .6, .8]:
            windows.append(dict(window_start=w.week_ending.iloc[i], hedge_ratio=h, s0=initial,
                forward=f, realized_avg=average, savings_per_gal=average-f, hedge_won=average > f,
                budget_overrun_b=1.5*(h*f+(1-h)*average-initial), is_latest_complete=i == len(w)-53))
    windows = pd.DataFrame(windows)
    windows["window_pct_rank"] = windows.groupby("hedge_ratio").savings_per_gal.transform(rank)
    history = []
    for i, row in w.iterrows():
        if (row.week_ending-w.week_ending.iloc[0]).days < 364:
            continue
        subset = w[(w.week_ending <= row.week_ending) & (w.week_ending > row.week_ending-pd.Timedelta(days=365))]
        x = np.diff(np.log(subset.jet_fuel_gal.to_numpy(float)))
        weights = np.array([.94**(len(x)-j-1) for j in range(len(x))])
        weights /= sum(weights)
        mean = sum(weights*x)
        variance = sum(weights*(x-mean)**2)/(1-sum(weights**2))
        history.append(dict(week_ending=row.week_ending, mu=52*mean+26*variance,
                            sigma=math.sqrt(52*variance), is_current=i == len(w)-1))
    history = pd.DataFrame(history)
    history["mu_pct_rank"], history["sigma_pct_rank"] = rank(history.mu), rank(history.sigma)
    x = wr.jet_fuel_gal.dropna()
    z = (x-x.mean())/x.std(ddof=1)
    tails = pd.DataFrame([dict(threshold=k, observed_share=float((abs(z) > k).mean()),
        normal_share=math.erfc(k/math.sqrt(2)), ratio=float((abs(z) > k).mean())/math.erfc(k/math.sqrt(2)),
        excess_kurtosis=x.kurt(), skew=x.skew(), n_weeks=len(x)) for k in [2, 3, 4]])
    return dict(market_decomposition=market, proxy_return_correlation=correlations,
        proxy_effectiveness_annual=pd.DataFrame(annual), hedge_backtest_windows=windows,
        calibration_history=history, return_tail_frequency=tails)


def reference_forecast(row, index, n_paths=10000, seed=20261021):
    # Independent direct Box-Muller and GBM equations; exact same entropy triple.
    normals = np.empty((n_paths, 52))
    for pid in range(n_paths):
        u = np.random.default_rng(np.random.SeedSequence([seed, index, pid])).random((26, 2))
        radius = np.sqrt(-2*np.log(np.maximum(u[:, 0], np.finfo(float).tiny)))
        angle = 2*np.pi*u[:, 1]
        normals[pid] = np.column_stack([radius*np.cos(angle), radius*np.sin(angle)]).reshape(-1)
    rows = []
    sigma, actual = float(row["sigma"]), float(row["realized_avg"])
    for model, mu in [("EWM", row["mu"]), ("MARTINGALE", 0.), ("RISK_FREE", .04)]:
        prices = row["s0"]*np.exp(np.cumsum((mu-sigma*sigma/2)/52+sigma/np.sqrt(52)*normals, axis=1))
        avgs = prices.sum(axis=1)/52
        lo, mid, hi = np.quantile(avgs, [.05, .5, .95])
        rows.append(dict(window_start=row["week_ending"], drift_model=model, p05=lo, p50=mid, p95=hi,
            mean=avgs.mean(), realized_avg=actual, inside_band=bool(lo <= actual <= hi), below_p05=bool(actual < lo),
            above_p95=bool(actual > hi), log_err_p50=math.log(mid/actual), high_drift=bool(row["mu"] > .5),
            mu_ewm=row["mu"], n_paths=n_paths, window_index=index, base_seed=seed))
    return pd.DataFrame(rows)
