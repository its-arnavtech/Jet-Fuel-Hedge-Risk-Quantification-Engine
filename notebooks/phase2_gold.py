# Databricks notebook source
# MAGIC %md
# MAGIC # Synthetic operations and Gold treasury analytics
# MAGIC Actual EIA prices, explicitly synthetic routes/flights/positions. Historical hedge costs
# MAGIC are counterfactual scenarios using a simplified one-year forward fixed at the window start.

# COMMAND ----------
import re
from uuid import uuid4

from pyspark.sql import functions as F

dbutils.widgets.text("catalog", "workspace")
dbutils.widgets.text("snapshot_id", "")
catalog, snapshot = dbutils.widgets.get("catalog"), dbutils.widgets.get("snapshot_id")
if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", catalog) or not re.fullmatch(r"[a-f0-9]{64}", snapshot):
    raise ValueError("Invalid catalog or snapshot ID")
spark.sql(f"USE CATALOG `{catalog}`")
marker = "Jet Fuel Hedge Risk Quantification Engine managed schema v1"
for schema in ["jet_fuel_bronze", "jet_fuel_silver", "jet_fuel_gold"]:
    if not any(r[1] == marker for r in spark.sql(f"DESCRIBE SCHEMA EXTENDED `{schema}`").collect()):
        raise ValueError("Unowned project schema")
latest = spark.sql("SELECT * FROM jet_fuel_silver.pipeline_runs ORDER BY started_at DESC LIMIT 1").first()
quality = spark.table("jet_fuel_silver.ingestion_quality").first()
if latest.status != "SUCCESS" or latest.pipeline_run_id != quality.pipeline_run_id:
    raise ValueError("Silver publication is not ready")
gold_run_id = str(uuid4())
spark.sql("""CREATE TABLE IF NOT EXISTS jet_fuel_gold.pipeline_runs
(pipeline_run_id STRING, started_at TIMESTAMP, completed_at TIMESTAMP, status STRING) USING DELTA""")
spark.sql(f"INSERT INTO jet_fuel_gold.pipeline_runs VALUES ('{gold_run_id}',current_timestamp(),NULL,'STARTED')")
volume = f"/Volumes/{catalog}/jet_fuel_bronze/landing/operations/{snapshot}"

# COMMAND ----------
for name, key in [("routes", "route_id"), ("flights", "flight_id"), ("hedge_positions", "position_id")]:
    frame = spark.read.json(f"{volume}/{name}.jsonl").withColumn("snapshot_id", F.lit(snapshot))
    if frame.where("is_synthetic != true OR is_synthetic IS NULL").limit(1).count():
        raise ValueError("Synthetic source flag missing")
    if frame.groupBy(key).count().where("count > 1").limit(1).count():
        raise ValueError(f"Duplicate {key}")
    frame.createOrReplaceTempView(f"raw_{name}")
    spark.sql(f"""CREATE TABLE IF NOT EXISTS jet_fuel_bronze.synthetic_{name}
    USING DELTA TBLPROPERTIES ('delta.appendOnly'='true') AS SELECT * FROM raw_{name} WHERE false""")
    spark.sql(f"""MERGE INTO jet_fuel_bronze.synthetic_{name} t USING raw_{name} s
    ON t.snapshot_id=s.snapshot_id AND t.{key}=s.{key} WHEN NOT MATCHED THEN INSERT *""")

spark.sql("""CREATE OR REPLACE TEMP VIEW routes_candidate AS
SELECT * EXCEPT(effective_dt,expiry_dt),cast(effective_dt AS DATE) AS effective_dt,
cast(expiry_dt AS DATE) AS expiry_dt FROM raw_routes""")
spark.sql("""CREATE OR REPLACE TEMP VIEW flights_candidate AS
SELECT * EXCEPT(flight_date),cast(flight_date AS DATE) AS flight_date FROM raw_flights""")
spark.sql("""CREATE OR REPLACE TEMP VIEW positions_candidate AS
SELECT * EXCEPT(position_date,expiry_dt),cast(position_date AS DATE) AS position_date,
cast(expiry_dt AS DATE) AS expiry_dt FROM raw_hedge_positions""")
if spark.sql("""SELECT f.flight_id FROM flights_candidate f LEFT JOIN routes_candidate r
ON f.route_id=r.route_id AND f.flight_date>=r.effective_dt AND f.flight_date<r.expiry_dt
WHERE r.route_id IS NULL""").limit(1).count():
    raise ValueError("Flight has no valid-time route")
for name, view in [("routes", "routes_candidate"), ("flights", "flights_candidate"),
                   ("hedge_positions", "positions_candidate")]:
    spark.sql(f"CREATE OR REPLACE TABLE jet_fuel_silver.{name} USING DELTA AS SELECT * FROM {view}")

# COMMAND ----------
spark.sql("""CREATE OR REPLACE TABLE jet_fuel_gold.dim_date USING DELTA AS
WITH calendar AS (
 SELECT explode(sequence((SELECT min(price_date) FROM jet_fuel_silver.fuel_prices),
 (SELECT max(price_date) FROM jet_fuel_silver.fuel_prices),INTERVAL 1 DAY)) AS calendar_date
), marked AS (
 SELECT c.calendar_date,
 last_value(CASE WHEN p.price_date IS NOT NULL THEN named_struct('price_date',p.price_date,
 'spot',p.jet_fuel_gal,'vol',p.rolling_vol_90d) END,true) OVER(ORDER BY c.calendar_date
 ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS mark
 FROM calendar c LEFT JOIN jet_fuel_silver.fuel_prices p ON c.calendar_date=p.price_date
)
SELECT calendar_date,cast(date_format(calendar_date,'yyyyMMdd') AS INT) AS date_id,
 cast(date_trunc('month',calendar_date) AS DATE) AS cost_month,year(calendar_date) AS year,
 month(calendar_date) AS month,mark.price_date AS price_observation_date,
 datediff(calendar_date,mark.price_date) AS price_age_days,
 mark.spot AS spot_price_gal,mark.vol AS rolling_vol_90d,'EIA_ASOF_LAST_AVAILABLE' AS price_basis
FROM marked""")
if spark.sql("""SELECT f.flight_id FROM jet_fuel_silver.flights f
LEFT JOIN jet_fuel_gold.dim_date d ON f.flight_date=d.calendar_date
WHERE NOT f.cancelled AND (d.spot_price_gal IS NULL OR d.price_age_days>7)""").limit(1).count():
    raise ValueError("Missing or stale flight-date fuel mark")

spark.sql("""CREATE OR REPLACE TABLE jet_fuel_gold.dim_month USING DELTA AS
SELECT DISTINCT cost_month,year(cost_month) AS year,month(cost_month) AS month FROM jet_fuel_gold.dim_date""")
spark.sql("""CREATE OR REPLACE TABLE jet_fuel_gold.dim_route USING DELTA AS
SELECT * FROM jet_fuel_silver.routes""")
spark.sql("""CREATE OR REPLACE TABLE jet_fuel_gold.dim_hedge_scenario USING DELTA AS
SELECT concat('H',lpad(cast(cast(100*hedge_ratio AS INT) AS STRING),3,'0')) AS scenario_id,
hedge_ratio,concat(cast(cast(100*hedge_ratio AS INT) AS STRING),'% futures') AS scenario_label
FROM (SELECT explode(array(0.0D,0.2D,0.4D,0.6D,0.8D)) AS hedge_ratio)""")

# COMMAND ----------
spark.sql("""CREATE OR REPLACE TABLE jet_fuel_gold.route_fuel_costs USING DELTA AS
WITH monthly AS (
 SELECT r.route_id,r.aircraft_type,d.cost_month,count(*) AS monthly_flights,
 sum(r.avg_fuel_burn_gal) AS monthly_gallons,
 sum(r.avg_fuel_burn_gal*d.spot_price_gal) AS unhedged_cost_usd,
 max(d.price_observation_date) AS price_observation_date,
 max(d.price_age_days) AS max_price_age_days,avg(d.rolling_vol_90d) AS rolling_vol_90d
 FROM jet_fuel_silver.flights f JOIN jet_fuel_silver.routes r
 ON f.route_id=r.route_id AND f.flight_date>=r.effective_dt AND f.flight_date<r.expiry_dt
 JOIN jet_fuel_gold.dim_date d ON f.flight_date=d.calendar_date
 WHERE NOT f.cancelled GROUP BY r.route_id,r.aircraft_type,d.cost_month
), contract AS (
 SELECT d.spot_price_gal*exp(0.04) AS locked_price_gal,d.calendar_date AS hedge_start_date
 FROM jet_fuel_gold.dim_date d
 WHERE d.calendar_date=(SELECT min(flight_date) FROM jet_fuel_silver.flights)
), costs AS (
 SELECT m.*,m.unhedged_cost_usd/m.monthly_gallons AS spot_price_gal,s.scenario_id,s.hedge_ratio,
 c.locked_price_gal,c.hedge_start_date,
 s.hedge_ratio*c.locked_price_gal*m.monthly_gallons+(1-s.hedge_ratio)*m.unhedged_cost_usd AS hedged_cost_usd
 FROM monthly m CROSS JOIN jet_fuel_gold.dim_hedge_scenario s CROSS JOIN contract c
)
SELECT *,hedged_cost_usd-unhedged_cost_usd AS hedge_pnl_usd,
unhedged_cost_usd-hedged_cost_usd AS hedge_savings_usd,
sha2(concat(route_id,'|',cast(cost_month AS STRING),'|',scenario_id),256) AS cost_id,
true AS is_synthetic,'HYPOTHETICAL_WINDOW_START_ONE_YEAR_FORWARD' AS hedge_basis,
current_timestamp() AS updated_ts FROM costs""")
spark.sql("""CREATE TABLE IF NOT EXISTS jet_fuel_silver.simulation_raw_paths (
 simulation_run_id STRING,path_id BIGINT,hedge_ratio DOUBLE,simulated_total_cost_b DOUBLE
) USING DELTA""")

# COMMAND ----------
# The deployment script appends all six versioned SQL view definitions here.
