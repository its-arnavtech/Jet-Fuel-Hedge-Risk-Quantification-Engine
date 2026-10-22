"""Reproducible PBIP/TMDL/PBIR authoring; Import only, credential-free M.

All narrative numbers come from DAX measures over guarded current facts.
Run verify_powerbi_contract.py after generation; Desktop is a separate validation.
"""

import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT/"powerbi/JetFuelHedgeRisk"
REPORT = PROJECT/"JetFuelHedgeRisk.Report"
MODEL = PROJECT/"JetFuelHedgeRisk.SemanticModel"
BASE = "https://developer.microsoft.com/json-schemas/fabric/"
SCHEMAS = {
    "pbip": BASE+"pbip/pbipProperties/1.0.0/schema.json",
    "pbir": BASE+"item/report/definitionProperties/2.0.0/schema.json",
    "pbism": BASE+"item/semanticModel/definitionProperties/1.0.0/schema.json",
    **{n: BASE+f"item/report/definition/{kind}/{v}/schema.json" for n, kind, v in [
        ("report", "report", "3.3.0"), ("page", "page", "2.1.0"),
        ("visual", "visualContainer", "2.7.0"), ("pages", "pagesMetadata", "1.0.0"),
        ("version", "versionMetadata", "1.0.0")]},
    "theme": "https://raw.githubusercontent.com/microsoft/powerbi-desktop-samples/main/Report%20Theme%20JSON%20Schema/reportThemeSchema-2.159.json",
}
MEASURES = {}


def measure(name, expression, folder, fmt=None):
    MEASURES[name] = (expression, folder, fmt)


def measures():
    measure("Analytics Ready", "SELECTEDVALUE(reporting_readiness[analytics_ready],FALSE())", "Status")
    measure("Risk Ready", "SELECTEDVALUE(reporting_readiness[risk_ready],FALSE())", "Status")
    measure("Insights Ready", "SELECTEDVALUE(reporting_readiness[insights_ready],FALSE())", "Status")
    measure("Readiness", 'IF(COUNTROWS(reporting_readiness)<>1,"Unavailable",IF([Analytics Ready]&&[Risk Ready]&&[Insights Ready],"Ready","Stale"))', "Status")
    measure("Header", '"Price as of " & IF(ISBLANK(SELECTEDVALUE(reporting_readiness[price_as_of])),"unavailable",FORMAT(SELECTEDVALUE(reporting_readiness[price_as_of]),"yyyy-MM-dd")) & "  |  " & [Readiness] & "  |  Simulation completed " & IF(ISBLANK(SELECTEDVALUE(reporting_readiness[simulation_completed_at])),"unavailable",FORMAT(SELECTEDVALUE(reporting_readiness[simulation_completed_at]),"yyyy-MM-dd HH:mm"))', "Status")
    measure("Simulation Run", 'SELECTEDVALUE(reporting_readiness[simulation_run_id],"Unavailable")', "Status")
    measure("Scenario Selector", '"Synthetic fixture scenario"', "Status")
    # Starter measures retained verbatim in meaning and table naming.
    starter = (ROOT/"powerbi/measures.dax").read_text(encoding="utf-8")
    import re
    starter = "\n".join(x for x in starter.splitlines() if not x.startswith("//"))
    for name, expression in re.findall(r"(?m)^([^\n=]+?)\s*=\s*([\s\S]*?)(?=\n\n|\Z)", starter):
        measure(name.strip(), expression.strip(), "Simulation" if "Cost B" in name or "VaR" in name else "Backtest")
    market = "market_decomposition_current"
    measure("Market Date", f"CALCULATE(MAX({market}[price_date]),REMOVEFILTERS())", "Market", "yyyy-MM-dd")
    for label, col in [("Jet", "jet_fuel_gal"), ("WTI", "wti_gal"), ("HO", "heating_oil_gal"), ("Crack", "crack_spread")]:
        measure(f"Latest {label}", f"VAR d=[Market Date] RETURN CALCULATE(SELECTEDVALUE({market}[{col}]),REMOVEFILTERS(),{market}[price_date]=d)", "Market", "0.000")
        measure(f"Prior {label}", f"VAR d=[Market Date] VAR p=MAXX(FILTER(ALL({market}),{market}[price_date]<=EDATE(d,-12)),{market}[price_date]) RETURN CALCULATE(SELECTEDVALUE({market}[{col}]),REMOVEFILTERS(),{market}[price_date]=p)", "Market", "0.000")
        measure(f"Change {label}", f"IF([Insights Ready],[Latest {label}]-[Prior {label}])", "Market", "+0.000;-0.000;0.000")
    measure("WTI Monthly", f"AVERAGE({market}[wti_gal])", "Market", "0.000")
    measure("Crack Monthly", f"AVERAGE({market}[crack_spread])", "Market", "0.000")
    measure("Crack Historical Mean", f"VAR y=YEAR([Market Date]) RETURN AVERAGEX(FILTER(ALL({market}),YEAR({market}[price_date])<y),{market}[crack_spread])", "Market", "0.000")
    measure("Crack Share", "DIVIDE([Change Crack],[Change Jet])", "Market", "0.0%")
    measure("WTI Offset", "DIVIDE([Change WTI],[Change Jet])", "Market", "0.0%")
    measure("Crack Multiple", "DIVIDE([Latest Crack],[Crack Historical Mean])", "Market", "0.0")
    measure("Jet Rank", f"VAR d=[Market Date] RETURN CALCULATE(SELECTEDVALUE({market}[jet_pct_rank_full_history]),REMOVEFILTERS(),{market}[price_date]=d)", "Market", "0.0%")
    measure("Waterfall Value", 'IF([Insights Ready],SWITCH(SELECTEDVALUE(\'Market Steps\'[Step]),"Start",[Prior Jet],"WTI change",[Change WTI],"Crack change",[Change Crack],"Latest",[Latest Jet]))', "Market", "0.000")
    measure("Bridge Low", 'IF([Insights Ready],SWITCH(SELECTEDVALUE(\'Market Steps\'[Step]),"Start",0,"Latest",0,"WTI change",MIN([Prior Jet],[Prior Jet]+[Change WTI]),"Crack change",MIN([Prior Jet]+[Change WTI],[Latest Jet])))', "Market", "0.000")
    measure("Bridge High", 'IF([Insights Ready],SWITCH(SELECTEDVALUE(\'Market Steps\'[Step]),"Start",[Prior Jet],"Latest",[Latest Jet],"WTI change",MAX([Prior Jet],[Prior Jet]+[Change WTI]),"Crack change",MAX([Prior Jet]+[Change WTI],[Latest Jet])))', "Market", "0.000")
    measure("Bridge Label", 'IF([Insights Ready],IF(SELECTEDVALUE(\'Market Steps\'[Step]) IN {"Start","Latest"},FORMAT([Waterfall Value],"$0.000"),FORMAT([Waterfall Value],"+$0.000;-$0.000;$0.000")))', "Market")
    measure("Bridge Color", 'SWITCH(SELECTEDVALUE(\'Market Steps\'[Step]),"WTI change","#B85C38","Crack change","#E0A100","#1F4E79")', "Market")
    measure("Change Per Gallon", 'SWITCH(SELECTEDVALUE(\'Instruments\'[Instrument]),"Jet",[Change Jet],"HO",[Change HO],"WTI",[Change WTI])', "Market", "+0.000;-0.000;0.000")
    corr = "proxy_return_correlation_current"
    for label, col in [("Price Level Correlation", "price_level_corr_jet_wti_90d"), ("WTI Return Correlation", "ret_corr_jet_wti_90d"), ("HO Return Correlation", "ret_corr_jet_ho_90d")]:
        measure(label, f"IF(MAX({corr}[price_date])>EDATE([Market Date],-36),SELECTEDVALUE({corr}[{col}]))", "Proxy", "0.000")
        measure("Latest "+label, f"VAR d=MAXX(ALL({corr}),{corr}[price_date]) RETURN CALCULATE([{label}],REMOVEFILTERS(),{corr}[price_date]=d)", "Proxy", "0.000")
    annual = "proxy_effectiveness_annual_current"
    measure("Proxy R2", f'IF(SELECTEDVALUE({annual}[year])<>"ALL",SELECTEDVALUE({annual}[r2]))', "Proxy", "0.0%")
    measure("Proxy Beta", f"SELECTEDVALUE({annual}[min_var_beta])", "Proxy", "0.000")
    measure("Years Compared", f'COUNTROWS(FILTER(ALL({annual}[year]),{annual}[year]<>"ALL"))', "Proxy", "0")
    measure("HO Wins Years", f'''VAR years=FILTER(ALL({annual}[year]),{annual}[year]<>"ALL") RETURN COUNTROWS(FILTER(years,
        CALCULATE(SELECTEDVALUE({annual}[r2]),{annual}[proxy]="HO")>CALCULATE(SELECTEDVALUE({annual}[r2]),{annual}[proxy]="WTI")))''', "Proxy", "0")
    measure("WTI Years Effective", f'COUNTROWS(FILTER(ALL({annual}),{annual}[year]<>"ALL"&&{annual}[proxy]="WTI"&&{annual}[r2]>=0.8))', "Proxy", "0")
    bt = "hedge_backtest_windows_current"
    base = f"FILTER(ALL({bt}),{bt}[hedge_ratio]=0)"
    measure("Windows", f"COUNTROWS({base})", "Backtest", "0")
    measure("Win Share", f"DIVIDE(COUNTROWS(FILTER({base},{bt}[hedge_won])),[Windows])", "Backtest", "0.0%")
    measure("Mean Savings Gal", f"AVERAGEX({base},{bt}[savings_per_gal])", "Backtest", "+$0.000;-$0.000;$0.000")
    measure("Latest Window Rank", f"CALCULATE(SELECTEDVALUE({bt}[window_pct_rank]),REMOVEFILTERS(),{bt}[hedge_ratio]=0,{bt}[is_latest_complete]=TRUE())", "Backtest", "0.0%")
    measure("Window Savings", f"CALCULATE(SELECTEDVALUE({bt}[savings_per_gal]),{bt}[hedge_ratio]=0)", "Backtest", "+0.000;-0.000;0.000")
    measure("Mean Overrun B", f"IF(HASONEVALUE({bt}[hedge_ratio]),AVERAGE({bt}[budget_overrun_b]))", "Backtest", "0.00")
    measure("P95 Overrun B", f"IF(HASONEVALUE({bt}[hedge_ratio]),PERCENTILEX.INC({bt},{bt}[budget_overrun_b],0.95))", "Backtest", "0.00")
    for h in [0, 80]:
        for prefix in ["Mean", "P95"]:
            measure(f"Historical {prefix} {h}", f"CALCULATE([{prefix} Overrun B],REMOVEFILTERS(),{bt}[hedge_ratio]={h/100})", "Backtest", "0.00")
    measure("Historical Hedge Cost B", "IF([Insights Ready],[Historical Mean 80]-[Historical Mean 0])", "Backtest", "+0.00;-0.00;0.00")
    measure("Historical P95 Move", f"PERCENTILEX.INC({base},DIVIDE({bt}[realized_avg],{bt}[s0])-1,0.95)", "Backtest", "0.0%")
    measure("Route Savings M", "IF(HASONEVALUE('Hedge Scenario'[scenario_id]),SUM('Route Costs'[hedge_savings_usd])/1000000)", "Backtest", "0.00")
    measure("Route Total Savings M", "CALCULATE([Route Savings M],REMOVEFILTERS(dim_route),REMOVEFILTERS(dim_month))", "Backtest", "0.00")
    measure("Route Count", "COUNTROWS(ALL(dim_route))", "Backtest", "0")
    measure("Selected Hedge Ratio", "SELECTEDVALUE('Hedge Scenario'[hedge_ratio])", "Backtest", "0.0%")
    measure("Route Cost M", "DIVIDE([Fuel Cost USD],1000000)", "Backtest", "0.00")
    measure("Route Unhedged M", "DIVIDE([Unhedged Cost USD],1000000)", "Backtest", "0.00")
    measure("B767 Share", 'DIVIDE(SUMX(FILTER(ALL(dim_route),dim_route[aircraft_type]="B767"),dim_route[avg_fuel_burn_gal]*dim_route[daily_frequencies]),SUMX(ALL(dim_route),dim_route[avg_fuel_burn_gal]*dim_route[daily_frequencies]))', "Backtest", "0.0%")
    measure("B767 Departures", 'SUMX(FILTER(ALL(dim_route),dim_route[aircraft_type]="B767"),dim_route[daily_frequencies])', "Backtest", "0")
    history = "calibration_history_current"
    for col in ["mu", "sigma", "mu_pct_rank", "sigma_pct_rank"]:
        measure("Current "+col, f"CALCULATE(SELECTEDVALUE({history}[{col}]),REMOVEFILTERS(),{history}[is_current]=TRUE())", "Simulation", "0.0%")
    measure("Calibration Count", f"COUNTROWS(ALL({history}))", "Simulation", "0")
    measure("Median Mu", f"MEDIANX(ALL({history}),{history}[mu])", "Simulation", "0.0%")
    for col in ["mu", "sigma"]:
        measure(col.upper(), f"SELECTEDVALUE({history}[{col}])", "Simulation", "0.0%")
    for q, label in [(.25, "Mu IQR Low"), (.75, "Mu IQR High")]:
        measure(label, f"PERCENTILEX.INC(ALL({history}),{history}[mu],{q})", "Simulation", "0.0%")
    forecast = "forecast_backtest_current"
    for label, condition in [("Band Coverage", f"{forecast}[inside_band]"), ("Below P05", f"{forecast}[below_p05]")]:
        measure(label, f"DIVIDE(COUNTROWS(FILTER({forecast},{condition})),COUNTROWS({forecast}))", "Simulation", "0.0%")
    measure("High Drift Below P05", f"CALCULATE([Below P05],{forecast}[high_drift]=TRUE())", "Simulation", "0.0%")
    measure("Log RMSE", f"SQRT(AVERAGEX({forecast},{forecast}[log_err_p50]^2))", "Simulation", "0.000")
    for label in ["Band Coverage", "High Drift Below P05"]:
        measure("EWM "+label, f'CALCULATE([{label}],REMOVEFILTERS(),{forecast}[drift_model]="EWM")', "Simulation", "0.0%")
    for col, label in [("p05_price_gal", "Fan P05"), ("p25_price_gal", "Fan P25"), ("p50_price_gal", "Fan Median"), ("p75_price_gal", "Fan P75"), ("p95_price_gal", "Fan P95")]:
        measure(label, f"SELECTEDVALUE(price_fan_current[{col}])", "Simulation", "0.000")
    measure("Terminal Median", "VAR t=MAXX(ALL(price_fan_current),price_fan_current[step]) RETURN CALCULATE([Fan Median],REMOVEFILTERS(),price_fan_current[step]=t)", "Simulation", "0.000")
    for label in ["Mean Cost B", "P95 Cost B", "CVaR95 B"]:
        for h in [0, 80]:
            measure(f"{label} {h}", f"CALCULATE([{label}],REMOVEFILTERS(),'Risk Metrics'[hedge_ratio]={h/100})", "Simulation", "0.00")
    measure("Spot Run Rate B", "[Latest Jet]*1.5", "Simulation", "0.00")
    measure("Simulation Hedge Cost B", "IF([Risk Ready],[Mean Cost B 80]-[Mean Cost B 0])", "Simulation", "+0.00;-0.00;0.00")
    measure("Mean Versus Run Rate", "IF([Risk Ready]&&[Insights Ready],DIVIDE([Mean Cost B 0],[Spot Run Rate B])-1)", "Simulation", "+0.0%;-0.0%;0.0%")
    measure("Model History Cost", 'IF([Readiness]="Ready",SWITCH(SELECTEDVALUE(\'Cost Basis\'[Basis]),"Simulation",[Simulation Hedge Cost B],"History",[Historical Hedge Cost B]))', "Simulation", "+0.00;-0.00;0.00")
    measure("Histogram Paths", "IF(SELECTEDVALUE(cost_histogram_current[hedge_ratio]) IN {0,0.8},SUM(cost_histogram_current[path_count]))", "Simulation", "#,0")
    tails = "return_tail_frequency_current"
    for col, label in [("observed_share", "Observed Tail"), ("normal_share", "Normal Tail"), ("ratio", "Tail Ratio"), ("excess_kurtosis", "Kurtosis")]:
        measure(label, f"SELECTEDVALUE({tails}[{col}])", "Simulation", "0.0%" if "Tail" in label and "Ratio" not in label else "0.0")
    measure("Three Sigma Ratio", f"CALCULATE([Tail Ratio],REMOVEFILTERS(),{tails}[threshold]=3)", "Simulation", "0.0")
    measure("Tail Kurtosis", f"CALCULATE([Kurtosis],REMOVEFILTERS(),{tails}[threshold]=3)", "Simulation", "0.0")
    measure("Sensitivity Difference B", "IF(HASONEVALUE(v_hedge_sensitivity[hedge_ratio])&&HASONEVALUE(v_hedge_sensitivity[price_change_pct]),SELECTEDVALUE(v_hedge_sensitivity[hedged_cost_b])-SELECTEDVALUE(v_hedge_sensitivity[unhedged_cost_b]))", "Scenario", "+0.00;-0.00;0.00")
    measure("Break Even", "EXP(0.04)-1", "Scenario", "0.0%")
    for shock in [-30, 50]:
        measure(f"Shock {shock} Difference", f"CALCULATE([Sensitivity Difference B],REMOVEFILTERS(),v_hedge_sensitivity[hedge_ratio]=0.8,v_hedge_sensitivity[price_change_pct]={shock})", "Scenario", "+0.00;-0.00;0.00")
    measure("Nominal Coverage", "IF([Insights Ready],0.9)", "Simulation", "0%")
    measure("Effective Benchmark", "IF([Insights Ready],0.8)", "Proxy", "0.00")
    measure("Historical P95 Price", "[Latest Jet]*(1+[Historical P95 Move])", "Simulation", "0.000")
    measure("Forward Price", "[Latest Jet]*EXP(0.04)", "Simulation", "0.000")
    measure("Readiness Color", 'SWITCH([Readiness],"Ready","#2E8B57","Stale","#B85C38","#707070")', "Status")
    measure("Sensitivity Magnitude", 'VAR c=[Sensitivity Difference B] VAR cap=MAXX(ALL(v_hedge_sensitivity),ABS(v_hedge_sensitivity[hedged_cost_b]-v_hedge_sensitivity[unhedged_cost_b])) RETURN DIVIDE(ABS(c),cap)', "Scenario")
    measure("Sensitivity Color", 'VAR c=[Sensitivity Difference B] VAR s=[Sensitivity Magnitude] RETURN SWITCH(TRUE(),ISBLANK(c)||c=0,"#FFFFFF",c<0&&s>0.66,"#1F4E79",c<0&&s>0.33,"#82B5D5",c<0,"#D7E8F4",s>0.66,"#B85C38",s>0.33,"#E49C8D","#F3D9D3")', "Scenario")
    measure("Sensitivity Font", 'IF([Sensitivity Magnitude]>0.66,"#FFFFFF","#172B3A")', "Scenario")
    measure("Ratio Color", 'SWITCH(SELECTEDVALUE(hedge_backtest_windows_current[hedge_ratio]),0,"#DCEAF4",0.2,"#A6CCE3",0.4,"#6BAED6",0.6,"#3182BD",0.8,"#08519C","#707070")', "Backtest")
    measure("Proxy Color", 'SWITCH(SELECTEDVALUE(proxy_effectiveness_annual_current[proxy]),"HO","#2E8B57","WTI","#B85C38","BRENT","#7A6C9E","#707070")', "Proxy")
    # Every title branches on available data and uses signed, refresh-sensitive values.
    titles = {
        "1.1": 'VAR c=[Change Crack] VAR w=[Change WTI] RETURN IF(ABS(c)>=ABS(w),"Crack spread","WTI-equivalent") & " contributed " & FORMAT(IF(ABS(c)>=ABS(w),[Crack Share],1-[Crack Share]),"0.0%") & " of jet’s " & FORMAT([Change Jet],"+$0.000;-$0.000;$0.000") & "/gal trailing-year change"',
        "1.2": '"Jet moved from $" & FORMAT([Prior Jet],"0.000") & " to $" & FORMAT([Latest Jet],"0.000") & "/gal: crude plus crack reconcile exactly"',
        "2.1": '"Price levels: WTI " & FORMAT([Latest Price Level Correlation],"0.00") & "; daily returns: WTI " & FORMAT([Latest WTI Return Correlation],"0.00") & ", heating oil " & FORMAT([Latest HO Return Correlation],"0.00")',
        "2.2": 'IF([HO Wins Years]>[Years Compared]/2,"Heating oil","WTI") & " out-tracked " & IF([HO Wins Years]>[Years Compared]/2,"WTI","heating oil") & " in " & FORMAT(IF([HO Wins Years]>[Years Compared]/2,[HO Wins Years],[Years Compared]-[HO Wins Years]),"0") & " of " & FORMAT([Years Compared],"0") & " years; WTI cleared 0.80 R² in " & FORMAT([WTI Years Effective],"0")',
        "2.3": '"WTI changed " & FORMAT([Change WTI],"+$0.000;-$0.000;$0.000") & " vs jet " & FORMAT([Change Jet],"+$0.000;-$0.000;$0.000") & "/gal (" & FORMAT([WTI Offset],"0.0%") & "); heating oil " & FORMAT([Change HO],"+$0.000;-$0.000;$0.000")',
        "3.1": '"A one-year forward beat spot in " & FORMAT([Win Share],"0.0%") & " of " & FORMAT([Windows],"0") & " windows (mean " & FORMAT([Mean Savings Gal],"+$0.000;-$0.000;$0.000") & "/gal)"',
        "3.2": '"80% cover moved historical P95 overrun from $" & FORMAT([Historical P95 0],"0.00") & "B to $" & FORMAT([Historical P95 80],"0.00") & "B; expected cost change " & FORMAT([Historical Hedge Cost B],"+$0.00;-$0.00;$0.00") & "B/yr"',
        "3.3": '"Synthetic " & FORMAT([Route Count],"0") & "-route schedule: " & IF(HASONEVALUE(\'Hedge Scenario\'[scenario_id]),FORMAT(SELECTEDVALUE(\'Hedge Scenario\'[hedge_ratio]),"0%") & " cover, " & FORMAT([Route Total Savings M],"+$0.00;-$0.00;$0.00") & "M savings","select one scenario") & "; " & FORMAT([B767 Share],"0.0%") & " of scheduled gallons on " & FORMAT([B767 Departures],"0") & " daily B767 departures"',
        "4.1": '"Current drift " & FORMAT([Current mu],"0.0%") & "/yr ranks at " & FORMAT([Current mu_pct_rank],"0.0%") & " of " & FORMAT([Calibration Count],"0") & " calibrations; median " & FORMAT([Median Mu],"0.0%")',
        "4.2": '"EWM band covered " & FORMAT([EWM Band Coverage],"0.0%") & " of outcomes (nominal 90%); high-drift outcomes below P05: " & FORMAT([EWM High Drift Below P05],"0.0%")',
        "4.3": '"Model terminal median $" & FORMAT([Terminal Median],"0.000") & "/gal (" & FORMAT(DIVIDE([Terminal Median],[Latest Jet]),"0.0") & "× today); historical P95 average-price move " & FORMAT([Historical P95 Move],"+0.0%;-0.0%;0.0%")',
        "4.4": '"3-sigma weekly moves occur " & FORMAT([Three Sigma Ratio],"0.0") & "× the normal-implied rate; excess kurtosis " & FORMAT([Tail Kurtosis],"0.0")',
        "5.1": '"Unhedged mean $" & FORMAT([Mean Cost B 0],"0.00") & "B (" & FORMAT([Mean Versus Run Rate],"+0.0%;-0.0%;0.0%") & " vs $" & FORMAT([Spot Run Rate B],"0.00") & "B run-rate); CVaR95 $" & FORMAT([CVaR95 B 0],"0.00") & "B → $" & FORMAT([CVaR95 B 80],"0.00") & "B at 80%"',
        "5.2": '"80% cover changes expected cost: model " & FORMAT([Simulation Hedge Cost B],"+$0.00;-$0.00;$0.00") & "B; history " & FORMAT([Historical Hedge Cost B],"+$0.00;-$0.00;$0.00") & "B. Interpret the drift–carry gap."',
        "5.3": '"Hedge break-even is " & FORMAT([Break Even],"0.0%") & "; 80% cover at −30%: " & FORMAT([Shock -30 Difference],"+$0.00;-$0.00;$0.00") & "B, at +50%: " & FORMAT([Shock 50 Difference],"+$0.00;-$0.00;$0.00") & "B"',
    }
    for number, expr in titles.items():
        flag = "[Insights Ready]" if number[0] in "123" else "[Insights Ready]&&[Risk Ready]"
        if number == "3.3":
            flag += "&&[Analytics Ready]"
        measure("Title "+number, f'IF({flag}, {expr}, "Unavailable — complete a current-source publication")', "Headlines")
    subtitles = {
        "1.1": '"Actual EIA monthly averages; full history. Latest month may be partial."',
        "1.2": '"Crack $" & FORMAT([Latest Crack],"0.000") & "/gal = " & FORMAT([Crack Multiple],"0.0") & "× prior-years mean; jet full-sample rank " & FORMAT([Jet Rank],"0.0%")',
        "2.1": '"90 calendar days, ≥20 paired log returns. Price-level, misleading (dashed grey)."',
        "2.2": '"Weekly returns; missing weeks break returns. Benchmark 0.80; tooltip: minimum-variance beta."',
        "2.3": '"Actual spot changes. Position table: Synthetic fixture; linear spot proxies, not forward valuation."',
        "3.1": '"Latest complete window rank " & FORMAT([Latest Window Rank],"0.0%") & "; overlapping windows, descriptive evidence, no independent-trial claim."',
        "3.2": '"Reference carrier, 1.5B gal/yr | P95 of complete one-year purchase windows; means are arithmetic averages."',
        "3.3": '"Synthetic fixture | Latest complete historical window rank " & FORMAT([Latest Window Rank],"0.0%") & "; fixture calendar differs from weekly purchase windows."',
        "4.1": '"EWM μ and σ; full-sample μ interquartile band. Not a forecast."',
        "4.2": '"10,000 common paths/window/model; one-year purchase averages excluding S0. Log-RMSE in tooltip."',
        "4.3": '"Extrapolation of trailing-year drift, not a forecast | P05–P95 outer, P25–P75 inner band; median solid | Reference carrier, 1.5B gal/yr"',
        "4.4": '"Drift can overstate levels while normal shocks understate tail frequency; these errors do not cancel."',
        "5.1": '"Reference carrier, 1.5B gal/yr | Common-path GBM; not a forecast. Fixed 0% and 80% series."',
        "5.2": '"Reference carrier, 1.5B gal/yr | VaR reduction equals coverage (20/40/60/80%) by construction."',
        "5.3": '"Reference carrier, 1.5B gal/yr | Hedged minus unhedged cost; blue saving, red additional cost; signed labels."',
    }
    for number, expr in subtitles.items():
        measure("Subtitle "+number, expr, "Headlines")
    for p, question in enumerate(PAGES, 1):
        measure("Page "+str(p), json.dumps(question, ensure_ascii=False), "Headlines")


PAGES = ["What actually drove the jet fuel spike?", "Which hedge instrument actually tracks jet fuel?",
         "Did hedging pay? 16 years of rolling evidence", "How far should we trust the simulation?",
         "What the model says about the hedge decision, read correctly"]


def save(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content if isinstance(content, str) else json.dumps(content, indent=2, ensure_ascii=False)+"\n", encoding="utf-8")


def quote(value):
    return "'"+value.replace("'", "''")+"'"


def table_definition(name, columns, source, calculated=False):
    text = f"table {quote(name)}\n"
    for col, typ in columns.items():
        source_col = f"[{col}]" if calculated else col
        text += f"\n\tcolumn {quote(col)}\n\t\tdataType: {typ}\n\t\tsummarizeBy: none\n\t\tsourceColumn: {source_col}\n"
        if typ == "dateTime":
            text += "\t\tformatString: yyyy-MM-dd\n"
        elif typ == "double":
            fmt = "0.0%" if col in {"hedge_ratio", "r2", "mu", "sigma", "mu_pct_rank", "sigma_pct_rank", "observed_share", "normal_share"} else "0.00" if col.endswith("_b") else "0.000"
            text += f"\t\tformatString: {fmt}\n"
    kind = "calculated" if calculated else "m"
    text += f"\n\tpartition {quote(name)} = {kind}\n\t\tmode: import\n\t\tsource =\n"
    text += "\n".join("\t\t\t"+x for x in source.splitlines())+"\n"
    save(MODEL/"definition/tables"/(name+".tmdl"), text)


def semantic_model():
    save(PROJECT/"JetFuelHedgeRisk.pbip", dict(**{"$schema": SCHEMAS["pbip"]}, version="1.0",
         artifacts=[{"report": {"path": "JetFuelHedgeRisk.Report"}}], settings={"enableAutoRecovery": True}))
    save(MODEL/"definition.pbism", {"$schema": SCHEMAS["pbism"], "version": "4.0", "settings": {"qnaEnabled": False}})
    save(MODEL/"definition/database.tmdl", "database\n\tcompatibilityLevel: 1600\n")
    save(MODEL/"definition/model.tmdl", "model Model\n\tculture: en-US\n\tdefaultPowerBIDataSourceVersion: powerBI_V3\n\tsourceQueryCulture: en-US\n\tdataAccessOptions\n\t\tlegacyRedirects\n\t\treturnErrorValuesAsNull\n")
    pq = (ROOT/"powerbi/GoldTable.pq").read_text(encoding="utf-8")
    pq = pq[pq.index("(TableName"):]
    save(MODEL/"definition/expressions.tmdl", "expression GoldTable =\n"+"\n".join("\t\t"+line for line in pq.splitlines())+"\n")
    from fuel_hedge.insights import KEYS
    for name in KEYS:
        frame = pd.read_csv(ROOT/f"artifacts/insights_local/{name}.csv")
        specs = {}
        for col in frame:
            dtype = frame[col].dtype
            typ = "dateTime" if col in ["price_date", "window_start", "week_ending"] else "boolean" if dtype.kind == "b" else "int64" if dtype.kind in "iu" else "double" if dtype.kind == "f" else "string"
            specs[col] = typ
        specs.update(insights_run_id="string", source_pipeline_run_id="string", created_ts="dateTime", is_synthetic="boolean")
        table_definition(name+"_current", specs, f'GoldTable("{name}_current")')
    other = {
        "Route Costs": ("route_fuel_costs_current", dict(route_id="string", aircraft_type="string", cost_month="dateTime", scenario_id="string", hedge_ratio="double", monthly_flights="int64", monthly_gallons="double", hedged_cost_usd="double", unhedged_cost_usd="double", hedge_savings_usd="double", is_synthetic="boolean")),
        "Risk Metrics": ("risk_metrics_current", {**dict(hedge_ratio="double", simulation_run_id="string"), **{c:"double" for c in ["mean_cost_b", "p50_cost_b", "p95_cost_b", "var_95_b", "cvar_95_b", "var_reduction_pct", "s0", "mu_calibrated", "sigma_calibrated"]}}),
        "price_fan_current": ("price_fan_current", {"step":"int64", "time_years":"double", **{c:"double" for c in ["p05_price_gal", "p25_price_gal", "p50_price_gal", "p75_price_gal", "p95_price_gal"]}}),
        "cost_histogram_current": ("cost_histogram_current", dict(hedge_ratio="double", bin="int64", bin_lower_cost_b="double", bin_upper_cost_b="double", path_count="int64")),
        "reporting_readiness": ("reporting_readiness", dict(analytics_ready="boolean", risk_ready="boolean", insights_ready="boolean", price_as_of="dateTime", simulation_completed_at="dateTime", simulation_run_id="string", source_pipeline_run_id="string")),
        "dim_route": ("dim_route", dict(route_id="string", origin="string", destination="string", aircraft_type="string", avg_fuel_burn_gal="double", daily_frequencies="int64")),
        "dim_month": ("dim_month", dict(cost_month="dateTime", year="int64", month="int64")),
        "dim_date": ("dim_date", dict(calendar_date="dateTime", cost_month="dateTime", year="int64", month="int64")),
        "Hedge Scenario": ("dim_hedge_scenario", dict(scenario_id="string", hedge_ratio="double", scenario_label="string")),
        "v_hedge_sensitivity": ("v_hedge_sensitivity", dict(hedge_ratio="double", price_change_pct="int64", hedged_cost_b="double", unhedged_cost_b="double")),
        "v_hedge_mtm": ("v_hedge_mtm", dict(underlying="string", locked_price_gal="double", current_spot_gal="double", pnl_per_gallon="double", hedge_status="string", is_synthetic="boolean")),
    }
    for name, (source, specs) in other.items():
        expression = f'GoldTable("{source}")'
        if source in {"v_hedge_mtm", "v_hedge_sensitivity"}:
            expression = f'let Ready=GoldTable("reporting_readiness"), Data=GoldTable("{source}") in if (try Ready{{0}}[analytics_ready] otherwise false) then Data else Table.FirstN(Data,0)'
        table_definition(name, specs, expression)
    for name, col, values in [("Market Steps", "Step", ["Start", "WTI change", "Crack change", "Latest"]),
                              ("Instruments", "Instrument", ["Jet", "HO", "WTI"]),
                              ("Cost Basis", "Basis", ["Simulation", "History"])]:
        data = ",".join('{"'+v+'",'+str(i)+'}' for i, v in enumerate(values))
        table_definition(name, {col:"string", "Ordinal":"int64"}, f'DATATABLE("{col}",STRING,"Ordinal",INTEGER,{{{data}}})', calculated=True)
        path = MODEL/"definition/tables"/(name+".tmdl")
        text = path.read_text(encoding="utf-8").replace(f"\tcolumn {quote(col)}\n", f"\tcolumn {quote(col)}\n\t\tsortByColumn: Ordinal\n")
        save(path, text)
    text = "table _Measures\n\tcolumn Value\n\t\tdataType: int64\n\t\tisHidden\n\t\tsummarizeBy: none\n\t\tsourceColumn: [Value]\n\n\tpartition _Measures = calculated\n\t\tmode: import\n\t\tsource = ROW(\"Value\",1)\n"
    dax = []
    for name, (expression, folder, fmt) in MEASURES.items():
        text += f"\n\tmeasure {quote(name)} =\n"+"\n".join("\t\t\t"+line for line in expression.splitlines())+f"\n\t\tdisplayFolder: {folder}\n"
        if fmt:
            text += f"\t\tformatString: {fmt}\n"
        dax.append(name+" =\n"+expression)
    save(MODEL/"definition/tables/_Measures.tmdl", text)
    save(ROOT/"powerbi/insight_measures.dax", "\n\n".join(dax)+"\n")
    rels = []
    relationships = [("Route Costs", "route_id", "dim_route", "route_id"), ("Route Costs", "cost_month", "dim_month", "cost_month"),
                     ("Route Costs", "scenario_id", "Hedge Scenario", "scenario_id"), ("Risk Metrics", "hedge_ratio", "Hedge Scenario", "hedge_ratio"),
                     ("market_decomposition_current", "price_date", "dim_date", "calendar_date"),
                     ("proxy_return_correlation_current", "price_date", "dim_date", "calendar_date")]
    for i, (fact, fk, dim, pk) in enumerate(relationships):
        rels.append(f"relationship r{i}\n\tfromColumn: {quote(fact)}.{quote(fk)}\n\ttoColumn: {quote(dim)}.{quote(pk)}\n\tfromCardinality: many\n\ttoCardinality: one\n\tcrossFilteringBehavior: oneDirection\n")
    save(MODEL/"definition/relationships.tmdl", "\n".join(rels))


def field(table, name, is_measure=False):
    return {"Measure" if is_measure else "Column": {"Expression": {"SourceRef": {"Entity": table}}, "Property": name}}


def literal(value):
    return {"expr": {"Literal": {"Value": "true" if value is True else "false" if value is False else str(value)+"D" if isinstance(value, (int, float)) else "'"+value.replace("'", "''")+"'"}}}


def dynamic(name):
    return {"expr": field("_Measures", name, True)}


def projection(item):
    table, name = ("_Measures", item) if isinstance(item, str) else item
    return {"field": field(table, name, table == "_Measures"), "queryRef": table+"."+name, "nativeQueryRef": name}


def visual(page, number, kind, roles, position, title=None, subtitle=None, objects=None):
    identifier = "v"+number.replace(".", "_")
    title = title or "Title "+number
    subtitle = subtitle or "Subtitle "+number
    props = {
        "title": [{"properties": {"show": literal(True), "text": dynamic(title), "fontSize": literal(13), "titleWrap": literal(True)}}],
        "subTitle": [{"properties": {"show": literal(True), "text": dynamic(subtitle), "fontSize": literal(10), "titleWrap": literal(True)}}],
        "general": [{"properties": {"altText": dynamic(title)}}],
        "background": [{"properties": {"show": literal(True), "color": {"solid": {"color": literal("#FFFFFF")}}, "transparency": literal(0)}}],
    }
    formatting = {"labels": [{"properties": {"show": literal(kind not in {"lineChart", "stackedAreaChart"}), "labelPrecision": literal(2)}}],
                  "legend": [{"properties": {"show": literal(True)}}]}
    if objects:
        formatting.update(objects)
    data = {"$schema": SCHEMAS["visual"], "name": identifier, "position": dict(zip(["x", "y", "width", "height"], position), z=0, tabOrder=0),
        "visual": {"visualType": kind, "query": {"queryState": {role: {"projections": [projection(v) for v in items]} for role, items in roles.items()}},
                   "visualContainerObjects": props, "objects": formatting}}
    save(REPORT/f"definition/pages/{page}/visuals/{identifier}/visual.json", data)


def report():
    save(REPORT/"definition.pbir", {"$schema": SCHEMAS["pbir"], "version": "4.0", "datasetReference": {"byPath": {"path": "../JetFuelHedgeRisk.SemanticModel"}}})
    save(REPORT/"definition/version.json", {"$schema": SCHEMAS["version"], "version": "2.0.0"})
    save(REPORT/"definition/report.json", {"$schema": SCHEMAS["report"],
        "themeCollection": {"customTheme": {"name": "jet_fuel_theme", "type": "RegisteredResources", "reportVersionAtImport": {"visual": "2.7.0", "page": "2.1.0", "report": "3.3.0"}}},
        "resourcePackages": [{"name": "RegisteredResources", "type": "RegisteredResources", "items": [{"name": "jet_fuel_theme", "path": "jet_fuel_theme.json", "type": "CustomTheme"}]}]})
    theme = {"$schema": SCHEMAS["theme"], "name": "Jet fuel evidence", "dataColors": ["#1F4E79", "#B85C38", "#2E8B57", "#7A6C9E", "#E0A100"],
             "background": "#F3F5F7", "foreground": "#172B3A", "tableAccent": "#1F4E79",
             "textClasses": {"title": {"fontFace": "Segoe UI", "fontSize": 13}, "label": {"fontFace": "Segoe UI", "fontSize": 10}},
             "visualStyles": {"*": {"*": {"labels": [{"show": True}], "legend": [{"show": True}], "lineStyles": [{"showMarker": True}]}}}}
    save(REPORT/"StaticResources/RegisteredResources/jet_fuel_theme.json", theme)
    save(REPORT/"definition/pages/pages.json", {"$schema": SCHEMAS["pages"], "pageOrder": ["page"+str(i) for i in range(1, 6)], "activePageName": "page1"})
    for i, question in enumerate(PAGES, 1):
        page = "page"+str(i)
        save(REPORT/f"definition/pages/{page}/page.json", {"$schema": SCHEMAS["page"], "name": page, "displayName": question, "displayOption": "FitToPage", "width": 1280, "height": 720})
        visual(page, f"{i}_header", "card", {"Values": ["Header"], "Tooltips": ["Simulation Run"]}, [20, 8, 1240, 88], title="Page "+str(i), subtitle="Readiness")
    m, c, a, b, h, f, t = [name+"_current" for name in ["market_decomposition", "proxy_return_correlation", "proxy_effectiveness_annual", "hedge_backtest_windows", "calibration_history", "forecast_backtest", "return_tail_frequency"]]
    visual("page1", "1.1", "stackedAreaChart", {"Category": [("dim_date", "cost_month")], "Y": ["WTI Monthly", "Crack Monthly"]}, [20, 112, 1240, 310])
    visual("page1", "1.2", "waterfallChart", {"Category": [("Market Steps", "Step")], "Y": ["Waterfall Value"]}, [20, 434, 1240, 265])
    visual("page2", "2.1", "lineChart", {"Category": [(c, "price_date")], "Y": ["Price Level Correlation", "WTI Return Correlation", "HO Return Correlation"]}, [20, 112, 610, 275])
    visual("page2", "2.2", "clusteredColumnChart", {"Category": [(a, "year")], "Series": [(a, "proxy")], "Y": ["Proxy R2"], "Tooltips": ["Proxy Beta"]}, [650, 112, 610, 275])
    visual("page2", "2.3", "clusteredBarChart", {"Category": [("Instruments", "Instrument")], "Y": ["Change Per Gallon"]}, [20, 403, 610, 296])
    visual("page2", "2_3_marks", "tableEx", {"Values": [("v_hedge_mtm", col) for col in ["underlying", "locked_price_gal", "current_spot_gal", "pnl_per_gallon", "hedge_status"]]}, [650, 403, 610, 296], title="Subtitle 2.3", subtitle="Header")
    visual("page3", "3.1", "clusteredColumnChart", {"Category": [(b, "window_start")], "Y": ["Window Savings"], "Series": [(b, "hedge_won")]}, [20, 112, 790, 270])
    visual("page3", "3.2", "scatterChart", {"Category": [(b, "hedge_ratio")], "X": ["Mean Overrun B"], "Y": ["P95 Overrun B"]}, [830, 112, 430, 270])
    visual("page3", "3.3", "lineClusteredColumnComboChart", {"Category": [("dim_month", "cost_month")], "Y": ["Route Cost M"], "Y2": ["Route Unhedged M"]}, [20, 400, 630, 299])
    visual("page3", "3_3_routes", "clusteredBarChart", {"Category": [("dim_route", "route_id")], "Series": [("dim_route", "aircraft_type")], "Y": ["Route Savings M"]}, [670, 400, 590, 299], title="Title 3.3", subtitle="Subtitle 3.3")
    visual("page3", "3_slicer", "slicer", {"Values": [("Hedge Scenario", "scenario_label")]}, [840, 86, 420, 28], title="Readiness", subtitle="Readiness", objects={"selection": [{"properties": {"singleSelect": literal(True), "selectAllCheckboxEnabled": literal(False)}}]})
    visual("page4", "4.1", "lineChart", {"Category": [(h, "week_ending")], "Y": ["MU", "SIGMA"]}, [20, 112, 610, 275])
    visual("page4", "4.2", "clusteredBarChart", {"Category": [(f, "drift_model")], "Y": ["Band Coverage", "Below P05", "High Drift Below P05"], "Tooltips": ["Log RMSE"]}, [650, 112, 610, 275])
    visual("page4", "4.3", "lineChart", {"Category": [("price_fan_current", "step")], "Y": ["Fan P05", "Fan P25", "Fan Median", "Fan P75", "Fan P95", "Latest Jet", "Forward Price", "Historical P95 Price"]}, [20, 403, 610, 296])
    visual("page4", "4.4", "clusteredColumnChart", {"Category": [(t, "threshold")], "Y": ["Observed Tail", "Normal Tail"], "Tooltips": ["Tail Ratio"]}, [650, 403, 610, 296])
    visual("page5", "5.1", "lineChart", {"Category": [("cost_histogram_current", "bin_lower_cost_b")], "Series": [("cost_histogram_current", "hedge_ratio")], "Y": ["Histogram Paths"]}, [20, 112, 790, 290])
    visual("page5", "5.2", "clusteredBarChart", {"Category": [("Cost Basis", "Basis")], "Y": ["Model History Cost"]}, [830, 112, 430, 290])
    visual("page5", "5.3", "pivotTable", {"Rows": [("v_hedge_sensitivity", "hedge_ratio")], "Columns": [("v_hedge_sensitivity", "price_change_pct")], "Values": ["Sensitivity Difference B"]}, [20, 420, 1240, 279])
    decorate_report()
    layered_visuals()


def layered_visuals():
    """Use certified Deneb for bands/layers rather than approximating them with price lines.

PBIR configuration follows https://deneb.guide/docs/pbir-guide. Desktop retrieves
the certified visual from AppSource; there is no vendored executable or credential.
"""
    guid = "deneb7E15AEF80B9E4D4F8E12924291ECE89A"
    report_path = REPORT/"definition/report.json"
    content = json.loads(report_path.read_text(encoding="utf-8"))
    content["publicCustomVisuals"] = [guid]
    save(report_path, content)
    def encoding(name, typ="quantitative", **kwargs):
        return dict(field=name, type=typ, **kwargs)
    def layer_chart(page, number, columns, spec):
        path = REPORT/f"definition/pages/page{page}/visuals/v{number.replace('.', '_')}/visual.json"
        obj = json.loads(path.read_text(encoding="utf-8"))
        spec.update({"$schema": "https://vega.github.io/schema/vega-lite/v5.json", "data": {"name": "dataset"},
                     "width": "container", "height": "container", "autosize": {"type": "fit", "contains": "padding"},
                     "config": {"font": "Segoe UI", "axis": {"labelFontSize": 10, "titleFontSize": 11}, "view": {"stroke": None}}})
        # The status overlay uses no fabricated numeric data. All plotted data comes from model fields.
        for layer in spec["layer"]:
            layer["transform"] = [{"filter": "datum.Readiness == 'Ready'"}]+layer.get("transform", [])
        spec["layer"].append({"data": {"values": [{"message": "Unavailable — complete current-source publication"}]},
            "transform": [{"filter": "length(data('dataset')) == 0 || data('dataset')[0].Readiness != 'Ready'"}], "mark": {"type": "text", "align": "center", "color": "#707070", "fontSize": 13},
            "encoding": {"x": {"value": 240}, "y": {"value": 100}, "text": {"field": "message"}}})
        obj["visual"]["visualType"] = guid
        obj["visual"]["query"] = {"queryState": {"dataset": {"projections": [projection(c) for c in columns+["Readiness"]]}}}
        obj["visual"]["objects"] = {"vega": [{"properties": {"jsonSpec": literal(json.dumps(spec, separators=(",", ":"))), "jsonConfig": literal("{}"), "provider": literal("vegaLite"), "renderMode": literal("svg")}}]}
        save(path, obj)
    h = "calibration_history_current"
    layer_chart(1, "1.2", [("Market Steps", "Step"), ("Market Steps", "Ordinal"), "Bridge Low", "Bridge High", "Bridge Label", "Bridge Color"], {
        "layer": [
            {"mark": {"type": "bar", "width": {"band": .75}}, "encoding": {"x": encoding("Step", "ordinal", sort={"field": "Ordinal", "order": "ascending"}, axis={"labelAngle": 0}),
                "y": encoding("Bridge Low", title="$/gal"), "y2": {"field": "Bridge High"}, "color": encoding("Bridge Color", "nominal", scale=None, legend=None),
                "tooltip": [{"field": "Bridge Label", "type": "nominal"}]}},
            {"mark": {"type": "text", "dy": -8, "fontSize": 11}, "encoding": {"x": encoding("Step", "ordinal", sort={"field": "Ordinal", "order": "ascending"}), "y": encoding("Bridge High"), "text": {"field": "Bridge Label"}}}]})
    layer_chart(4, "4.1", [(h, "week_ending"), "MU", "SIGMA", "Mu IQR Low", "Mu IQR High", (h, "is_current")], {
        "resolve": {"scale": {"y": "independent"}}, "layer": [
            {"layer": [
                {"mark": {"type": "area", "opacity": .12, "color": "#1F4E79"}, "encoding": {"x": encoding("week_ending", "temporal"), "y": encoding("Mu IQR Low", title="Annual drift μ"), "y2": {"field": "Mu IQR High"}}},
                {"mark": {"type": "line", "color": "#1F4E79"}, "encoding": {"x": encoding("week_ending", "temporal"), "y": encoding("MU", title="Annual drift μ"), "tooltip": [encoding("week_ending", "temporal"), encoding("MU", format=".1%")] }},
                {"transform": [{"filter": "datum.is_current"}], "mark": {"type": "point", "shape": "diamond", "filled": True, "size": 70, "color": "#1F4E79"}, "encoding": {"x": encoding("week_ending", "temporal"), "y": encoding("MU")}},
                {"transform": [{"filter": "datum.is_current"}], "mark": {"type": "text", "align": "right", "dy": -12, "color": "#1F4E79"}, "encoding": {"x": encoding("week_ending", "temporal"), "y": encoding("MU"), "text": encoding("MU", format=".1%")}}]},
            {"mark": {"type": "line", "color": "#B85C38", "strokeDash": [5, 3]}, "encoding": {"x": encoding("week_ending", "temporal"), "y": encoding("SIGMA", title="Annual volatility σ", axis={"orient": "right"}), "tooltip": [encoding("SIGMA", format=".1%")]}}
        ]})
    layer_chart(4, "4.3", [("price_fan_current", "step"), "Fan P05", "Fan P25", "Fan Median", "Fan P75", "Fan P95", "Latest Jet", "Forward Price", "Historical P95 Price"], {
        "encoding": {"x": encoding("step", title="Future week")}, "layer": [
            {"mark": {"type": "area", "opacity": .16, "color": "#1F4E79"}, "encoding": {"y": encoding("Fan P05", title="$/gal"), "y2": {"field": "Fan P95"}}},
            {"mark": {"type": "area", "opacity": .33, "color": "#1F4E79"}, "encoding": {"y": encoding("Fan P25"), "y2": {"field": "Fan P75"}}},
            {"mark": {"type": "line", "color": "#1F4E79", "strokeWidth": 2}, "encoding": {"y": encoding("Fan Median"), "tooltip": [encoding("Fan Median", format=".3f"), encoding("Fan P05", format=".3f"), encoding("Fan P95", format=".3f")]}},
            *[{"mark": {"type": "line", "color": tint, "strokeDash": dash}, "encoding": {"y": encoding(name), "tooltip": [encoding(name, format=".3f")]}} for name, tint, dash in [
                ("Latest Jet", "#333333", [2, 2]), ("Forward Price", "#B85C38", [6, 2, 2, 2]), ("Historical P95 Price", "#2E8B57", [6, 3])]]]})
    layer_chart(5, "5.1", [("cost_histogram_current", c) for c in ["bin_lower_cost_b", "bin_upper_cost_b", "hedge_ratio"]]+["Histogram Paths", "Spot Run Rate B", "Mean Cost B 0", "P95 Cost B 0", "CVaR95 B 0", "Mean Cost B 80", "P95 Cost B 80", "CVaR95 B 80"], {
        "transform": [{"filter": "datum.hedge_ratio == 0 || datum.hedge_ratio == 0.8"}], "layer": [
            {"mark": {"type": "bar", "opacity": .4, "binSpacing": 0}, "encoding": {
                "x": encoding("bin_lower_cost_b", bin="binned", title="Annual cost, $B"), "x2": {"field": "bin_upper_cost_b"},
                "y": encoding("Histogram Paths", title="Paths per bin"), "color": encoding("hedge_ratio", "nominal", scale={"domain": [0, .8], "range": ["#B85C38", "#1F4E79"]}, title="Coverage"),
                "tooltip": [encoding("hedge_ratio", format=".0%"), encoding("bin_lower_cost_b", format=".2f"), encoding("Histogram Paths")] }},
            *[{"transform": [{"aggregate": [{"op": "max", "field": name, "as": "rule_"+name}]}], "mark": {"type": "rule", "color": tint, "strokeDash": dash},
                "encoding": {"x": encoding("rule_"+name), "tooltip": [{"field": "rule_"+name, "type": "quantitative", "title": name, "format": ".2f"}]}}
              for name, tint, dash in [("Spot Run Rate B", "#333333", [3, 2, 1, 2]),
                 ("Mean Cost B 0", "#B85C38", [1, 0]), ("P95 Cost B 0", "#B85C38", [5, 3]), ("CVaR95 B 0", "#B85C38", [2, 2]),
                 ("Mean Cost B 80", "#1F4E79", [1, 0]), ("P95 Cost B 80", "#1F4E79", [5, 3]), ("CVaR95 B 80", "#1F4E79", [2, 2])]]]})


def decorate_report():
    """Native formatting and analytics references; Desktop rendering remains a separate gate."""
    def path(page, number):
        return REPORT/f"definition/pages/page{page}/visuals/v{number.replace('.', '_')}/visual.json"
    def change(page, number, fn):
        target = path(page, number)
        content = json.loads(target.read_text(encoding="utf-8"))
        fn(content["visual"])
        save(target, content)
    def color(value):
        return {"solid": {"color": literal(value)}}
    def lines(names):
        return [{"selector": {"metadata": "_Measures."+name}, "properties": {
            "show": literal(True), "value": dynamic(name), "lineColor": color(tint),
            "style": literal("dashed"), "dataLabelShow": literal(True), "displayName": literal(name),
            "dataLabelText": literal("NameAndValue"), "dataLabelDecimalPoints": literal(2)}} for name, tint in names]
    def ref(page, number, names, axis="y1AxisReferenceLine"):
        change(page, number, lambda v: v["objects"].update({axis: lines(names)}))
    ref(1, "1.1", [("Crack Historical Mean", "#777777")])
    ref(2, "2.2", [("Effective Benchmark", "#555555")])
    ref(2, "2.3", [("Change Jet", "#1F4E79")], "xAxisReferenceLine")
    ref(4, "4.2", [("Nominal Coverage", "#555555")], "xAxisReferenceLine")
    ref(4, "4.3", [("Latest Jet", "#333333"), ("Forward Price", "#B85C38"), ("Historical P95 Price", "#2E8B57")])
    ref(5, "5.1", [("Spot Run Rate B", "#333333"), ("Mean Cost B 0", "#B85C38"),
                      ("P95 Cost B 0", "#B85C38"), ("CVaR95 B 0", "#B85C38"),
                      ("Mean Cost B 80", "#1F4E79"), ("P95 Cost B 80", "#1F4E79"),
                      ("CVaR95 B 80", "#1F4E79")], "xAxisReferenceLine")
    for page, number, palette in [(1, "1.1", [("WTI Monthly", "#B85C38"), ("Crack Monthly", "#E0A100")]),
                                  (2, "2.1", [("Price Level Correlation", "#777777"), ("WTI Return Correlation", "#B85C38"), ("HO Return Correlation", "#2E8B57")]),
                                  (4, "4.1", [("MU", "#1F4E79"), ("SIGMA", "#B85C38")])]:
        change(page, number, lambda v, palette=palette: v["objects"].update({"dataPoint": [
            {"selector": {"metadata": "_Measures."+name}, "properties": {"fill": color(tint)}} for name, tint in palette]}))
    change(2, "2.1", lambda v: v["objects"].update({"lineStyles": [
        {"selector": {"metadata": "_Measures.Price Level Correlation"}, "properties": {"lineStyle": literal("dashed"), "strokeColor": color("#777777")}},
        {"selector": {"metadata": "_Measures.WTI Return Correlation"}, "properties": {"showMarker": literal(True), "markerShape": literal("circle")}},
        {"selector": {"metadata": "_Measures.HO Return Correlation"}, "properties": {"showMarker": literal(True), "markerShape": literal("diamond")}}]}))
    # Native matrix totals are meaningless across shocks/ratios; signed cell values carry meaning.
    change(5, "5.3", lambda v: v["objects"].update({
        "values": [{"selector": {"metadata": "_Measures.Sensitivity Difference B"}, "properties": {
            "backColor": {"solid": {"color": dynamic("Sensitivity Color")}},
            "fontColor": {"solid": {"color": dynamic("Sensitivity Font")}}, "labelPrecision": literal(2)}}],
        "subTotals": [{"properties": {"rowSubtotals": literal(False), "columnSubtotals": literal(False)}}]}))
    change(2, "2.2", lambda v: v["objects"].update({
        "dataPoint": [{"properties": {"fill": {"solid": {"color": dynamic("Proxy Color")}}}}],
        "labels": [{"properties": {"show": literal(True), "enableTitleDataLabel": literal(True), "titleContentType": literal("Series name"), "fontSize": literal(8)}}]}))
    change(3, "3.2", lambda v: v["objects"].update({
        "dataPoint": [{"properties": {"fill": {"solid": {"color": dynamic("Ratio Color")}}}}],
        "categoryLabels": [{"properties": {"show": literal(True)}}]}))
    for page in range(1, 6):
        def header_style(v):
            v["objects"].update({"labels": [{"properties": {"fontSize": literal(11), "color": {"solid": {"color": dynamic("Readiness Color")}}}}],
                                 "categoryLabels": [{"properties": {"show": literal(False)}}]})
            v["visualContainerObjects"]["title"][0]["properties"]["fontSize"] = literal(19)
            v["visualContainerObjects"]["background"][0]["properties"]["color"] = color("#EAF0F5")
        change(page, f"{page}_header", header_style)
    # Persist a selected scenario, without restricting the slicer's list of choices.
    change(3, "3_slicer", lambda v: v["objects"].update({"general": [{"properties": {"filter": {
        "filter": {"Version": 2, "From": [{"Name": "s", "Entity": "Hedge Scenario", "Type": 0}], "Where": [{"Condition": {"In": {
            "Expressions": [{"Column": {"Expression": {"SourceRef": {"Source": "s"}}, "Property": "scenario_label"}}],
            "Values": [[{"Literal": {"Value": "'80% futures'"}}]]}}}]}}}}]}))
    target = path(3, "3_slicer")
    content = json.loads(target.read_text(encoding="utf-8"))
    content["position"].update(x=940, y=40, width=320, height=58, z=1)
    content["visual"]["visualContainerObjects"]["title"][0]["properties"]["text"] = dynamic("Scenario Selector")
    content["visual"]["visualContainerObjects"]["subTitle"][0]["properties"]["show"] = literal(False)
    save(target, content)
    target = path(3, "3_header")
    content = json.loads(target.read_text(encoding="utf-8"))
    content["position"]["width"] = 900
    save(target, content)
    # The fixed histogram series are limited in the measure, including when all ratios import.
    change(5, "5.1", lambda v: v["objects"].update({"lineStyles": [{"properties": {"interpolationStep": literal("step-before"), "areaShow": literal(True)}}],
        "categoryAxis": [{"properties": {"axisType": literal("Scalar")}}]}))


def main():
    measures()
    semantic_model()
    report()
    columns = [name for name in MEASURES if name.startswith("Title ")]
    query = 'EVALUATE CALCULATETABLE(ROW(\n'+',\n'.join('    "'+name+'",['+name+']' for name in columns)+'\n),TREATAS({"H080"},\'Hedge Scenario\'[scenario_id]))\n'
    save(ROOT/"powerbi/tests/headlines.dax", query)
    numeric = [name for name, (_, folder, fmt) in MEASURES.items() if fmt and folder != "Status"]
    save(ROOT/"powerbi/tests/headline_numbers.dax", 'EVALUATE CALCULATETABLE(ROW(\n'+',\n'.join('    "'+name+'",['+name+']' for name in numeric)+'\n),TREATAS({"H080"},\'Hedge Scenario\'[scenario_id]))\n')
    print(f"Generated five-page PBIP with {len(MEASURES)} measures")


if __name__ == "__main__":
    main()
