# Databricks notebook source
# MAGIC %md
# MAGIC # Distributed GBM and calibrated hedge risk
# MAGIC A reference 1.5B gallon/year carrier with simplified futures carry, actual EIA calibration,
# MAGIC deterministic Box–Muller shocks and common price paths across ratios. No basis/options model.

# COMMAND ----------
import json
import math
import re
import time
from uuid import uuid4

import mlflow
import numpy as np
import pandas as pd

dbutils.widgets.text('catalog','workspace')
dbutils.widgets.text('n_paths','100000')
dbutils.widgets.text('seed','20261010')
dbutils.widgets.text('horizon_years','1.0')
dbutils.widgets.text('source_sha256','unknown')
catalog=dbutils.widgets.get('catalog')
if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',catalog):
    raise ValueError('Invalid catalog')
spark.sql(f'USE CATALOG `{catalog}`')
for schema in ['jet_fuel_bronze','jet_fuel_silver','jet_fuel_gold']:
    metadata=spark.sql(f'DESCRIBE SCHEMA EXTENDED `{schema}`').collect()
    if not any(r[1]=='Jet Fuel Hedge Risk Quantification Engine managed schema v1' for r in metadata):
        raise ValueError('Unowned project schema')
source=spark.sql('SELECT * FROM jet_fuel_silver.pipeline_runs ORDER BY started_at DESC LIMIT 1').first()
source_quality=spark.table('jet_fuel_silver.ingestion_quality').first()
gold_quality=spark.table('jet_fuel_gold.analytics_quality').first()
gold_latest=spark.sql('SELECT * FROM jet_fuel_gold.pipeline_runs ORDER BY started_at DESC LIMIT 1').first()
if (source.status!='SUCCESS' or source.pipeline_run_id!=source_quality.pipeline_run_id
        or gold_latest.status!='SUCCESS' or gold_latest.pipeline_run_id!=gold_quality.pipeline_run_id
        or gold_quality.source_pipeline_run_id!=source.pipeline_run_id):
    raise ValueError('Silver and operations Gold must be current and successful')

# COMMAND ----------
# Deployment injects the versioned pure NumPy calibration/simulation module here.
# INJECT_SIMULATION_MODULE

# COMMAND ----------
weekly=spark.table('jet_fuel_silver.weekly_fuel_prices').select('week_ending','jet_fuel_gal').toPandas()
calibration=calibrate(weekly)
latest_price=spark.sql('SELECT price_date,jet_fuel_gal FROM jet_fuel_silver.fuel_prices ORDER BY price_date DESC LIMIT 1').first()
config=SimulationConfig(s0=float(latest_price.jet_fuel_gal),mu=calibration['mu'],sigma=calibration['sigma'],
                         n_paths=int(dbutils.widgets.get('n_paths')),
                         seed=int(dbutils.widgets.get('seed')),
                         horizon_years=float(dbutils.widgets.get('horizon_years')))
run_id=str(uuid4())
user=spark.sql('SELECT current_user() AS user').first().user
mlflow.set_tracking_uri('databricks')
mlflow.set_registry_uri('databricks-uc')
mlflow.set_experiment(f'/Users/{user}/jet-fuel-hedge-engine/gbm')
started=time.monotonic()

# COMMAND ----------
spark.sql('''CREATE TABLE IF NOT EXISTS jet_fuel_silver.simulation_runs (
 simulation_run_id STRING,started_at TIMESTAMP,completed_at TIMESTAMP,status STRING,
 mlflow_run_id STRING,source_pipeline_run_id STRING,price_as_of DATE,
 n_paths INT,seed BIGINT,horizon_years DOUBLE,annual_gallons DOUBLE,s0 DOUBLE,
 mu DOUBLE,sigma DOUBLE,risk_free_rate DOUBLE,decay DOUBLE,n_calibration_returns INT,
 calibration_start DATE,calibration_end DATE,duration_seconds DOUBLE
) USING DELTA''')

with mlflow.start_run(run_name=f'jet_fuel_gbm_{config.n_paths}_paths') as tracked:
    mlflow_id=tracked.info.run_id
    params={**config.__dict__,**calibration,'s0_as_of':str(latest_price.price_date),
            'source_pipeline_run_id':source.pipeline_run_id,'simulation_run_id':run_id,
            'source_sha256':dbutils.widgets.get('source_sha256'),
            'numpy_version':np.__version__,'mlflow_version':mlflow.__version__,
            'normal_sampler':'Box-Muller/NumPy-PCG64/SeedSequence(base_seed,path_id)',
            'purchase_average':'future_weekly_periods_excluding_S0'}
    mlflow.log_params({k:json.dumps(v) if isinstance(v,(tuple,list)) else v for k,v in params.items()})
    mlflow.log_dict(params,'simulation_parameters.json')
    spark.sql(f"""INSERT INTO jet_fuel_silver.simulation_runs VALUES (
      '{run_id}',current_timestamp(),NULL,'STARTED','{mlflow_id}','{source.pipeline_run_id}',
      DATE'{latest_price.price_date}',{config.n_paths},{config.seed},{config.horizon_years},
      {config.annual_gallons},{config.s0},{config.mu},{config.sigma},{config.risk_free_rate},
      {calibration['decay']},{calibration['n_returns']},DATE'{calibration['calibration_start']}',
      DATE'{calibration['calibration_end']}',NULL)""")

    def compute_batches(batches):
        for batch in batches:
            # Bound memory independently of Spark's Arrow batch-size setting.
            for start in range(0,len(batch),512):
                ids=batch.path_id.iloc[start:start+512].to_numpy(dtype=np.int64)
                paths=price_paths(ids,config)
                yield pd.DataFrame({'simulation_run_id':run_id,'path_id':ids,
                                    'average_price_gal':paths[:,1:].mean(axis=1),
                                    'terminal_price_gal':paths[:,-1],
                                    'price_path':[p.tolist() for p in paths]})

    schema='simulation_run_id string,path_id long,average_price_gal double,terminal_price_gal double,price_path array<double>'
    output=(spark.range(config.n_paths).selectExpr('id AS path_id').repartition(8)
            .mapInPandas(compute_batches,schema))
    output.write.mode('append').saveAsTable('jet_fuel_silver.simulated_price_paths')
    observed=spark.sql(f"SELECT count(*) AS n,count(DISTINCT path_id) AS unique_n FROM jet_fuel_silver.simulated_price_paths WHERE simulation_run_id='{run_id}'").first()
    if observed.n!=config.n_paths or observed.unique_n!=config.n_paths:
        raise ValueError('Distributed path count/identity mismatch')
    ratios=','.join(str(r)+'D' for r in config.hedge_ratios)
    spark.sql(f"""INSERT INTO jet_fuel_silver.simulation_raw_paths
      SELECT '{run_id}',p.path_id,h.hedge_ratio,
      (h.hedge_ratio*{config.forward_price}+(1-h.hedge_ratio)*p.average_price_gal)
        *{config.annual_gallons}*{config.horizon_years}/1e9
      FROM jet_fuel_silver.simulated_price_paths p
      CROSS JOIN (SELECT explode(array({ratios})) AS hedge_ratio) h
      WHERE p.simulation_run_id='{run_id}'""")

    # INJECT_RISK_SQL
    spark.sql(f"""CREATE OR REPLACE TABLE jet_fuel_gold.risk_metrics USING DELTA AS
      SELECT m.*,r.horizon_years,r.annual_gallons,r.s0,r.mu AS mu_calibrated,
      r.sigma AS sigma_calibrated,r.risk_free_rate,r.seed,r.price_as_of,r.mlflow_run_id,
      r.source_pipeline_run_id,r.calibration_start,r.calibration_end,
      current_timestamp() AS created_ts
      FROM jet_fuel_gold.v_risk_metrics m JOIN jet_fuel_silver.simulation_runs r
      USING(simulation_run_id) WHERE r.status='SUCCESS' OR r.simulation_run_id='{run_id}'""")
    fan_sql=f"""
      SELECT '{run_id}' AS simulation_run_id,step,step/52.0 AS time_years,
      percentile_cont(.05) WITHIN GROUP(ORDER BY price) AS p05_price_gal,
      percentile_cont(.25) WITHIN GROUP(ORDER BY price) AS p25_price_gal,
      percentile_cont(.50) WITHIN GROUP(ORDER BY price) AS p50_price_gal,
      percentile_cont(.75) WITHIN GROUP(ORDER BY price) AS p75_price_gal,
      percentile_cont(.95) WITHIN GROUP(ORDER BY price) AS p95_price_gal
      FROM jet_fuel_silver.simulated_price_paths
      LATERAL VIEW posexplode(price_path) points AS step,price
      WHERE simulation_run_id='{run_id}' GROUP BY step"""
    spark.sql(f'CREATE TABLE IF NOT EXISTS jet_fuel_gold.price_fan USING DELTA AS {fan_sql} LIMIT 0')
    spark.sql(f'INSERT INTO jet_fuel_gold.price_fan {fan_sql}')
    histogram_sql=f"""
      WITH bounds AS (
       SELECT hedge_ratio,min(simulated_total_cost_b) AS lo,max(simulated_total_cost_b) AS hi
       FROM jet_fuel_silver.simulation_raw_paths WHERE simulation_run_id='{run_id}' GROUP BY hedge_ratio
      ), binned AS (
       SELECT p.hedge_ratio,b.lo,b.hi,CASE WHEN b.hi=b.lo THEN 0 ELSE
       least(49,cast(floor(50*(p.simulated_total_cost_b-b.lo)/(b.hi-b.lo)) AS INT)) END AS bin
       FROM jet_fuel_silver.simulation_raw_paths p JOIN bounds b USING(hedge_ratio)
       WHERE p.simulation_run_id='{run_id}'
      ) SELECT '{run_id}' AS simulation_run_id,hedge_ratio,bin,
        lo+(hi-lo)*bin/50.0 AS bin_lower_cost_b,lo+(hi-lo)*(bin+1)/50.0 AS bin_upper_cost_b,
        count(*) AS path_count FROM binned GROUP BY hedge_ratio,bin,lo,hi"""
    spark.sql(f'CREATE TABLE IF NOT EXISTS jet_fuel_gold.cost_histogram USING DELTA AS {histogram_sql} LIMIT 0')
    spark.sql(f'INSERT INTO jet_fuel_gold.cost_histogram {histogram_sql}')
    risk=spark.sql(f"SELECT * FROM jet_fuel_gold.risk_metrics WHERE simulation_run_id='{run_id}' ORDER BY hedge_ratio").toPandas()
    if len(risk)!=len(config.hedge_ratios) or not (risk.n_paths==config.n_paths).all():
        raise ValueError('Risk ratio/count mismatch')
    for row in risk.to_dict('records'):
        label=f"hedge_{round(row['hedge_ratio']*100):03d}"
        mlflow.log_metrics({f'{label}_{metric}':float(row[metric]) for metric in
                           ['mean_cost_b','p95_cost_b','var_95_b','cvar_95_b','var_reduction_pct']
                           if math.isfinite(float(row[metric]))})
    source_now=spark.sql('SELECT * FROM jet_fuel_silver.pipeline_runs ORDER BY started_at DESC LIMIT 1').first()
    if source_now.status!='SUCCESS' or source_now.pipeline_run_id!=source.pipeline_run_id:
        raise ValueError('Silver changed during simulation; rerun against current source')
    duration=time.monotonic()-started
    mlflow.log_metric('duration_seconds',duration)
    mlflow.log_table(risk,'risk_metrics.json')
    quality_sql=f"""
      SELECT '{run_id}' AS simulation_run_id,'{source.pipeline_run_id}' AS source_pipeline_run_id,
      current_timestamp() AS checked_at,{config.n_paths} AS n_paths,{duration} AS duration_seconds,
      (SELECT count(*) FROM jet_fuel_silver.simulation_raw_paths WHERE simulation_run_id='{run_id}') AS cost_rows,
      (SELECT count(*) FROM jet_fuel_gold.price_fan WHERE simulation_run_id='{run_id}') AS fan_steps,
      '{mlflow_id}' AS mlflow_run_id"""
    spark.sql(f'CREATE TABLE IF NOT EXISTS jet_fuel_gold.simulation_quality USING DELTA AS {quality_sql} LIMIT 0')
    spark.sql(f'INSERT INTO jet_fuel_gold.simulation_quality {quality_sql}')
    display(risk)

# Tracking must finish successfully before the registry publishes this run.
source_now=spark.sql('SELECT * FROM jet_fuel_silver.pipeline_runs ORDER BY started_at DESC LIMIT 1').first()
if source_now.status!='SUCCESS' or source_now.pipeline_run_id!=source.pipeline_run_id:
    raise ValueError('Silver changed before simulation publication')
spark.sql(f"""UPDATE jet_fuel_silver.simulation_runs SET status='SUCCESS',
  completed_at=current_timestamp(),duration_seconds={duration} WHERE simulation_run_id='{run_id}'""")
spark.sql('''CREATE OR REPLACE VIEW jet_fuel_gold.latest_simulation_run AS
  SELECT * FROM jet_fuel_silver.simulation_runs WHERE status='SUCCESS'
  QUALIFY row_number() OVER(ORDER BY completed_at DESC,started_at DESC)=1''')
