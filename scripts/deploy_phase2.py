"""Generate deterministic operations, stage immutable inputs, and submit Gold notebook."""

import base64
from datetime import date
import hashlib
from pathlib import Path
import json

import pandas as pd

from fuel_hedge.config import Settings, load_env
from fuel_hedge.databricks import ensure_project_schemas, upload_immutable, workspace_client
from fuel_hedge.operations import synthetic_operations


def build_source(root):
    source = (root / 'notebooks/phase2_gold.py').read_text(encoding='utf-8')
    for sql in sorted((root / 'sql').glob('0[1-6]_*.sql')):
        source += '\n# COMMAND ----------\nspark.sql(' + repr(sql.read_text(encoding='utf-8')) + ')\n'
    source += '''
# COMMAND ----------
spark.sql(f"""CREATE OR REPLACE TABLE jet_fuel_gold.analytics_quality USING DELTA AS
SELECT '{gold_run_id}' AS pipeline_run_id,'{source_pipeline_run_id}' AS source_pipeline_run_id,
 current_timestamp() AS checked_at,
 (SELECT count(*) FROM jet_fuel_silver.routes) AS routes,
 (SELECT count(*) FROM jet_fuel_silver.flights) AS scheduled_flights,
 (SELECT count(*) FROM jet_fuel_silver.flights WHERE NOT cancelled) AS operated_flights,
 (SELECT count(*) FROM jet_fuel_gold.route_fuel_costs) AS route_scenario_rows,
 (SELECT sum(monthly_gallons) FROM jet_fuel_gold.route_fuel_costs WHERE hedge_ratio=0) AS operated_gallons,
 (SELECT sum(monthly_flights) FROM jet_fuel_gold.route_fuel_costs WHERE hedge_ratio=0) AS gold_operated_flights,
 (SELECT count(*) FROM jet_fuel_gold.v_hedge_sensitivity) AS sensitivity_rows,
 (SELECT max(price_date) FROM jet_fuel_silver.fuel_prices) AS latest_price_date,
 true AS operations_are_synthetic""")
q=spark.table('jet_fuel_gold.analytics_quality').first()
if q.operated_flights != q.gold_operated_flights or q.sensitivity_rows != 30:
    raise ValueError('Gold consumption/scenario reconciliation failed')
source_latest=spark.sql('SELECT * FROM jet_fuel_silver.pipeline_runs ORDER BY started_at DESC LIMIT 1').first()
source_quality=spark.table('jet_fuel_silver.ingestion_quality').first()
if (source_latest.status!='SUCCESS' or source_latest.pipeline_run_id!=source_pipeline_run_id
        or source_quality.pipeline_run_id!=source_pipeline_run_id):
    raise ValueError('Silver source changed during Gold publication; rerun Gold')
spark.sql(f"UPDATE jet_fuel_gold.pipeline_runs SET status='SUCCESS',completed_at=current_timestamp() WHERE pipeline_run_id='{gold_run_id}'")
display(spark.table('jet_fuel_gold.analytics_quality'))
'''
    return source


def main():
    from databricks.sdk.service import jobs, workspace
    root = Path(__file__).resolve().parents[1]
    load_env(root / '.env')
    settings = Settings.from_env()
    client = workspace_client(settings)
    ensure_project_schemas(client, settings.catalog)
    as_of = date.fromisoformat(pd.read_csv(root / 'artifacts/silver/fuel_prices.csv').price_date.max())
    data = synthetic_operations(as_of)
    encoded = {name: (frame.to_json(orient='records', lines=True) + '\n').encode()
               for name, frame in data.items()}
    snapshot = hashlib.sha256(b''.join(encoded[name] for name in sorted(encoded))).hexdigest()
    folder = f'/Volumes/{settings.catalog}/jet_fuel_bronze/landing/operations/{snapshot}'
    client.files.create_directory(folder)
    for name, content in encoded.items():
        upload_immutable(client, f'{folder}/{name}.jsonl', content)
    source = build_source(root)
    remote = f'/Users/{client.current_user.me().user_name}/jet-fuel-hedge-engine/phase2_gold'
    client.workspace.import_(path=remote, content=base64.b64encode(source.encode()).decode(),
                             format=workspace.ImportFormat.SOURCE, language=workspace.Language.PYTHON,
                             overwrite=True)
    run = client.jobs.submit(run_name='jet-fuel-phase2-gold',timeout_seconds=3600,
                            tasks=[jobs.SubmitTask(task_key='gold_analytics',timeout_seconds=3600,
                                   notebook_task=jobs.NotebookTask(notebook_path=remote,
                                       source=jobs.Source.WORKSPACE,
                                       base_parameters={'catalog':settings.catalog,'snapshot_id':snapshot}))])
    print(json.dumps({'run_id':run.run_id,'snapshot_id':snapshot,
                      'as_of':str(as_of),'scheduled_flights':len(data['flights'])},indent=2))


if __name__ == '__main__':
    main()
