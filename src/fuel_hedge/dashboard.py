"""AI/BI dashboard definition using Databricks Lakeview's documented widget schema."""

from .config import identifier


def dashboard_definition(catalog: str, include_risk: bool = False) -> dict:
    catalog = identifier(catalog)
    gold = f'{catalog}.jet_fuel_gold'
    datasets, layout = [], [{
        'widget': {'name':'context', 'multilineTextboxSpec': {'lines':[
            '# Jet Fuel Hedge Analytics\n\n',
            'Actual EIA Gulf Coast prices; synthetic flight operations and hedge positions. '
            'Route costs are historical counterfactual hedge scenarios. '
            'Reference-carrier risk uses 1.5 billion gallons/year.\n',
        ]}}, 'position':{'x':0,'y':0,'width':12,'height':2},
    }]

    def widget(name, title, sql, fields, kind, x, y, width=6, encodings=None):
        datasets.append({'name':name,'displayName':title,'queryLines':[sql+'\n']})
        if kind=='table':
            spec={'version':2,'widgetType':'table',
                  'encodings':{'columns':[{'fieldName':f,'displayName':f.replace('_',' ')} for f in fields]}}
        else:
            spec={'version':3,'widgetType':kind,'encodings':encodings}
        spec['frame']={'showTitle':True,'title':title}
        layout.append({'widget':{'name':name+'_widget','queries':[{
            'name':'main_query','query':{'datasetName':name,'disaggregated':True,
             'fields':[{'name':f,'expression':f'`{f}`'} for f in fields]},
        }],'spec':spec},'position':{'x':x,'y':y,'width':width,'height':5}})

    widget('price_trend','EIA jet fuel price USD per gallon',
           f'SELECT price_date,jet_fuel_gal FROM {gold}.v_price_correlation WHERE price_date>=date_add((SELECT max(price_date) FROM {gold}.v_price_correlation),-365) ORDER BY price_date',
           ['price_date','jet_fuel_gal'],'line',0,2,encodings={
               'x':{'fieldName':'price_date','scale':{'type':'temporal'}},
               'y':{'fieldName':'jet_fuel_gal','scale':{'type':'quantitative'},'axis':{'title':'USD / gallon'}},
           })
    widget('route_cost','Unhedged cost by synthetic route USD',
           f'SELECT route_id,sum(monthly_fuel_cost_usd) AS fuel_cost_usd FROM {gold}.v_route_burn GROUP BY route_id ORDER BY fuel_cost_usd DESC',
           ['route_id','fuel_cost_usd'],'bar',6,2,encodings={
               'x':{'fieldName':'route_id','scale':{'type':'categorical'}},
               'y':{'fieldName':'fuel_cost_usd','scale':{'type':'quantitative'},'axis':{'title':'USD'}},
           })
    widget('hedge_marks','Synthetic hedge marks using matching underlying prices',
           f'SELECT position_id,underlying,current_spot_gal,unrealized_pnl_usd,hedge_status,as_of_date FROM {gold}.v_hedge_mtm',
           ['position_id','underlying','current_spot_gal','unrealized_pnl_usd','hedge_status','as_of_date'],
           'table',0,7,width=12)
    if include_risk:
        latest=f'(SELECT simulation_run_id FROM {gold}.latest_simulation_run)'
        widget('risk_metrics','Reference carrier risk USD billions',
               f'SELECT hedge_ratio,mean_cost_b,p95_cost_b,var_95_b,cvar_95_b,var_reduction_pct FROM {gold}.risk_metrics WHERE simulation_run_id=(SELECT simulation_run_id FROM {gold}.latest_simulation_run)',
               ['hedge_ratio','mean_cost_b','p95_cost_b','var_95_b','cvar_95_b','var_reduction_pct'],'table',0,12,width=12)
        widget('price_fan','GBM price fan: 5 / 25 / 50 / 75 / 95 percentiles',
               f'SELECT time_years,p05_price_gal,p25_price_gal,p50_price_gal,p75_price_gal,p95_price_gal FROM {gold}.price_fan WHERE simulation_run_id={latest} ORDER BY step',
               ['time_years','p05_price_gal','p25_price_gal','p50_price_gal','p75_price_gal','p95_price_gal'],
               'line',0,17,encodings={
                   'x':{'fieldName':'time_years','scale':{'type':'quantitative'},'axis':{'title':'Years'}},
                   'y':{'fields':[{'fieldName':f'p{p:02}_price_gal','displayName':f'P{p:02}'} for p in [5,25,50,75,95]],
                        'scale':{'type':'quantitative'},'axis':{'title':'USD / gallon'}},
               })
        widget('cost_histogram','Unhedged cost histogram (latest successful run)',
               f'SELECT (bin_lower_cost_b+bin_upper_cost_b)/2 AS cost_b,path_count FROM {gold}.cost_histogram WHERE simulation_run_id={latest} AND hedge_ratio=0 ORDER BY bin',
               ['cost_b','path_count'],'bar',6,17,encodings={
                   'x':{'fieldName':'cost_b','scale':{'type':'quantitative'},'axis':{'title':'USD billions'}},
                   'y':{'fieldName':'path_count','scale':{'type':'quantitative'}},
               })
        widget('hedge_effectiveness','Incremental VaR reduction by hedge ratio',
               f'SELECT hedge_ratio,var_reduction_pct FROM {gold}.risk_metrics WHERE simulation_run_id={latest} ORDER BY hedge_ratio',
               ['hedge_ratio','var_reduction_pct'],'bar',0,22,encodings={
                   'x':{'fieldName':'hedge_ratio','scale':{'type':'categorical'}},
                   'y':{'fieldName':'var_reduction_pct','scale':{'type':'quantitative'},'axis':{'title':'Reduction %'}},
               })
        widget('sensitivity','Reference carrier cost under spot-price shocks',
               f'SELECT hedge_ratio,price_change_pct,hedged_cost_b FROM {gold}.v_hedge_sensitivity ORDER BY hedge_ratio,price_change_pct',
               ['hedge_ratio','price_change_pct','hedged_cost_b'],'heatmap',6,22,encodings={
                   'x':{'fieldName':'price_change_pct','scale':{'type':'categorical'}},
                   'y':{'fieldName':'hedge_ratio','scale':{'type':'categorical'}},
                   'color':{'fieldName':'hedged_cost_b','scale':{'type':'quantitative','colorRamp':{'mode':'scheme','scheme':'viridis'}}},
               })
    return {'datasets':datasets,'pages':[{'name':'overview','displayName':'Treasury overview',
                                          'pageType':'PAGE_TYPE_CANVAS','layout':layout}]}
