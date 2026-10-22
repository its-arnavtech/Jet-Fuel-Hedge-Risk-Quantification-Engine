"""Validate Microsoft schemas, model bindings and headline SQL contract.

Does not claim to execute DAX. Native model parse and DAX execution are separate gates.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import urllib.parse
import urllib.request

import jsonschema

from build_powerbi import MEASURES, PROJECT, REPORT, measures


def fetch_schema(url):
    url = url.replace("/schema.embedded.json", "/schema-embedded.json")
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in {"developer.microsoft.com", "raw.githubusercontent.com", "vega.github.io"}:
        raise ValueError("Schema must come from official Microsoft HTTPS sources")
    if parsed.hostname == "raw.githubusercontent.com" and not parsed.path.startswith("/microsoft/"):
        raise ValueError("Only Microsoft schema repository allowed")
    cache = Path(".tmp/powerbi_schema_cache")
    cache.mkdir(parents=True, exist_ok=True)
    path = cache/(hashlib.sha256(url.encode()).hexdigest()+".json")
    if not path.exists():
        with urllib.request.urlopen(url, timeout=30) as response:
            path.write_bytes(response.read())
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--desktop-results", help="Read actual ADOMD query output and compare headline inputs with live Python evidence")
    args = parser.parse_args()
    measures()
    for name, (expression, _, _) in MEASURES.items():
        for reference in re.findall(r"(?<![A-Za-z0-9_'])\[([^\]]+)\]", expression):
            if reference not in MEASURES:
                raise ValueError(f"Unknown measure dependency: {name} -> {reference}")
    validations = []
    for path in sorted(PROJECT.rglob("*")):
        if path.suffix not in {".json", ".pbip", ".pbir", ".pbism"} or ".pbi" in path.parts:
            continue
        instance = json.loads(path.read_text(encoding="utf-8"))
        schema = fetch_schema(instance["$schema"])
        # RefResolver retains each schema's base URI, including relative embedded references.
        resolver = jsonschema.RefResolver(base_uri=instance["$schema"], referrer=schema,
            handlers={"https": fetch_schema})
        jsonschema.Draft7Validator(schema, resolver=resolver).validate(instance)
        validations.append(str(path.relative_to(PROJECT)))
    tables = {}
    for path in (PROJECT/"JetFuelHedgeRisk.SemanticModel/definition/tables").glob("*.tmdl"):
        text = path.read_text(encoding="utf-8")
        tables[path.stem] = set(re.findall(r"(?m)^\tcolumn (?:'([^']+)'|([^\s]+))", text))
        tables[path.stem] = {a or b for a, b in tables[path.stem]}
    bindings = 0
    layered_specs = 0
    for path in REPORT.glob("definition/pages/*/visuals/*/visual.json"):
        visual = json.loads(path.read_text(encoding="utf-8"))
        aliases = {}
        def walk(value):
            nonlocal bindings
            if isinstance(value, dict):
                if "From" in value:
                    aliases.update({source["Name"]: source["Entity"] for source in value["From"] if "Entity" in source})
                for kind in ["Column", "Measure"]:
                    if kind in value:
                        obj = value[kind]
                        source = obj["Expression"]["SourceRef"]
                        table, name = source.get("Entity", aliases.get(source.get("Source"))), obj["Property"]
                        if kind == "Measure":
                            if table != "_Measures" or name not in MEASURES:
                                raise ValueError(f"Unknown measure: {table}.{name}")
                        elif name not in tables.get(table, set()):
                            raise ValueError(f"Unknown column: {table}.{name}")
                        bindings += 1
                for child in value.values():
                    walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)
        walk(visual)
        if visual["visual"]["visualType"].startswith("deneb"):
            value = visual["visual"]["objects"]["vega"][0]["properties"]["jsonSpec"]["expr"]["Literal"]["Value"]
            spec = json.loads(value[1:-1].replace("''", "'"))
            spec_schema = fetch_schema(spec["$schema"])
            jsonschema.Draft7Validator(spec_schema).validate(spec)
            layered_specs += 1
        if "general" not in visual["visual"]["visualContainerObjects"]:
            raise ValueError("Every visual requires alt text")
    titles = [name for name in MEASURES if name.startswith("Title ")]
    if len(titles) != 15:
        raise ValueError("Exactly 15 headline units required")
    evidence = dict(json_schemas_passed=True, json_files=len(validations), schema_validated_files=validations,
                    field_bindings_checked=bindings, layered_specs_validated=layered_specs, titles=len(titles),
                    tmdl_parsed=False, dax_executed=False, desktop_rendered=False)
    if args.live:
        from fuel_hedge.config import Settings, load_env
        from fuel_hedge.databricks import workspace_client
        from verify_phase1 import query
        load_env()
        settings = Settings.from_env()
        client = workspace_client(settings)
        statement = (Path("powerbi/tests/headline_numbers.sql")).read_text(encoding="utf-8")
        statement = statement.replace("jet_fuel_gold.", settings.catalog+".jet_fuel_gold.")
        result = query(client, settings.warehouse_id, statement)
        if len(result) != 50 or result.duplicated(["finding", "metric"]).any():
            raise ValueError("Warehouse headline contract requires exactly 50 distinct inputs; empty/unready results fail closed")
        expected = json.loads(Path("docs/evidence/phase5_verification.json").read_text(encoding="utf-8"))["findings"]
        import numpy as np
        for row in result.to_dict("records"):
            value = expected[row["finding"]]
            for key in row["metric"].split("."):
                value = value[key]
            np.testing.assert_allclose(float(row["value"]), value, atol=1e-9, rtol=0)
        evidence["sql_headline_numbers_checked"] = len(result)
    if args.desktop_results:
        import numpy as np
        desktop = json.loads(Path(args.desktop_results).read_text(encoding="utf-8-sig"))
        if not desktop["dax_executed"] or not desktop["ready"]:
            raise ValueError("Desktop model must be refreshed and Ready before numeric verification")
        f = json.loads(Path("docs/evidence/phase5_verification.json").read_text(encoding="utf-8"))["findings"]
        values = desktop["numbers"][0]
        expected = {
            "Change Jet": f["F1"]["jet_change"], "Change WTI": f["F1"]["wti_change"],
            "Change Crack": f["F1"]["crack_change"], "Crack Share": f["F1"]["crack_share"],
            "Latest Crack": f["F1"]["crack"], "Crack Multiple": f["F1"]["crack_multiple"], "Jet Rank": f["F1"]["jet_rank"],
            "Latest Price Level Correlation": f["F2"]["price_level"], "Latest WTI Return Correlation": f["F2"]["returns_wti"],
            "Latest HO Return Correlation": f["F2"]["returns_ho"], "HO Wins Years": f["F3"]["ho_wins"],
            "Years Compared": f["F3"]["years"], "WTI Years Effective": f["F3"]["wti_effective"],
            "Change HO": f["F4"]["ho_change"], "WTI Offset": f["F4"]["wti_change"]/f["F4"]["jet_change"],
            "Windows": f["F5"]["windows"], "Win Share": f["F5"]["win_rate"], "Mean Savings Gal": f["F5"]["mean_savings"],
            "Historical P95 0": f["F5"]["p95_unhedged"], "Historical P95 80": f["F5"]["p95_80"],
            "Historical Hedge Cost B": f["F5"]["expected_hedge_cost_b"], "Latest Window Rank": f["F6"]["latest_rank"],
            "Route Total Savings M": f["F12"]["route_savings_80_m"], "B767 Share": f["F12"]["b767_gallon_share"],
            "B767 Departures": f["F12"]["b767_departures"], "Current mu": f["F7"]["mu"], "Current sigma": f["F7"]["sigma"],
            "Current mu_pct_rank": f["F7"]["mu_rank"], "Calibration Count": f["F7"]["calibrations"], "Median Mu": f["F7"]["median_mu"],
            "EWM Band Coverage": f["F8"]["EWM"]["coverage"], "EWM High Drift Below P05": f["F8"]["EWM"]["high_drift_below"],
            "Terminal Median": f["F10"]["terminal_median"], "Historical P95 Move": f["F10"]["historical_p95_move"],
            "Three Sigma Ratio": f["F9"]["ratio"], "Tail Kurtosis": f["F9"]["excess_kurtosis"],
            "Mean Cost B 0": f["F10"]["mean_cost_b"], "Mean Versus Run Rate": f["F10"]["mean_vs_spot"],
            "Spot Run Rate B": f["F10"]["spot_run_rate_b"], "CVaR95 B 0": f["F10"]["cvar_unhedged"], "CVaR95 B 80": f["F10"]["cvar_80"],
            "Simulation Hedge Cost B": f["F10"]["simulation_hedge_change_b"], "Break Even": f["F11"]["break_even"],
            "Shock -30 Difference": f["F11"]["minus30_cost_b"], "Shock 50 Difference": f["F11"]["plus50_cost_b"], "Selected Hedge Ratio": .8,
        }
        for name, number in expected.items():
            if values.get(name) is None:
                raise ValueError("Missing Desktop headline number: "+name)
            np.testing.assert_allclose(float(values[name]), number, atol=1e-9, rtol=0, err_msg=name)
        if not all(str(value).strip() and "Unavailable" not in str(value) for value in desktop["headlines"][0].values()):
            raise ValueError("At least one Desktop headline is unavailable")
        evidence["dax_executed"] = True
        evidence["desktop_headline_inputs_reconciled"] = len(expected)
        import pandas as pd
        folder = Path("artifacts/insights_gold")
        market = pd.read_csv(folder/"market_decomposition.csv", parse_dates=["price_date"])
        latest_date = market.price_date.max()
        latest_month = market.loc[market.price_date.dt.to_period("M").eq(latest_date.to_period("M")), "jet_fuel_gal"].mean()
        np.testing.assert_allclose(values["Latest Monthly Jet"], latest_month, atol=1e-9, rtol=0)
        evidence["desktop_latest_month_annotation_reconciled"] = True
        grains = desktop["grains"]
        if len(grains) != 4 or [len(rows) for rows in grains] != [5, 54, 5, 3]:
            raise ValueError("Unexpected Desktop risk/proxy/frontier/coverage grains")
        risk = pd.read_csv(folder/"risk_metrics.csv")
        routes = pd.read_csv(folder/"route_fuel_costs.csv")
        base_routes = routes.loc[routes.hedge_ratio.eq(0)]
        comparisons = 0
        def check(value, target, label):
            nonlocal comparisons
            if value is None:
                raise ValueError("Unexpected blank Desktop grain: "+label)
            np.testing.assert_allclose(float(value), target, atol=1e-9, rtol=0, err_msg=label)
            comparisons += 1
        for row in grains[0]:
            ratio = float(row["scenario_label"].split("%", 1)[0])/100
            actual_risk = risk.loc[np.isclose(risk.hedge_ratio, ratio)].iloc[0]
            for title, column in [("Mean Cost B", "mean_cost_b"), ("P95 Cost B", "p95_cost_b"), ("CVaR95 B", "cvar_95_b")]:
                check(row[title], actual_risk[column], title)
            check(row["Fuel Gallons"], base_routes.monthly_gallons.sum(), "scenario-safe gallons")
            # Compare monetary sums in the report's $M units: VertiPaq and NumPy
            # reduction order differs at ~3e-8 USD on an 88M USD sum.
            check(row["Unhedged Cost USD"]/1e6, base_routes.unhedged_cost_usd.sum()/1e6, "scenario-safe unhedged cost, $M")
            check(row["Fuel Cost USD"]/1e6, routes.loc[np.isclose(routes.hedge_ratio, ratio), "hedged_cost_usd"].sum()/1e6, "single-scenario cost, $M")
        annual = pd.read_csv(folder/"proxy_effectiveness_annual.csv")
        for row in grains[1]:
            source = annual.loc[annual.year.astype(str).eq(str(row["year"])) & annual.proxy.eq(row["proxy"])].iloc[0]
            if str(row["year"]) == "ALL":
                if row["R2"] is not None:
                    raise ValueError("ALL R2 must not enter the annual chart")
            else:
                check(row["R2"], source.r2, "annual R2")
            check(row["Beta"], source.min_var_beta, "annual beta")
        windows = pd.read_csv(folder/"hedge_backtest_windows.csv")
        for row in grains[2]:
            source = windows.loc[np.isclose(windows.hedge_ratio, row["hedge_ratio"]), "budget_overrun_b"]
            check(row["Mean Overrun B"], source.mean(), "frontier mean")
            check(row["P95 Overrun B"], source.quantile(.95), "frontier P95")
        for row in grains[3]:
            source = f["F8"][row["drift_model"]]
            for title, key in [("Coverage", "coverage"), ("Below P05", "below_p05"), ("High Drift Below P05", "high_drift_below"), ("Log RMSE", "log_rmse")]:
                check(row[title], source[key], title)
        if desktop["multiple_scenarios"] != [{"Savings": None, "Cost": None}]:
            raise ValueError("Multiple scenarios must return blank costs/savings")
        evidence["desktop_grain_values_reconciled"] = comparisons
        evidence["scenario_multiplication_guard_passed"] = True
        evidence["desktop_cost_sum_comparison_unit"] = "USD millions; absolute tolerance 1e-9 in displayed unit"
    out = Path("docs/evidence/powerbi_contract.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print(json.dumps({k:v for k,v in evidence.items() if k != "schema_validated_files"}, indent=2))


if __name__ == "__main__":
    main()
