-- Warehouse equivalents of headline numbers. Never executes or substitutes for DAX.
WITH m AS (SELECT * FROM jet_fuel_gold.market_decomposition_current),
latest AS (SELECT * FROM m QUALIFY row_number() OVER(ORDER BY price_date DESC)=1),
prior AS (SELECT * FROM m WHERE price_date <= (SELECT add_months(price_date,-12) FROM latest)
 QUALIFY row_number() OVER(ORDER BY price_date DESC)=1),
market AS (SELECT l.jet_fuel_gal-p.jet_fuel_gal AS jet_change,l.wti_gal-p.wti_gal AS wti_change,
 l.crack_spread-p.crack_spread AS crack_change,l.heating_oil_gal-p.heating_oil_gal AS ho_change,
 l.* FROM latest l CROSS JOIN prior p),
annual AS (SELECT year,max(CASE WHEN proxy='HO' THEN r2 END) AS ho,
 max(CASE WHEN proxy='WTI' THEN r2 END) AS wti FROM jet_fuel_gold.proxy_effectiveness_annual_current
 WHERE year<>'ALL' GROUP BY year),
backtest AS (SELECT * FROM jet_fuel_gold.hedge_backtest_windows_current),
history AS (SELECT * FROM jet_fuel_gold.calibration_history_current),
forecast AS (SELECT * FROM jet_fuel_gold.forecast_backtest_current),
risk AS (SELECT * FROM jet_fuel_gold.risk_metrics_current),
numbers AS (
SELECT 'F1' AS finding,'jet_change' AS metric,jet_change AS value FROM market
UNION ALL SELECT 'F1','wti_change',wti_change FROM market
UNION ALL SELECT 'F1','crack_change',crack_change FROM market
UNION ALL SELECT 'F1','crack_share',crack_change/jet_change FROM market
UNION ALL SELECT 'F1','crack',crack_spread FROM market
UNION ALL SELECT 'F1','jet_rank',jet_pct_rank_full_history FROM market
UNION ALL SELECT 'F1','crack_rank',crack_pct_rank_full_history FROM market
UNION ALL SELECT 'F1','crack_multiple',l.crack_spread/avg(m.crack_spread) FROM latest l CROSS JOIN m
 WHERE year(m.price_date)<year(l.price_date) GROUP BY l.crack_spread
UNION ALL SELECT 'F2','price_level',price_level_corr_jet_wti_90d FROM jet_fuel_gold.proxy_return_correlation_current
 WHERE price_date=(SELECT max(price_date) FROM m)
UNION ALL SELECT 'F2','returns_wti',ret_corr_jet_wti_90d FROM jet_fuel_gold.proxy_return_correlation_current
 WHERE price_date=(SELECT max(price_date) FROM m)
UNION ALL SELECT 'F2','returns_ho',ret_corr_jet_ho_90d FROM jet_fuel_gold.proxy_return_correlation_current
 WHERE price_date=(SELECT max(price_date) FROM m)
UNION ALL SELECT 'F3','ho_wins',count_if(ho>wti) FROM annual
UNION ALL SELECT 'F3','years',count(*) FROM annual
UNION ALL SELECT 'F3','wti_effective',count_if(wti>=0.8) FROM annual
UNION ALL SELECT 'F4','jet_change',jet_change FROM market
UNION ALL SELECT 'F4','wti_change',wti_change FROM market
UNION ALL SELECT 'F4','ho_change',ho_change FROM market
UNION ALL SELECT 'F5','windows',count(*) FROM backtest WHERE hedge_ratio=0
UNION ALL SELECT 'F5','win_rate',avg(cast(hedge_won AS DOUBLE)) FROM backtest WHERE hedge_ratio=0
UNION ALL SELECT 'F5','mean_savings',avg(savings_per_gal) FROM backtest WHERE hedge_ratio=0
UNION ALL SELECT 'F5','p95_unhedged',percentile_cont(.95) WITHIN GROUP(ORDER BY budget_overrun_b) FROM backtest WHERE hedge_ratio=0
UNION ALL SELECT 'F5','p95_80',percentile_cont(.95) WITHIN GROUP(ORDER BY budget_overrun_b) FROM backtest WHERE hedge_ratio=.8
UNION ALL SELECT 'F5','expected_hedge_cost_b',avg(CASE WHEN hedge_ratio=.8 THEN budget_overrun_b END)-avg(CASE WHEN hedge_ratio=0 THEN budget_overrun_b END) FROM backtest
UNION ALL SELECT 'F6','latest_savings',savings_per_gal FROM backtest WHERE hedge_ratio=0 AND is_latest_complete
UNION ALL SELECT 'F6','latest_rank',window_pct_rank FROM backtest WHERE hedge_ratio=0 AND is_latest_complete
UNION ALL SELECT 'F7','mu',mu FROM history WHERE is_current
UNION ALL SELECT 'F7','sigma',sigma FROM history WHERE is_current
UNION ALL SELECT 'F7','mu_rank',mu_pct_rank FROM history WHERE is_current
UNION ALL SELECT 'F7','sigma_rank',sigma_pct_rank FROM history WHERE is_current
UNION ALL SELECT 'F7','calibrations',count(*) FROM history
UNION ALL SELECT 'F7','median_mu',percentile_cont(.5) WITHIN GROUP(ORDER BY mu) FROM history
UNION ALL SELECT 'F8','EWM.coverage',avg(cast(inside_band AS DOUBLE)) FROM forecast WHERE drift_model='EWM'
UNION ALL SELECT 'F8','EWM.high_drift_below',avg(cast(below_p05 AS DOUBLE)) FROM forecast WHERE drift_model='EWM' AND high_drift
UNION ALL SELECT 'F9','ratio',ratio FROM jet_fuel_gold.return_tail_frequency_current WHERE threshold=3
UNION ALL SELECT 'F9','excess_kurtosis',excess_kurtosis FROM jet_fuel_gold.return_tail_frequency_current WHERE threshold=3
UNION ALL SELECT 'F10','mean_cost_b',mean_cost_b FROM risk WHERE hedge_ratio=0
UNION ALL SELECT 'F10','spot_run_rate_b',jet_fuel_gal*1.5 FROM market
UNION ALL SELECT 'F10','simulation_hedge_change_b',max(CASE WHEN hedge_ratio=.8 THEN mean_cost_b END)-max(CASE WHEN hedge_ratio=0 THEN mean_cost_b END) FROM risk
UNION ALL SELECT 'F10','historical_hedge_change_b',avg(CASE WHEN hedge_ratio=.8 THEN budget_overrun_b END)-avg(CASE WHEN hedge_ratio=0 THEN budget_overrun_b END) FROM backtest
UNION ALL SELECT 'F10','mean_vs_spot',r.mean_cost_b/(m.jet_fuel_gal*1.5)-1 FROM risk r CROSS JOIN market m WHERE hedge_ratio=0
UNION ALL SELECT 'F10','cvar_unhedged',cvar_95_b FROM risk WHERE hedge_ratio=0
UNION ALL SELECT 'F10','cvar_80',cvar_95_b FROM risk WHERE hedge_ratio=.8
UNION ALL SELECT 'F10','terminal_median',p50_price_gal FROM jet_fuel_gold.price_fan_current WHERE step=(SELECT max(step) FROM jet_fuel_gold.price_fan_current)
UNION ALL SELECT 'F10','historical_p95_move',percentile_cont(.95) WITHIN GROUP(ORDER BY realized_avg/s0-1) FROM backtest WHERE hedge_ratio=0
UNION ALL SELECT 'F11','break_even',exp(.04)-1
UNION ALL SELECT 'F11','minus30_cost_b',hedged_cost_b-unhedged_cost_b FROM jet_fuel_gold.v_hedge_sensitivity WHERE hedge_ratio=.8 AND price_change_pct=-30
UNION ALL SELECT 'F11','plus50_cost_b',hedged_cost_b-unhedged_cost_b FROM jet_fuel_gold.v_hedge_sensitivity WHERE hedge_ratio=.8 AND price_change_pct=50
UNION ALL SELECT 'F12','b767_departures',sum(daily_frequencies) FROM jet_fuel_gold.dim_route WHERE aircraft_type='B767'
UNION ALL SELECT 'F12','b767_gallon_share',sum(CASE WHEN aircraft_type='B767' THEN daily_frequencies*avg_fuel_burn_gal END)/sum(daily_frequencies*avg_fuel_burn_gal) FROM jet_fuel_gold.dim_route
UNION ALL SELECT 'F12','route_savings_80_m',sum(hedge_savings_usd)/1e6 FROM jet_fuel_gold.route_fuel_costs_current WHERE hedge_ratio=.8
)
SELECT * FROM numbers WHERE (SELECT analytics_ready AND risk_ready AND insights_ready FROM jet_fuel_gold.reporting_readiness);
