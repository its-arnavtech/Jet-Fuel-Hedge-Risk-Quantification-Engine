# Databricks notebook source
# MAGIC %md
# MAGIC # Historical evidence and walk-forward GBM validation
# MAGIC Actual EIA prices; budget costs use the reference 1.5B gallon/year carrier.
# MAGIC No change to production calibration or simulation defaults. Not a forecast.

# COMMAND ----------
import re
from uuid import uuid4

from pyspark.sql import functions as F

dbutils.widgets.text("catalog", "workspace")
dbutils.widgets.text("n_paths", "10000")
dbutils.widgets.text("base_seed", "20261021")
catalog = dbutils.widgets.get("catalog")
if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", catalog):
    raise ValueError("Invalid catalog")
spark.sql(f"USE CATALOG `{catalog}`")
for schema in ["jet_fuel_bronze", "jet_fuel_silver", "jet_fuel_gold"]:
    metadata = spark.sql(f"DESCRIBE SCHEMA EXTENDED `{schema}`").collect()
    if not any(r[1] == "Jet Fuel Hedge Risk Quantification Engine managed schema v1" for r in metadata):
        raise ValueError("Unowned project schema")
source = spark.sql("SELECT * FROM jet_fuel_silver.pipeline_runs ORDER BY started_at DESC LIMIT 1").first()
quality = spark.table("jet_fuel_silver.ingestion_quality").first()
if not source or not quality or source.status != "SUCCESS" or source.pipeline_run_id != quality.pipeline_run_id:
    raise ValueError("Latest Silver publication must be SUCCESS")
source_id = source.pipeline_run_id
run_id = str(uuid4())
spark.sql("""CREATE TABLE IF NOT EXISTS jet_fuel_gold.insights_runs (
 insights_run_id STRING,source_pipeline_run_id STRING,started_at TIMESTAMP,
 completed_at TIMESTAMP,status STRING,n_paths INT,base_seed BIGINT,execution_mode STRING
) USING DELTA""")
n_paths = int(dbutils.widgets.get("n_paths"))
seed = int(dbutils.widgets.get("base_seed"))
if n_paths != 10000:
    raise ValueError("Published walk-forward evidence requires 10,000 paths")
spark.sql(f"""INSERT INTO jet_fuel_gold.insights_runs VALUES (
 '{run_id}','{source_id}',current_timestamp(),NULL,'STARTED',{n_paths},{seed},'mapInPandas')""")

# COMMAND ----------
# INJECT_SIMULATION_MODULE
# INJECT_INSIGHTS_MODULE

# COMMAND ----------
daily = spark.table("jet_fuel_silver.fuel_prices").toPandas()
weekly = spark.table("jet_fuel_silver.weekly_fuel_prices").toPandas()
tables = deterministic_tables(daily, weekly)
inputs = forecast_inputs(tables["calibration_history"], tables["hedge_backtest_windows"])
inputs["window_index"] = range(len(inputs))


def compute_windows(batches):
    for batch in batches:
        for row in batch.to_dict("records"):
            yield forecast_window(row, int(row["window_index"]), n_paths, seed)


forecast_schema = ("window_start timestamp,drift_model string,p05 double,p50 double,p95 double,"
                   "mean double,realized_avg double,inside_band boolean,below_p05 boolean,"
                   "above_p95 boolean,log_err_p50 double,high_drift boolean,mu_ewm double,"
                   "n_paths long,window_index long,base_seed long")
forecast = spark.createDataFrame(inputs).repartition(8).mapInPandas(compute_windows, forecast_schema)


def lineage(frame):
    for name, dtype in frame.dtypes:
        if dtype in {"double", "float"}:
            frame = frame.withColumn(name, F.when(F.isnan(name), F.lit(None)).otherwise(F.col(name)))
    return (frame.withColumn("insights_run_id", F.lit(run_id))
            .withColumn("source_pipeline_run_id", F.lit(source_id))
            .withColumn("created_ts", F.current_timestamp()).withColumn("is_synthetic", F.lit(False)))


counts = []
for name, frame in tables.items():
    output = spark.createDataFrame(frame)
    for col in ["price_date", "week_ending", "window_start"]:
        if col in frame:
            output = output.withColumn(col, F.to_date(col))
    output = lineage(output)
    # All new facts retain run history. STARTED blocks publication during partial writes.
    output.write.mode("append").saveAsTable(f"jet_fuel_gold.{name}")
    counts.append((name, len(frame)))
forecast = lineage(forecast.withColumn("window_start", F.to_date("window_start")))
forecast.write.mode("append").saveAsTable("jet_fuel_gold.forecast_backtest")
counts.append(("forecast_backtest", len(inputs)*3))
quality_rows = spark.createDataFrame(counts, "table_name string,expected_rows long")
quality_rows = lineage(quality_rows).withColumnRenamed("created_ts", "checked_at")
quality_rows.write.mode("append").saveAsTable("jet_fuel_gold.insights_quality")
for name, expected in counts:
    count = spark.table(f"jet_fuel_gold.{name}").where(F.col("insights_run_id") == run_id).count()
    if count != expected or expected <= 0:
        raise ValueError(f"Insight publication row count mismatch: {name}")
latest = spark.sql("SELECT * FROM jet_fuel_silver.pipeline_runs ORDER BY started_at DESC LIMIT 1").first()
quality_now = spark.table("jet_fuel_silver.ingestion_quality").first()
if latest.status != "SUCCESS" or latest.pipeline_run_id != source_id or quality_now.pipeline_run_id != source_id:
    raise ValueError("Silver changed during insights calculation")
spark.sql(f"""UPDATE jet_fuel_gold.insights_runs SET status='SUCCESS',completed_at=current_timestamp()
 WHERE insights_run_id='{run_id}'""")
# INJECT_INSIGHTS_SQL
display(spark.table("jet_fuel_gold.insights_publication_ready"))
