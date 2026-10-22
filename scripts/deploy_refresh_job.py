"""Deploy one sequential, bounded serverless refresh job and its project secret."""

import argparse
import base64
import hashlib
import json
from pathlib import Path

from fuel_hedge.config import Settings,load_env
from fuel_hedge.databricks import ensure_project_schemas,workspace_client
from deploy_phase2 import build_source
from deploy_phase5 import build_source as build_insights_source


def main():
    from databricks.sdk.errors import ResourceAlreadyExists
    from databricks.sdk.service import jobs,workspace
    parser=argparse.ArgumentParser()
    parser.add_argument('--enable-schedule',action='store_true')
    parser.add_argument('--run-now',action='store_true')
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    load_env(root/'.env')
    settings=Settings.from_env()
    client=workspace_client(settings)
    ensure_project_schemas(client,settings.catalog)
    if not settings.eia_api_key:
        raise ValueError('Local EIA_API_KEY is required to configure the project secret')
    scope='jet-fuel-hedge-engine'
    try:
        client.secrets.create_scope(scope)
    except ResourceAlreadyExists:
        pass
    client.secrets.put_secret(scope=scope,key='eia-api-key',string_value=settings.eia_api_key)
    folder=f'/Users/{client.current_user.me().user_name}/jet-fuel-hedge-engine'
    sources={name:(root/f'notebooks/{name}.py').read_text(encoding='utf-8') for name in
             ['refresh_capture','phase1_pipeline','refresh_operations','phase3_risk','reporting_contract']}
    sources['refresh_capture']=sources['refresh_capture'].replace('# INJECT_EIA_MODULE',(root/'src/fuel_hedge/eia.py').read_text(encoding='utf-8'))
    sources['refresh_operations']=sources['refresh_operations'].replace('# INJECT_OPERATIONS_MODULE',(root/'src/fuel_hedge/operations.py').read_text(encoding='utf-8'))
    sources['phase2_gold']=build_source(root)
    sources['phase5_insights']=build_insights_source(root,include_reporting=False)
    sources['phase3_risk']=sources['phase3_risk'].replace('# INJECT_SIMULATION_MODULE',(root/'src/fuel_hedge/simulation.py').read_text(encoding='utf-8')).replace('# INJECT_RISK_SQL','spark.sql('+repr((root/'sql/04_risk_metrics.sql').read_text(encoding='utf-8'))+')')
    reporting='\n'.join('spark.sql('+repr(sql.strip())+')' for sql in
        (root/'sql/07_reporting_contract.sql').read_text(encoding='utf-8').split(';') if sql.strip())
    sources['reporting_contract']=sources['reporting_contract'].replace('# INJECT_REPORTING_SQL',reporting)
    tasks=[]
    previous=None
    for name in ['refresh_capture','phase1_pipeline','phase5_insights','refresh_operations','phase2_gold','phase3_risk','reporting_contract']:
        # Versioned job-specific paths cannot silently alter previously deployed jobs.
        digest=hashlib.sha256(sources[name].encode()).hexdigest()
        remote=f'{folder}/refresh/{name}_{digest[:16]}'
        client.workspace.mkdirs(f'{folder}/refresh')
        client.workspace.import_(path=remote,content=base64.b64encode(sources[name].encode()).decode(),
            format=workspace.ImportFormat.SOURCE,language=workspace.Language.PYTHON,overwrite=True)
        params={'catalog':settings.catalog}
        if name=='phase2_gold':
            params['snapshot_id']='{{tasks.refresh_operations.values.snapshot_id}}'
        if name=='phase3_risk':
            params.update(n_paths='100000',seed='20261010',horizon_years='1.0',source_sha256=digest)
        tasks.append(jobs.Task(task_key=name,timeout_seconds=1800,max_retries=0,
            depends_on=[jobs.TaskDependency(task_key=previous)] if previous else None,
            notebook_task=jobs.NotebookTask(notebook_path=remote,source=jobs.Source.WORKSPACE,base_parameters=params)))
        previous=name
    schedule=jobs.CronSchedule(quartz_cron_expression='0 0 18 * * ?',timezone_id='America/Chicago',
                               pause_status=jobs.PauseStatus.UNPAUSED if args.enable_schedule else jobs.PauseStatus.PAUSED)
    config=jobs.JobSettings(name='Jet Fuel Hedge Engine daily medallion refresh',
        description='Managed jet-fuel project. Actual EIA full recapture; synthetic ops; 100K risk. Source controlled, sequential, bounded.',
        tags={'project':'jet-fuel-hedge-engine'},max_concurrent_runs=1,timeout_seconds=7200,
        tasks=tasks,schedule=schedule)
    state_path=root/'artifacts/refresh_job.json'
    state=json.loads(state_path.read_text(encoding='utf-8')) if state_path.exists() else {}
    if state and state['host']!=settings.host:
        raise ValueError('Refresh state belongs to another workspace')
    if state:
        existing=client.jobs.get(state['job_id'])
        if (existing.settings.tags or {}).get('project')!='jet-fuel-hedge-engine':
            raise ValueError('Refusing to update unowned job')
        client.jobs.reset(state['job_id'],config)
        job_id=state['job_id']
    else:
        job_id=client.jobs.create(**config.__dict__).job_id
    state={'host':settings.host,'job_id':job_id,'schedule_enabled':args.enable_schedule,
           'source_hashes':{k:hashlib.sha256(v.encode()).hexdigest() for k,v in sources.items()}}
    state_path.parent.mkdir(exist_ok=True,parents=True)
    state_path.write_text(json.dumps(state,indent=2), encoding='utf-8')
    if args.run_now:
        state['run_id']=client.jobs.run_now(job_id).run_id
        state_path.write_text(json.dumps(state,indent=2), encoding='utf-8')
    print(json.dumps(state,indent=2))


if __name__=='__main__':
    main()
