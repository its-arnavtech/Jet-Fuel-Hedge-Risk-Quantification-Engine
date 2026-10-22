"""Compile the exact layered PBIR specifications against extracts; not Desktop evidence."""

import argparse
import json
import math
from pathlib import Path

import pandas as pd
import vl_convert as vlc

from build_powerbi import REPORT


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    folder = Path("artifacts/insights_local" if args.offline else "artifacts/insights_gold")
    evidence = json.loads(Path("docs/evidence/phase5_offline_verification.json" if args.offline else "docs/evidence/phase5_verification.json").read_text(encoding="utf-8"))
    f = evidence["findings"]
    h = pd.read_csv(folder/"calibration_history.csv")
    h = h.rename(columns={"mu": "MU", "sigma": "SIGMA"})
    h["Mu IQR Low"], h["Mu IQR High"] = h.MU.quantile(.25), h.MU.quantile(.75)
    fan = pd.read_csv("artifacts/price_fan.csv") if args.offline else pd.read_csv(folder/"price_fan.csv")
    for prefix, label in [("05", "P05"), ("25", "P25"), ("50", "Median"), ("75", "P75"), ("95", "P95")]:
        fan["Fan "+label] = fan["p"+prefix+"_price_gal"]
    fan["Latest Jet"] = f["F10"]["spot_run_rate_b"]/1.5
    fan["Forward Price"] = fan["Latest Jet"]*math.exp(.04)
    fan["Historical P95 Price"] = fan["Latest Jet"]*(1+f["F10"]["historical_p95_move"])
    hist = pd.read_csv(folder/"cost_histogram.csv").rename(columns={"path_count": "Histogram Paths"})
    risk = pd.read_csv("artifacts/risk_metrics.csv") if args.offline else pd.read_csv(folder/"risk_metrics.csv")
    hist["Spot Run Rate B"] = f["F10"]["spot_run_rate_b"]
    prior_jet = f["F10"]["spot_run_rate_b"]/1.5-f["F1"]["jet_change"]
    current_jet = f["F10"]["spot_run_rate_b"]/1.5
    wti_end = prior_jet+f["F1"]["wti_change"]
    bridge = pd.DataFrame({"Step": ["Start", "WTI change", "Crack change", "Latest"], "Ordinal": [0, 1, 2, 3],
        "Bridge Low": [0, min(prior_jet, wti_end), min(wti_end, current_jet), 0],
        "Bridge High": [prior_jet, max(prior_jet, wti_end), max(wti_end, current_jet), current_jet],
        "Bridge Label": [f"${prior_jet:.3f}", f"${f['F1']['wti_change']:+.3f}", f"${f['F1']['crack_change']:+.3f}", f"${current_jet:.3f}"],
        "Bridge Color": ["#1F4E79", "#B85C38", "#E0A100", "#1F4E79"]})
    moves = pd.DataFrame({"Instrument": ["Jet", "HO", "WTI"], "Change Per Gallon": [f["F4"][name] for name in ["jet_change", "ho_change", "wti_change"]], "Change Jet": f["F4"]["jet_change"]})
    backtest = pd.read_csv(folder/"hedge_backtest_windows.csv")
    savings = backtest.loc[backtest.hedge_ratio.eq(0)].rename(columns={"savings_per_gal": "Window Savings"})
    frontier = backtest.groupby("hedge_ratio").budget_overrun_b.agg(**{"Mean Overrun B": "mean", "P95 Overrun B": lambda x: x.quantile(.95)}).reset_index()
    matrix = pd.read_csv(folder/"hedge_sensitivity.csv")
    matrix["Sensitivity Difference B"] = matrix.hedged_cost_b-matrix.unhedged_cost_b
    for ratio in [0, 80]:
        row = risk[risk.hedge_ratio.eq(ratio/100)].iloc[0]
        for name, col in [("Mean Cost B", "mean_cost_b"), ("P95 Cost B", "p95_cost_b"), ("CVaR95 B", "cvar_95_b")]:
            hist[name+" "+str(ratio)] = row[col]
    out = Path("dashboard/plots/insights/pbir_previews")
    out.mkdir(parents=True, exist_ok=True)
    previews = [("1_2", bridge, 1), ("2_3", moves, 2), ("3_1", savings, 3), ("3_2", frontier, 3), ("4_1", h, 4), ("4_3", fan, 4), ("5_1", hist, 5), ("5_3", matrix, 5)]
    for number, frame, page in previews:
        frame["Readiness"] = "Ready"
        obj = json.loads((REPORT/f"definition/pages/page{page}/visuals/v{number}/visual.json").read_text(encoding="utf-8"))
        raw = obj["visual"]["objects"]["vega"][0]["properties"]["jsonSpec"]["expr"]["Literal"]["Value"]
        spec = json.loads(raw[1:-1].replace("''", "'"))
        spec["data"]["values"] = json.loads(frame.to_json(orient="records", date_format="iso"))
        spec["width"], spec["height"] = 1000, 470
        spec["title"] = "PBIR SPECIFICATION PREVIEW — "+("offline extracts" if args.offline else "verified Gold extracts")+"; not a Desktop screenshot"
        (out/(number+".png")).write_bytes(vlc.vegalite_to_png(spec, scale=1.2))
    print(f"Compiled and rendered all {len(previews)} layered PBIR specifications")


if __name__ == "__main__":
    main()
