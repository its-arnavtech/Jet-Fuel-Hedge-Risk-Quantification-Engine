"""Submit the full distributed run with versioned, dependency-light simulation source."""

import argparse
import base64
import json
from pathlib import Path

from fuel_hedge.config import Settings, load_env
from fuel_hedge.databricks import ensure_project_schemas, workspace_client


def main():
    from databricks.sdk.service import jobs,workspace
    parser=argparse.ArgumentParser()
    parser.add_argument('--n-paths',type=int,default=100_000)
    parser.add_argument('--horizon-years',type=float,default=1.0)
    parser.add_argument('--seed',type=int,default=20261010)
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    load_env(root/'.env')
    settings=Settings.from_env()
    client=workspace_client(settings)
    ensure_project_schemas(client,settings.catalog)
    source=(root/'notebooks/phase3_risk.py').read_text()
    source=source.replace('# INJECT_SIMULATION_MODULE',(root/'src/fuel_hedge/simulation.py').read_text())
    source=source.replace('# INJECT_RISK_SQL','spark.sql('+repr((root/'sql/04_risk_metrics.sql').read_text())+')')
    remote=f'/Users/{client.current_user.me().user_name}/jet-fuel-hedge-engine/phase3_risk'
    client.workspace.import_(path=remote,content=base64.b64encode(source.encode()).decode(),
                             format=workspace.ImportFormat.SOURCE,language=workspace.Language.PYTHON,
                             overwrite=True)
    run=client.jobs.submit(run_name='jet-fuel-phase3-gbm-risk',timeout_seconds=5400,
        tasks=[jobs.SubmitTask(task_key='gbm_risk',timeout_seconds=5400,
           notebook_task=jobs.NotebookTask(notebook_path=remote,source=jobs.Source.WORKSPACE,
             base_parameters={'catalog':settings.catalog,'n_paths':str(args.n_paths),
                              'seed':str(args.seed),'horizon_years':str(args.horizon_years)}))])
    print(json.dumps({'run_id':run.run_id,'n_paths':args.n_paths,'seed':args.seed},indent=2))


if __name__=='__main__':
    main()
