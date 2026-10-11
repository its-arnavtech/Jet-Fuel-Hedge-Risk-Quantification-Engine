"""Reconcile live Gold costs/marks with independent local operations calculations."""

import argparse
from datetime import date
import json
from pathlib import Path

import numpy as np
import pandas as pd

from fuel_hedge.config import Settings, load_env
from fuel_hedge.databricks import workspace_client
from fuel_hedge.operations import HEDGE_RATIOS, linear_hedge_mark, synthetic_operations
from verify_phase1 import query


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--expect-no-risk', action='store_true')
    args = parser.parse_args()
    load_env()
    settings = Settings.from_env()
    client = workspace_client(settings)
    gold = f'{settings.catalog}.jet_fuel_gold'
    quality = query(client,settings.warehouse_id,f'SELECT * FROM {gold}.analytics_quality')
    run = query(client,settings.warehouse_id,
                f'SELECT * FROM {gold}.pipeline_runs ORDER BY started_at DESC LIMIT 1')
    if run.iloc[0].status!='SUCCESS' or run.iloc[0].pipeline_run_id!=quality.iloc[0].pipeline_run_id:
        raise ValueError('Gold publication is not ready')
    prices = pd.read_csv('artifacts/silver/fuel_prices.csv',parse_dates=['price_date'])
    data = synthetic_operations(date.fromisoformat(str(prices.price_date.max().date())))
    flights = data['flights'].loc[lambda f: ~f.cancelled].copy()
    flights['flight_date'] = pd.to_datetime(flights.flight_date)
    enriched = flights.merge(data['routes'][['route_id','avg_fuel_burn_gal']],on='route_id')
    enriched = pd.merge_asof(enriched.sort_values('flight_date'),prices.sort_values('price_date'),
                             left_on='flight_date',right_on='price_date')
    enriched['cost_month'] = enriched.flight_date.dt.to_period('M').dt.to_timestamp()
    enriched['spot_cost'] = enriched.avg_fuel_burn_gal*enriched.jet_fuel_gal
    monthly = enriched.groupby(['route_id','cost_month']).agg(
        monthly_flights=('flight_id','size'),monthly_gallons=('avg_fuel_burn_gal','sum'),
        unhedged_cost_usd=('spot_cost','sum')).reset_index()
    locked = enriched.loc[enriched.flight_date==enriched.flight_date.min(),'jet_fuel_gal'].iloc[0]*np.exp(.04)
    expected = monthly.merge(pd.DataFrame({'hedge_ratio':HEDGE_RATIOS}),how='cross')
    expected['hedged_cost_usd'] = expected.hedge_ratio*locked*expected.monthly_gallons+(1-expected.hedge_ratio)*expected.unhedged_cost_usd
    expected['hedge_pnl_usd'] = expected.hedged_cost_usd-expected.unhedged_cost_usd
    cloud = query(client,settings.warehouse_id,f'SELECT * FROM {gold}.route_fuel_costs')
    cloud['cost_month'] = pd.to_datetime(cloud.cost_month)
    cloud['hedge_ratio'] = pd.to_numeric(cloud.hedge_ratio)
    keys = ['route_id','cost_month','hedge_ratio']
    cloud,expected = cloud.sort_values(keys).reset_index(drop=True),expected.sort_values(keys).reset_index(drop=True)
    pd.testing.assert_frame_equal(cloud[keys],expected[keys],check_dtype=False)
    for column in ['monthly_flights','monthly_gallons','unhedged_cost_usd','hedged_cost_usd','hedge_pnl_usd']:
        np.testing.assert_allclose(pd.to_numeric(cloud[column]),expected[column],rtol=1e-10,atol=1e-5)
    if not cloud.cost_id.is_unique or not cloud.is_synthetic.eq('true').all():
        raise ValueError('Invalid Gold grain or synthetic flag')
    mtm = query(client,settings.warehouse_id,f'SELECT * FROM {gold}.v_hedge_mtm')
    spots = prices.iloc[-1].to_dict()
    for position in data['hedge_positions'].to_dict('records'):
        mark = linear_hedge_mark(position['instrument_type'],position['underlying'],
                                 position['contract_gallons'],position['locked_price_gal'],spots)
        actual = float(mtm.loc[mtm.position_id==position['position_id'],'unrealized_pnl_usd'].iloc[0])
        np.testing.assert_allclose(actual,mark)
    fleet = query(client,settings.warehouse_id,f'SELECT * FROM {gold}.v_fleet_summary')
    np.testing.assert_allclose(pd.to_numeric(fleet.fleet_share_pct).sum(),100)
    sensitivity = query(client,settings.warehouse_id,f'SELECT * FROM {gold}.v_hedge_sensitivity')
    if len(sensitivity)!=30:
        raise ValueError('Incomplete sensitivity grid')
    # No simulation has been run: the sixth query exists but must not fabricate risk rows.
    risk = query(client,settings.warehouse_id,f'SELECT * FROM {gold}.v_risk_metrics')
    if args.expect_no_risk and len(risk):
        raise ValueError('Unexpected simulation results before Phase 3')
    evidence = {'passed':True,'route_scenario_rows_reconciled':len(cloud),
                'hedge_marks_reconciled':len(mtm),'sensitivity_rows':len(sensitivity),
                'risk_rows_observed':len(risk),'quality':quality.to_dict('records')[0]}
    Path('artifacts/phase2_verification.json').write_text(json.dumps(evidence,indent=2))
    print(json.dumps(evidence,indent=2))


if __name__=='__main__':
    main()
