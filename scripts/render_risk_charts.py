"""Export publication charts only from independently verified live risk results."""

import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from fuel_hedge.config import Settings, load_env
from fuel_hedge.databricks import workspace_client
from verify_phase1 import query


def main():
    evidence=json.loads(Path('artifacts/phase3_verification.json').read_text())
    if not evidence['passed']:
        raise ValueError('Independent live reconciliation is required')
    load_env()
    settings=Settings.from_env()
    client=workspace_client(settings)
    gold=f'{settings.catalog}.jet_fuel_gold'
    run_id=evidence['simulation_run_id']
    fan=pd.read_csv('artifacts/price_fan.csv')
    risk=pd.read_csv('artifacts/risk_metrics.csv')
    hist=query(client,settings.warehouse_id,f"SELECT * FROM {gold}.cost_histogram WHERE simulation_run_id='{run_id}' ORDER BY hedge_ratio,bin")
    sensitivity=query(client,settings.warehouse_id,f'SELECT * FROM {gold}.v_hedge_sensitivity')
    output=Path('dashboard/plots')
    output.mkdir(parents=True,exist_ok=True)
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.spines.top':False,
                         'axes.spines.right':False,'axes.titleweight':'bold'})
    fig,axes=plt.subplots(2,2,figsize=(13,9),layout='constrained')
    ax=axes[0,0]
    ax.fill_between(fan.time_years,fan.p05_price_gal,fan.p95_price_gal,color='#ccdfee',label='P05–P95')
    ax.fill_between(fan.time_years,fan.p25_price_gal,fan.p75_price_gal,color='#78a9cb',label='P25–P75')
    ax.plot(fan.time_years,fan.p50_price_gal,color='#174a6e',label='Median')
    ax.set(title='Calibrated GBM price fan',xlabel='Years',ylabel='Jet fuel USD / gallon')
    ax.legend(frameon=False)
    ax=axes[0,1]
    for ratio,color in [(0.,'#c66c39'),(.8,'#174a6e')]:
        data=hist[pd.to_numeric(hist.hedge_ratio).eq(ratio)]
        lo=pd.to_numeric(data.bin_lower_cost_b).to_numpy()
        hi=pd.to_numeric(data.bin_upper_cost_b).to_numpy()
        ax.bar((lo+hi)/2,pd.to_numeric(data.path_count),width=(hi-lo),alpha=.6,
               label=f'{ratio:.0%} hedge',color=color)
    ax.set(title='Annual fuel cost distribution',xlabel='USD billions',ylabel='Paths per bin')
    ax.legend(frameon=False)
    ax=axes[1,0]
    ax.plot(risk.hedge_ratio*100,risk.var_95_b,marker='o',color='#174a6e',label='Incremental VaR95')
    ax.plot(risk.hedge_ratio*100,risk.cvar_95_b,marker='s',color='#c66c39',label='Absolute CVaR95')
    ax.set(title='Tail risk and hedge coverage',xlabel='Hedged consumption (%)',ylabel='USD billions')
    ax.legend(frameon=False)
    ax=axes[1,1]
    for c in ['hedge_ratio','price_change_pct','hedged_cost_b']:
        sensitivity[c]=pd.to_numeric(sensitivity[c])
    matrix=sensitivity.pivot(index='hedge_ratio',columns='price_change_pct',values='hedged_cost_b').sort_index()
    im=ax.imshow(matrix,aspect='auto',cmap='viridis')
    ax.set_xticks(np.arange(len(matrix.columns)),[f'{p:+.0f}%' for p in matrix.columns])
    ax.set_yticks(np.arange(len(matrix.index)),[f'{p:.0%}' for p in matrix.index])
    for y in range(len(matrix.index)):
        for x in range(len(matrix.columns)):
            ax.text(x,y,f'{matrix.iloc[y,x]:.2f}',ha='center',va='center',color='white',fontsize=9)
    ax.set(title='Reference carrier sensitivity',xlabel='Spot price shock',ylabel='Hedge coverage')
    fig.colorbar(im,ax=ax,label='Cost USD billions',shrink=.75)
    fig.suptitle(f"Jet Fuel Hedge Risk | {evidence['n_paths']:,} paths | seed 20261010\n"
                 'Actual EIA calibration; 1.5B gallon reference carrier; simplified financing forward',fontsize=14)
    fig.savefig(output/'risk_overview.png',dpi=160)
    plt.close(fig)
    (output/'provenance.json').write_text(json.dumps(evidence,indent=2))
    print(str(output/'risk_overview.png'))


if __name__=='__main__':
    main()
