"""Compare live distributed paths, exact SQL tails, calibration and MLflow to NumPy."""

import json
from pathlib import Path

import numpy as np
import pandas as pd

from fuel_hedge.config import Settings, load_env
from fuel_hedge.databricks import workspace_client
from fuel_hedge.simulation import SimulationConfig,calibrate,cost_distribution,price_paths,risk_summary
from verify_phase1 import query


def main():
    load_env()
    settings=Settings.from_env()
    client=workspace_client(settings)
    gold=f'{settings.catalog}.jet_fuel_gold'
    silver=f'{settings.catalog}.jet_fuel_silver'
    run=query(client,settings.warehouse_id,f'SELECT * FROM {gold}.latest_simulation_run').iloc[0]
    quality=query(client,settings.warehouse_id,f"SELECT * FROM {gold}.simulation_quality WHERE simulation_run_id='{run.simulation_run_id}'").iloc[0]
    source=query(client,settings.warehouse_id,f'SELECT * FROM {silver}.pipeline_runs ORDER BY started_at DESC LIMIT 1').iloc[0]
    if (run.status!='SUCCESS' or quality.simulation_run_id!=run.simulation_run_id
            or source.status!='SUCCESS' or run.source_pipeline_run_id!=source.pipeline_run_id):
        raise ValueError('Simulation publication/source watermark is not ready')
    calibration=calibrate(pd.read_csv('artifacts/silver/weekly_fuel_prices.csv'))
    np.testing.assert_allclose([float(run.mu),float(run.sigma)],
                               [calibration['mu'],calibration['sigma']],rtol=1e-12,atol=1e-12)
    config=SimulationConfig(s0=float(run.s0),mu=float(run.mu),sigma=float(run.sigma),
                            n_paths=int(run.n_paths),seed=int(run.seed),
                            horizon_years=float(run.horizon_years),annual_gallons=float(run.annual_gallons),
                            risk_free_rate=float(run.risk_free_rate))
    paths=price_paths(np.arange(config.n_paths),config)
    costs=cost_distribution(paths,config)
    expected=risk_summary(costs).sort_values('hedge_ratio').reset_index(drop=True)
    observed=query(client,settings.warehouse_id,
                   f"SELECT * FROM {gold}.risk_metrics WHERE simulation_run_id='{run.simulation_run_id}' ORDER BY hedge_ratio")
    for column in ['hedge_ratio','n_paths','mean_cost_b','p50_cost_b','p95_cost_b','var_95_b','cvar_95_b','var_reduction_pct']:
        np.testing.assert_allclose(pd.to_numeric(observed[column]),expected[column],rtol=1e-9,atol=1e-10)
    np.testing.assert_allclose(pd.to_numeric(observed.var_reduction_pct),100*np.array(config.hedge_ratios),atol=1e-7)
    samples=query(client,settings.warehouse_id,f"""SELECT path_id,price_path FROM {silver}.simulated_price_paths
       WHERE simulation_run_id='{run.simulation_run_id}' AND path_id IN (0,1,17,999,{config.n_paths-1}) ORDER BY path_id""")
    for row in samples.to_dict('records'):
        np.testing.assert_allclose(np.array(json.loads(row['price_path']),dtype=float),paths[int(row['path_id'])],rtol=1e-12,atol=1e-12)
    fan=query(client,settings.warehouse_id,f"SELECT * FROM {gold}.price_fan WHERE simulation_run_id='{run.simulation_run_id}' ORDER BY step")
    for q,column in [(.05,'p05_price_gal'),(.25,'p25_price_gal'),(.5,'p50_price_gal'),(.75,'p75_price_gal'),(.95,'p95_price_gal')]:
        np.testing.assert_allclose(pd.to_numeric(fan[column]),np.quantile(paths,q,axis=0),rtol=1e-9,atol=1e-10)
    hist=query(client,settings.warehouse_id,f"SELECT hedge_ratio,sum(path_count) AS n FROM {gold}.cost_histogram WHERE simulation_run_id='{run.simulation_run_id}' GROUP BY hedge_ratio ORDER BY hedge_ratio")
    if len(hist)!=5 or not pd.to_numeric(hist.n).eq(config.n_paths).all():
        raise ValueError('Histogram paths do not reconcile')
    if int(quality.cost_rows)!=config.n_paths*len(config.hedge_ratios):
        raise ValueError('Raw distribution row count mismatch')
    mlflow_run=client.experiments.get_run(run.mlflow_run_id).run
    if getattr(mlflow_run.info.status,'value',mlflow_run.info.status)!='FINISHED':
        raise ValueError('MLflow run is not finished')
    evidence={'passed':True,'simulation_run_id':run.simulation_run_id,'n_paths':config.n_paths,
              'cost_rows':int(quality.cost_rows),'fan_steps':len(fan),
              'sample_paths_checked':len(samples),'duration_seconds':float(run.duration_seconds),
              'mlflow_run_id':run.mlflow_run_id,'source_pipeline_run_id':run.source_pipeline_run_id,
              'calibration':calibration,'metrics':expected.to_dict('records')}
    Path('artifacts/phase3_verification.json').write_text(json.dumps(evidence,indent=2))
    expected.to_csv('artifacts/risk_metrics.csv',index=False)
    fan.to_csv('artifacts/price_fan.csv',index=False)
    hist.to_csv('artifacts/histogram_counts.csv',index=False)
    print(json.dumps(evidence,indent=2))


if __name__=='__main__':
    main()
