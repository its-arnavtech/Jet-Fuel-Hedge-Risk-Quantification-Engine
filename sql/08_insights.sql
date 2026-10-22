-- Additive Phase 5 publication. Never falls back past a newer STARTED run.
CREATE OR REPLACE VIEW jet_fuel_gold.insights_publication_ready AS
WITH latest AS (
 SELECT * FROM jet_fuel_gold.insights_runs
 QUALIFY row_number() OVER(ORDER BY started_at DESC,insights_run_id DESC)=1
), source AS (
 SELECT * FROM jet_fuel_silver.pipeline_runs
 QUALIFY row_number() OVER(ORDER BY started_at DESC,pipeline_run_id DESC)=1
), actual AS (
SELECT 'market_decomposition' AS table_name,insights_run_id,count(*) AS actual_rows FROM jet_fuel_gold.market_decomposition GROUP BY insights_run_id
UNION ALL
SELECT 'proxy_return_correlation' AS table_name,insights_run_id,count(*) AS actual_rows FROM jet_fuel_gold.proxy_return_correlation GROUP BY insights_run_id
UNION ALL
SELECT 'proxy_effectiveness_annual' AS table_name,insights_run_id,count(*) AS actual_rows FROM jet_fuel_gold.proxy_effectiveness_annual GROUP BY insights_run_id
UNION ALL
SELECT 'hedge_backtest_windows' AS table_name,insights_run_id,count(*) AS actual_rows FROM jet_fuel_gold.hedge_backtest_windows GROUP BY insights_run_id
UNION ALL
SELECT 'calibration_history' AS table_name,insights_run_id,count(*) AS actual_rows FROM jet_fuel_gold.calibration_history GROUP BY insights_run_id
UNION ALL
SELECT 'forecast_backtest' AS table_name,insights_run_id,count(*) AS actual_rows FROM jet_fuel_gold.forecast_backtest GROUP BY insights_run_id
UNION ALL
SELECT 'return_tail_frequency' AS table_name,insights_run_id,count(*) AS actual_rows FROM jet_fuel_gold.return_tail_frequency GROUP BY insights_run_id
), checked AS (
 SELECT i.insights_run_id,count(*) AS quality_rows,count(DISTINCT q.table_name) AS distinct_tables,
 sum(CASE WHEN q.expected_rows>0 AND q.expected_rows=a.actual_rows
 AND q.source_pipeline_run_id=i.source_pipeline_run_id THEN 1 ELSE 0 END) AS matching_tables
 FROM latest i JOIN jet_fuel_gold.insights_quality q USING(insights_run_id)
 LEFT JOIN actual a ON a.insights_run_id=q.insights_run_id AND a.table_name=q.table_name
 GROUP BY i.insights_run_id
)
SELECT i.insights_run_id,i.source_pipeline_run_id,i.completed_at,
 coalesce(i.status='SUCCESS' AND s.status='SUCCESS' AND i.source_pipeline_run_id=s.pipeline_run_id
 AND sq.pipeline_run_id=s.pipeline_run_id AND c.quality_rows=7 AND c.distinct_tables=7
 AND c.matching_tables=7,false) AS insights_ready
FROM latest i CROSS JOIN source s CROSS JOIN jet_fuel_silver.ingestion_quality sq
LEFT JOIN checked c USING(insights_run_id);

CREATE OR REPLACE VIEW jet_fuel_gold.market_decomposition_current AS
SELECT f.* FROM jet_fuel_gold.market_decomposition f JOIN jet_fuel_gold.insights_publication_ready r
USING(insights_run_id,source_pipeline_run_id) WHERE r.insights_ready;

CREATE OR REPLACE VIEW jet_fuel_gold.proxy_return_correlation_current AS
SELECT f.* FROM jet_fuel_gold.proxy_return_correlation f JOIN jet_fuel_gold.insights_publication_ready r
USING(insights_run_id,source_pipeline_run_id) WHERE r.insights_ready;

CREATE OR REPLACE VIEW jet_fuel_gold.proxy_effectiveness_annual_current AS
SELECT f.* FROM jet_fuel_gold.proxy_effectiveness_annual f JOIN jet_fuel_gold.insights_publication_ready r
USING(insights_run_id,source_pipeline_run_id) WHERE r.insights_ready;

CREATE OR REPLACE VIEW jet_fuel_gold.hedge_backtest_windows_current AS
SELECT f.* FROM jet_fuel_gold.hedge_backtest_windows f JOIN jet_fuel_gold.insights_publication_ready r
USING(insights_run_id,source_pipeline_run_id) WHERE r.insights_ready;

CREATE OR REPLACE VIEW jet_fuel_gold.calibration_history_current AS
SELECT f.* FROM jet_fuel_gold.calibration_history f JOIN jet_fuel_gold.insights_publication_ready r
USING(insights_run_id,source_pipeline_run_id) WHERE r.insights_ready;

CREATE OR REPLACE VIEW jet_fuel_gold.forecast_backtest_current AS
SELECT f.* FROM jet_fuel_gold.forecast_backtest f JOIN jet_fuel_gold.insights_publication_ready r
USING(insights_run_id,source_pipeline_run_id) WHERE r.insights_ready;

CREATE OR REPLACE VIEW jet_fuel_gold.return_tail_frequency_current AS
SELECT f.* FROM jet_fuel_gold.return_tail_frequency f JOIN jet_fuel_gold.insights_publication_ready r
USING(insights_run_id,source_pipeline_run_id) WHERE r.insights_ready;

CREATE OR REPLACE VIEW jet_fuel_gold.v_market_decomposition AS
SELECT * FROM jet_fuel_gold.market_decomposition_current;
