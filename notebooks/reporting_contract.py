# Databricks notebook source
# MAGIC %md
# MAGIC # Guarded reporting contract
# MAGIC Publish views only after the medallion and simulation tasks succeed.

# COMMAND ----------
import re
dbutils.widgets.text('catalog','workspace')
catalog=dbutils.widgets.get('catalog')
if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',catalog):
    raise ValueError('Invalid catalog')
spark.sql(f'USE CATALOG `{catalog}`')
for schema in ['jet_fuel_silver','jet_fuel_gold']:
    if not any(r[1]=='Jet Fuel Hedge Risk Quantification Engine managed schema v1'
               for r in spark.sql(f'DESCRIBE SCHEMA EXTENDED `{schema}`').collect()):
        raise ValueError('Unowned project schema')
# INJECT_REPORTING_SQL
readiness=spark.table('jet_fuel_gold.reporting_readiness').first()
if not readiness.analytics_ready or not readiness.risk_ready:
    raise ValueError('Reporting lineage or quality is not ready')
display(spark.table('jet_fuel_gold.reporting_readiness'))
