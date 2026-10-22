-- Stable Power BI/dashboard views publish only complete current-source results.
CREATE OR REPLACE VIEW jet_fuel_gold.reporting_readiness AS
WITH source AS (
 SELECT * FROM jet_fuel_silver.pipeline_runs QUALIFY row_number() OVER(ORDER BY started_at DESC)=1
), analytics AS (
 SELECT * FROM jet_fuel_gold.pipeline_runs QUALIFY row_number() OVER(ORDER BY started_at DESC)=1
)
SELECT s.pipeline_run_id AS source_pipeline_run_id,a.pipeline_run_id AS analytics_pipeline_run_id,
 r.simulation_run_id,r.price_as_of,r.n_paths,r.completed_at AS simulation_completed_at,
 (s.status='SUCCESS' AND sq.pipeline_run_id=s.pipeline_run_id
 AND a.status='SUCCESS' AND aq.pipeline_run_id=a.pipeline_run_id
 AND aq.source_pipeline_run_id=s.pipeline_run_id) AS analytics_ready,
 (s.status='SUCCESS' AND sq.pipeline_run_id=s.pipeline_run_id
 AND a.status='SUCCESS' AND aq.pipeline_run_id=a.pipeline_run_id
 AND aq.source_pipeline_run_id=s.pipeline_run_id AND r.source_pipeline_run_id=s.pipeline_run_id
 AND q.simulation_run_id=r.simulation_run_id AND q.cost_rows=r.n_paths*5
 AND q.fan_steps=cast(round(r.horizon_years*52) AS INT)+1) AS risk_ready,
 coalesce((SELECT insights_ready FROM jet_fuel_gold.insights_publication_ready),false) AS insights_ready
FROM source s CROSS JOIN analytics a
CROSS JOIN jet_fuel_silver.ingestion_quality sq CROSS JOIN jet_fuel_gold.analytics_quality aq
LEFT JOIN jet_fuel_gold.latest_simulation_run r ON true
LEFT JOIN jet_fuel_gold.simulation_quality q USING(simulation_run_id);

CREATE OR REPLACE VIEW jet_fuel_gold.route_fuel_costs_current AS
SELECT c.* FROM jet_fuel_gold.route_fuel_costs c
CROSS JOIN jet_fuel_gold.reporting_readiness r WHERE r.analytics_ready;

CREATE OR REPLACE VIEW jet_fuel_gold.risk_metrics_current AS
SELECT c.* FROM jet_fuel_gold.risk_metrics c JOIN jet_fuel_gold.reporting_readiness r
USING(simulation_run_id) WHERE r.risk_ready;

CREATE OR REPLACE VIEW jet_fuel_gold.price_fan_current AS
SELECT c.* FROM jet_fuel_gold.price_fan c JOIN jet_fuel_gold.reporting_readiness r
USING(simulation_run_id) WHERE r.risk_ready;

CREATE OR REPLACE VIEW jet_fuel_gold.cost_histogram_current AS
SELECT c.* FROM jet_fuel_gold.cost_histogram c JOIN jet_fuel_gold.reporting_readiness r
USING(simulation_run_id) WHERE r.risk_ready;
