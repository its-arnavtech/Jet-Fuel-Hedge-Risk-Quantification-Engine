"""Verify current Gold contract and adversarial publication/source states in live SQL."""

import json
from pathlib import Path

from fuel_hedge.config import Settings,load_env
from fuel_hedge.databricks import workspace_client
from fuel_hedge.dashboard import dashboard_definition
from verify_phase1 import query


def main():
    load_env()
    settings=Settings.from_env()
    client=workspace_client(settings)
    # SQL Statement Execution sessions are independent; qualify persistent references.
    for statement in Path('sql/07_reporting_contract.sql').read_text(encoding='utf-8').split(';'):
        if statement.strip():
            for schema in ['jet_fuel_gold','jet_fuel_silver']:
                statement=statement.replace(schema+'.',settings.catalog+'.'+schema+'.')
            query(client,settings.warehouse_id,statement)
    gold=f'{settings.catalog}.jet_fuel_gold'
    ready=query(client,settings.warehouse_id,f'SELECT * FROM {gold}.reporting_readiness')
    if len(ready)!=1 or ready.iloc[0].analytics_ready!='true' or ready.iloc[0].risk_ready!='true':
        raise ValueError('Reporting contract is not ready')
    counts={}
    analytics=query(client,settings.warehouse_id,f'SELECT route_scenario_rows FROM {gold}.analytics_quality').iloc[0]
    simulation=query(client,settings.warehouse_id,f'SELECT horizon_years FROM {gold}.latest_simulation_run').iloc[0]
    for table,expected in [('route_fuel_costs_current',int(analytics.route_scenario_rows)),
                           ('risk_metrics_current',5),
                           ('price_fan_current',round(float(simulation.horizon_years)*52)+1)]:
        counts[table]=int(query(client,settings.warehouse_id,f'SELECT count(*) AS n FROM {gold}.{table}').iloc[0].n)
        if counts[table]!=expected:
            raise ValueError(f'Unexpected current publication count: {table}')
    definition=dashboard_definition(settings.catalog,True)
    datasets={d['name']:len(query(client,settings.warehouse_id,''.join(d['queryLines']))) for d in definition['datasets']}
    original=Path('sql/07_reporting_contract.sql').read_text(encoding='utf-8').split(';')[0].split(' AS\n',1)[1]
    cases=[]
    for status,source_id,analytics_status,cost_rows,expected in [
        ('SUCCESS','S1','SUCCESS',500000,True),('STARTED','S1','SUCCESS',500000,False),
        ('SUCCESS','S2','SUCCESS',500000,False),('SUCCESS','S1','STARTED',500000,False),
        ('SUCCESS','S1','SUCCESS',499999,False),
    ]:
        replacements={
            'jet_fuel_silver.pipeline_runs':f"(SELECT '{source_id}' AS pipeline_run_id,'{status}' AS status,current_timestamp() AS started_at)",
            'jet_fuel_gold.pipeline_runs':f"(SELECT 'G1' AS pipeline_run_id,'{analytics_status}' AS status,current_timestamp() AS started_at)",
            'jet_fuel_silver.ingestion_quality':f"(SELECT '{source_id}' AS pipeline_run_id)",
            'jet_fuel_gold.analytics_quality':"(SELECT 'G1' AS pipeline_run_id,'S1' AS source_pipeline_run_id)",
            'jet_fuel_gold.latest_simulation_run':"(SELECT 'R1' AS simulation_run_id,'S1' AS source_pipeline_run_id,DATE'2026-10-06' AS price_as_of,100000 AS n_paths,1.0 AS horizon_years,current_timestamp() AS completed_at)",
            'jet_fuel_gold.simulation_quality':f"(SELECT 'R1' AS simulation_run_id,{cost_rows} AS cost_rows,53 AS fan_steps)",
        }
        statement=original
        for name,replacement in replacements.items():
            statement=statement.replace(name,replacement)
        result=query(client,settings.warehouse_id,statement).iloc[0]
        if (result.risk_ready=='true')!=expected:
            raise ValueError('Adversarial reporting guard failed')
        cases.append({'source_status':status,'source_id':source_id,'analytics_status':analytics_status,
                      'cost_rows':cost_rows,'risk_ready':result.risk_ready})
    evidence={'passed':True,'readiness':ready.to_dict('records'),'counts':counts,
              'dashboard_rows':datasets,'adversarial_cases':cases}
    Path('artifacts/reporting_verification.json').write_text(json.dumps(evidence,indent=2), encoding='utf-8')
    print(json.dumps(evidence,indent=2))


if __name__=='__main__':
    main()
