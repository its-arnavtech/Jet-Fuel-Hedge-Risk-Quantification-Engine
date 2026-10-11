"""Create/update the project's own dashboard; never duplicate an existing deployment ID."""

import argparse
import json
from pathlib import Path

from fuel_hedge.config import Settings, load_env
from fuel_hedge.dashboard import dashboard_definition
from fuel_hedge.databricks import workspace_client


def main():
    from databricks.sdk.service.dashboards import Dashboard
    parser=argparse.ArgumentParser()
    parser.add_argument('--include-risk',action='store_true')
    parser.add_argument('--dashboard-id')
    args=parser.parse_args()
    load_env()
    settings=Settings.from_env()
    client=workspace_client(settings)
    definition=dashboard_definition(settings.catalog,args.include_risk)
    output=Path('dashboard/jet_fuel_analytics.lvdash.json')
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(definition,indent=2), encoding='utf-8')
    state_path=Path('artifacts/dashboard.json')
    state=json.loads(state_path.read_text(encoding='utf-8')) if state_path.exists() else {}
    dashboard_id=args.dashboard_id or state.get('dashboard_id')
    if state.get('host') not in {None,settings.host}:
        raise ValueError('Dashboard state belongs to another workspace')
    dashboard=Dashboard(display_name='Jet Fuel Hedge Analytics',serialized_dashboard=json.dumps(definition),
                        warehouse_id=settings.warehouse_id)
    if dashboard_id:
        result=client.lakeview.update(dashboard_id,dashboard)
    else:
        dashboard.parent_path=f'/Users/{client.current_user.me().user_name}/jet-fuel-hedge-engine'
        result=client.lakeview.create(dashboard)
    state={'host':settings.host,'dashboard_id':result.dashboard_id,
           'url':f'{settings.host}/dashboardsv3/{result.dashboard_id}'}
    state_path.parent.mkdir(parents=True,exist_ok=True)
    state_path.write_text(json.dumps(state,indent=2), encoding='utf-8')
    # Run as viewer; don't embed the author's credentials into the published dashboard.
    client.lakeview.publish(result.dashboard_id,embed_credentials=False,warehouse_id=settings.warehouse_id)
    print(json.dumps(state,indent=2))


if __name__=='__main__':
    main()
