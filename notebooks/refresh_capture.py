# Databricks notebook source
# MAGIC %md
# MAGIC # Bounded actual EIA refresh
# MAGIC Full daily recapture preserves older revisions; publishes only a complete capture.
# MAGIC The EIA credential is read from the project scope and removed from echoed responses.

# COMMAND ----------
from datetime import date,timedelta
import hashlib
import json
import os
from pathlib import Path
import re
from uuid import uuid4

dbutils.widgets.text('catalog','workspace')
catalog=dbutils.widgets.get('catalog')
if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',catalog):
    raise ValueError('Invalid catalog')
marker='Jet Fuel Hedge Risk Quantification Engine managed schema v1'
if not any(r[1]==marker for r in spark.sql(f'DESCRIBE SCHEMA EXTENDED `{catalog}`.jet_fuel_bronze').collect()):
    raise ValueError('Unowned project schema')

# INJECT_EIA_MODULE

# COMMAND ----------
key=dbutils.secrets.get(scope='jet-fuel-hedge-engine',key='eia-api-key')
start,end='2010-01-01',(date.today()-timedelta(days=1)).isoformat()
pages=list(EIAClient(key).pages(start,end))
del key
if not pages:
    raise ValueError('Empty source capture')
capture_id=str(uuid4())
envelopes=[]
for page in pages:
    payload=json.dumps(page.pop('payload'),sort_keys=True,separators=(',',':'),allow_nan=False)
    envelopes.append({**page,'capture_id':capture_id,'event_id':str(uuid4()),
                      'payload_sha256':hashlib.sha256(payload.encode()).hexdigest(),
                      'payload_json':payload})
volume=Path(f'/Volumes/{catalog}/jet_fuel_bronze/landing')
staging=volume/'capture_staging'
staging.mkdir(exist_ok=True)
target=volume/'captures'/f'{capture_id}.jsonl'
temporary=staging/f'{capture_id}.pending'
with temporary.open('x',encoding='utf-8') as stream:
    stream.write('\n'.join(json.dumps(e,sort_keys=True,separators=(',',':')) for e in envelopes)+'\n')
# Keep incomplete files outside the stream source; same-volume rename publishes all bytes.
os.replace(temporary,target)
print(json.dumps({'capture_id':capture_id,'pages':len(envelopes),'start':start,'end':end}))
