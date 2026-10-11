# Databricks notebook source
# MAGIC %md
# MAGIC # Synthetic operations snapshot for current Silver price date
# MAGIC Synthetic BTS-style fixtures; immutable content-addressed volume files.

# COMMAND ----------
import hashlib
from pathlib import Path
import re

dbutils.widgets.text('catalog','workspace')
catalog=dbutils.widgets.get('catalog')
if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',catalog):
    raise ValueError('Invalid catalog')
spark.sql(f'USE CATALOG `{catalog}`')
if not any(r[1]=='Jet Fuel Hedge Risk Quantification Engine managed schema v1'
           for r in spark.sql('DESCRIBE SCHEMA EXTENDED jet_fuel_bronze').collect()):
    raise ValueError('Unowned project schema')

# INJECT_OPERATIONS_MODULE

# COMMAND ----------
as_of=spark.sql('SELECT max(price_date) AS as_of FROM jet_fuel_silver.fuel_prices').first().as_of
fixtures=synthetic_operations(as_of)
encoded={name:(frame.to_json(orient='records',lines=True)+'\n').encode() for name,frame in fixtures.items()}
snapshot=hashlib.sha256(b''.join(encoded[name] for name in sorted(encoded))).hexdigest()
folder=Path(f'/Volumes/{catalog}/jet_fuel_bronze/landing/operations/{snapshot}')
folder.mkdir(parents=True,exist_ok=True)
for name,content in encoded.items():
    path=folder/f'{name}.jsonl'
    if path.exists():
        if path.read_bytes()!=content:
            raise ValueError('Immutable synthetic snapshot conflict')
    else:
        with path.open('xb') as stream:
            stream.write(content)
dbutils.jobs.taskValues.set(key='snapshot_id',value=snapshot)
print({'as_of':str(as_of),'snapshot_id':snapshot})
