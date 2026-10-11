# Databricks notebook source
# MAGIC %md
# MAGIC # EIA Bronze and Silver pipeline
# MAGIC Serverless Free Edition. Run after local EIA capture and immutable volume staging.
# MAGIC No credentials are embedded. Prices are actual EIA data; routes and risk are later phases.

# COMMAND ----------
import re
from uuid import uuid4

from pyspark.sql import functions as F
from pyspark.sql.types import LongType, StringType, StructField, StructType

dbutils.widgets.text("catalog", "workspace")
catalog = dbutils.widgets.get("catalog")
if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", catalog):
    raise ValueError("Invalid catalog")
spark.sql(f"USE CATALOG `{catalog}`")
volume = f"/Volumes/{catalog}/jet_fuel_bronze/landing"
marker = "Jet Fuel Hedge Risk Quantification Engine managed schema v1"
for schema in ["jet_fuel_bronze", "jet_fuel_silver", "jet_fuel_gold"]:
    metadata = spark.sql(f"DESCRIBE SCHEMA EXTENDED `{catalog}`.`{schema}`").collect()
    if not any(len(row) > 1 and row[1] == marker for row in metadata):
        raise ValueError(f"Refusing to publish in an unowned schema: {schema}")
pipeline_run_id = str(uuid4())
spark.sql("""
CREATE TABLE IF NOT EXISTS jet_fuel_silver.pipeline_runs (
  pipeline_run_id STRING, started_at TIMESTAMP, completed_at TIMESTAMP, status STRING
) USING DELTA
""")
spark.sql(f"""
INSERT INTO jet_fuel_silver.pipeline_runs
VALUES ('{pipeline_run_id}', current_timestamp(), NULL, 'STARTED')
""")

# COMMAND ----------
# Explicit schema makes replay deterministic. Raw JSON is retained after credential redaction.
envelope_schema = StructType([
    StructField(name, LongType() if name == "offset" else StringType(), True)
    for name in ["capture_id", "event_id", "fetched_at", "payload_sha256", "source",
                 "endpoint", "frequency", "start", "end", "offset", "payload_json"]
])
spark.sql("""
CREATE TABLE IF NOT EXISTS jet_fuel_bronze.eia_price_events (
  capture_id STRING, event_id STRING, fetched_at STRING, payload_sha256 STRING,
  source STRING, endpoint STRING, frequency STRING, start STRING, end STRING,
  offset BIGINT, payload_json STRING
) USING DELTA TBLPROPERTIES ('delta.appendOnly' = 'true')
""")
query = (spark.readStream.schema(envelope_schema).option("mode", "FAILFAST")
         .json(f"{volume}/captures")
         .writeStream.option("checkpointLocation", f"{volume}/checkpoints/eia_v1")
         .trigger(availableNow=True).toTable(f"{catalog}.jet_fuel_bronze.eia_price_events"))
query.awaitTermination()

# COMMAND ----------
# Validate stream envelope and hashes before touching Silver.
events = spark.table("jet_fuel_bronze.eia_price_events")
bad_envelopes = events.where(
    F.col("event_id").isNull() | F.col("capture_id").isNull()
    | F.col("payload_json").isNull() | F.col("payload_sha256").isNull()
    | F.col("source").isNull() | F.col("frequency").isNull()
    | (F.sha2("payload_json", 256) != F.col("payload_sha256"))
    | (F.col("source") != "EIA") | (F.col("frequency") != "daily")
)
if bad_envelopes.limit(1).count():
    raise ValueError("Bronze contains invalid envelopes; inspect capture integrity")
if not events.limit(1).count():
    raise ValueError("Bronze is empty")

spark.sql("""
CREATE OR REPLACE TEMP VIEW eia_observations AS
SELECT e.capture_id, e.event_id, try_cast(e.fetched_at AS TIMESTAMP) AS fetched_at,
       o.period, o.series, o.value, o.units,
       try_cast(o.period AS DATE) AS price_date,
       try_cast(o.value AS DOUBLE) AS numeric_value
FROM jet_fuel_bronze.eia_price_events e
LATERAL VIEW explode(from_json(e.payload_json,
  'STRUCT<response:STRUCT<data:ARRAY<STRUCT<period:STRING,series:STRING,value:STRING,units:STRING>>>>'
).response.data) obs AS o
""")
spark.sql("""
CREATE OR REPLACE TEMP VIEW eia_latest AS
SELECT * EXCEPT (revision_rank) FROM (
  SELECT *, row_number() OVER (
    PARTITION BY price_date, series ORDER BY fetched_at DESC, event_id DESC
  ) AS revision_rank FROM eia_observations
) WHERE revision_rank = 1
""")
spark.sql("""
CREATE OR REPLACE TEMP VIEW eia_checked AS
SELECT *, CASE
  WHEN price_date IS NULL OR fetched_at IS NULL THEN 'invalid_date_or_ingest_timestamp'
  WHEN series IS NULL OR series NOT IN ('EER_EPJK_PF4_RGC_DPG','RWTC','RBRTE','EER_EPD2F_PF4_Y35NY_DPG')
    THEN 'unknown_series'
  WHEN units IS NULL
    OR (series IN ('RWTC','RBRTE') AND units NOT IN ('$/BBL','Dollars per Barrel'))
    OR (series NOT IN ('RWTC','RBRTE') AND units NOT IN ('$/GAL','Dollars per Gallon'))
    THEN 'unit_mismatch'
  WHEN numeric_value IS NULL OR isnan(numeric_value)
    OR abs(numeric_value) = cast('Infinity' AS DOUBLE)
    OR (series = 'EER_EPJK_PF4_RGC_DPG' AND numeric_value <= 0)
    THEN 'missing_or_invalid_price'
  ELSE NULL END AS rejection_reason
FROM eia_latest
""")
spark.sql("""
CREATE OR REPLACE TEMP VIEW eia_quarantine_candidate AS
SELECT * FROM eia_checked WHERE rejection_reason IS NOT NULL
""")

# COMMAND ----------
spark.sql("""
CREATE OR REPLACE TEMP VIEW eia_daily AS
SELECT price_date,
  max(CASE WHEN series='EER_EPJK_PF4_RGC_DPG' THEN numeric_value END) AS jet_fuel_gal,
  max(CASE WHEN series='RWTC' THEN numeric_value END) AS wti_spot_bbl,
  max(CASE WHEN series='RBRTE' THEN numeric_value END) AS brent_spot_bbl,
  max(CASE WHEN series='EER_EPD2F_PF4_Y35NY_DPG' THEN numeric_value END) AS heating_oil_gal,
  max(CASE WHEN series='EER_EPJK_PF4_RGC_DPG' THEN fetched_at END) AS fetched_at,
  max(CASE WHEN series='EER_EPJK_PF4_RGC_DPG' THEN capture_id END) AS capture_id,
  max(CASE WHEN series='EER_EPJK_PF4_RGC_DPG' THEN event_id END) AS event_id
FROM eia_checked WHERE rejection_reason IS NULL GROUP BY price_date
""")
spark.sql("""
CREATE OR REPLACE TEMP VIEW eia_returns AS
SELECT *, jet_fuel_gal - wti_spot_bbl / 42.0 AS crack_spread,
  ln(jet_fuel_gal / lag(jet_fuel_gal) OVER (ORDER BY price_date)) AS log_return,
  datediff(price_date, lag(price_date) OVER (ORDER BY price_date)) AS return_gap_days
FROM eia_daily WHERE jet_fuel_gal > 0
""")
spark.sql("""
CREATE OR REPLACE TEMP VIEW eia_prices_candidate AS
SELECT *, coalesce(return_gap_days > 4, false) AS long_return_gap,
  CASE WHEN count(log_return) OVER w >= 20
    AND max(coalesce(return_gap_days, 0)) OVER w <= 4 THEN stddev_samp(log_return) OVER w * sqrt(252) END
    AS rolling_vol_90d,
  CASE WHEN count(CASE WHEN wti_spot_bbl IS NOT NULL THEN 1 END) OVER w >= 20
    THEN corr(wti_spot_bbl, jet_fuel_gal) OVER w END AS rolling_corr_90d,
  'EIA' AS source, false AS is_synthetic, 'US Gulf Coast' AS jet_region,
  sha2(concat('EIA|', cast(price_date AS STRING), '|US_GULF'), 256) AS price_id
FROM eia_returns
WINDOW w AS (ORDER BY unix_date(price_date) RANGE BETWEEN 89 PRECEDING AND CURRENT ROW)
""")
if not spark.table("eia_prices_candidate").limit(1).count():
    raise ValueError("No positive jet fuel prices in Silver")

# COMMAND ----------
# Friday-ended complete weeks, latest available observation (Thursday on a Friday holiday).
spark.sql("""
CREATE OR REPLACE TEMP VIEW eia_week_ranked AS
SELECT *, date_add(price_date, pmod(6 - dayofweek(price_date), 7)) AS week_ending,
  row_number() OVER (
    PARTITION BY date_add(price_date, pmod(6 - dayofweek(price_date), 7))
    ORDER BY price_date DESC
  ) AS week_rank
FROM eia_prices_candidate
""")
spark.sql("""
CREATE OR REPLACE TEMP VIEW eia_weekly_candidate AS
SELECT week_ending, price_date AS observation_date, jet_fuel_gal,
  ln(jet_fuel_gal / lag(jet_fuel_gal) OVER (ORDER BY week_ending)) AS log_return,
  'EIA' AS source, false AS is_synthetic
FROM eia_week_ranked WHERE week_rank=1
AND week_ending <= (SELECT max(price_date) FROM eia_prices_candidate)
""")
weekly = spark.sql("""
SELECT week_ending, datediff(week_ending, lag(week_ending) OVER (ORDER BY week_ending)) AS gap
FROM eia_weekly_candidate
""")
if weekly.where("gap != 7").limit(1).count():
    raise ValueError("Missing calibration week; repair the source before simulation")
if weekly.count() < 26:
    raise ValueError("At least 26 complete weekly observations required")

# COMMAND ----------
# Publish only validated candidates. A partial publish leaves STARTED in pipeline_runs;
# downstream consumers must require the newest run to be SUCCESS and match quality.run_id.
spark.sql("""
CREATE OR REPLACE TABLE jet_fuel_silver.price_quarantine USING DELTA AS
SELECT * FROM eia_quarantine_candidate
""")
spark.sql("""
CREATE OR REPLACE TABLE jet_fuel_silver.fuel_prices USING DELTA
TBLPROPERTIES ('delta.enableChangeDataFeed'='true') AS
SELECT * FROM eia_prices_candidate
""")
spark.sql("""
CREATE OR REPLACE TABLE jet_fuel_silver.weekly_fuel_prices USING DELTA AS
SELECT * FROM eia_weekly_candidate
""")
# Persist observed counts/freshness with the completed publication watermark.
spark.sql(f"""
CREATE OR REPLACE TABLE jet_fuel_silver.ingestion_quality USING DELTA AS
SELECT '{pipeline_run_id}' AS pipeline_run_id, current_timestamp() AS checked_at,
  (SELECT count(*) FROM jet_fuel_bronze.eia_price_events) AS bronze_events,
  (SELECT count(*) FROM jet_fuel_silver.fuel_prices) AS daily_rows,
  (SELECT count(*) FROM jet_fuel_silver.weekly_fuel_prices) AS weekly_rows,
  (SELECT count(*) FROM jet_fuel_silver.price_quarantine) AS quarantine_rows,
  (SELECT count(*) FROM jet_fuel_silver.fuel_prices WHERE long_return_gap) AS long_return_gaps,
  (SELECT max(price_date) FROM jet_fuel_silver.fuel_prices) AS latest_price_date,
  'EIA' AS source, false AS is_synthetic
""")
spark.sql(f"""
UPDATE jet_fuel_silver.pipeline_runs SET status='SUCCESS', completed_at=current_timestamp()
WHERE pipeline_run_id='{pipeline_run_id}'
""")
display(spark.table("jet_fuel_silver.ingestion_quality"))
