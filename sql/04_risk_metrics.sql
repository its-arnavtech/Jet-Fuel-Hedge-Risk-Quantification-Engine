CREATE OR REPLACE VIEW jet_fuel_gold.v_risk_metrics AS
WITH cost_stats AS (
 SELECT simulation_run_id, hedge_ratio, count(*) AS n_paths,
   avg(simulated_total_cost_b) AS mean_cost_b,
   percentile_cont(0.50) WITHIN GROUP(ORDER BY simulated_total_cost_b) AS p50_cost_b,
   percentile_cont(0.95) WITHIN GROUP(ORDER BY simulated_total_cost_b) AS p95_cost_b
 FROM jet_fuel_silver.simulation_raw_paths GROUP BY simulation_run_id, hedge_ratio
), tails AS (
 SELECT s.simulation_run_id, s.hedge_ratio, avg(p.simulated_total_cost_b) AS cvar_95_b
 FROM cost_stats s JOIN jet_fuel_silver.simulation_raw_paths p
 ON s.simulation_run_id=p.simulation_run_id AND s.hedge_ratio=p.hedge_ratio
 WHERE p.simulated_total_cost_b >= s.p95_cost_b GROUP BY s.simulation_run_id,s.hedge_ratio
), metrics AS (
 SELECT s.*, s.p95_cost_b-s.mean_cost_b AS var_95_b, t.cvar_95_b
 FROM cost_stats s JOIN tails t USING(simulation_run_id,hedge_ratio)
)
SELECT m.*, CASE WHEN abs(b.var_95_b)>1e-12 THEN
  100.0*(b.var_95_b-m.var_95_b)/b.var_95_b END AS var_reduction_pct
FROM metrics m JOIN metrics b ON m.simulation_run_id=b.simulation_run_id AND b.hedge_ratio=0.0;
