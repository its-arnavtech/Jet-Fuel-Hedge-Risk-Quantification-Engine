"""Render the 15 evidence units from verified extracts; offline mode is conspicuous."""

import argparse
import json
from pathlib import Path
import textwrap

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.colors import TwoSlopeNorm
import numpy as np
import pandas as pd

COLORS = ["#1F4E79", "#B85C38", "#2E8B57", "#7A6C9E", "#E0A100"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    folder = Path("artifacts/insights_local" if args.offline else "artifacts/insights_gold")
    evidence = json.loads(Path("docs/evidence/phase5_offline_verification.json" if args.offline else "docs/evidence/phase5_verification.json").read_text(encoding="utf-8"))
    if not args.offline and not evidence["live_verified"]:
        raise ValueError("Gold storyboard requires live verification")
    numbers = evidence["findings"]
    out = Path("dashboard/plots/insights")
    out.mkdir(parents=True, exist_ok=True)
    def load(name):
        frame = pd.read_csv(folder/(name+".csv"))
        for col in ["price_date", "week_ending", "window_start", "cost_month"]:
            if col in frame:
                frame[col] = pd.to_datetime(frame[col])
        return frame
    market, corr, annual, bt, history, forecast, tails = [load(n) for n in [
        "market_decomposition", "proxy_return_correlation", "proxy_effectiveness_annual",
        "hedge_backtest_windows", "calibration_history", "forecast_backtest", "return_tail_frequency"]]
    routes = load("route_fuel_costs")
    risk = pd.read_csv("artifacts/risk_metrics.csv") if args.offline else load("risk_metrics")
    fan = pd.read_csv("artifacts/price_fan.csv") if args.offline else load("price_fan")
    hist = load("cost_histogram")
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False,
                         "axes.grid": True, "grid.alpha": .16, "axes.titlelocation": "left",
                         "text.parse_math": False})
    outputs = []
    def start(title, badge="Actual EIA prices", subplots=1):
        fig, axes = plt.subplots(1, subplots, figsize=(12.8, 7.2), layout="constrained")
        fig.suptitle(textwrap.fill(title, 90), fontsize=15, fontweight="bold", x=.025, ha="left")
        label = "OFFLINE DEVELOPMENT — NOT LIVE GOLD | " if args.offline else "Verified live Gold | "
        fig.supxlabel(label+"Price as of "+evidence["price_as_of"][:10]+" | "+badge, fontsize=9)
        return fig, axes
    def finish(fig, number):
        file = out/(number.replace(".", "_")+".png")
        fig.savefig(file, dpi=100)
        plt.close(fig)
        outputs.append(str(file))
    f = numbers["F1"]
    fig, ax = start(f"Crack spread contributed {f['crack_share']:.1%} of jet’s {f['jet_change']:+.3f} $/gal trailing-year change")
    monthly = market.set_index("price_date").resample("MS").mean(numeric_only=True)
    ax.stackplot(monthly.index, monthly.wti_gal, monthly.crack_spread, colors=[COLORS[1], COLORS[4]], labels=["WTI-equivalent", "Jet–WTI crack"])
    ax.axhline(f["historical_crack_mean"], color="#555555", ls="--", label="Prior-years mean crack (component benchmark)")
    ax.annotate(f"Latest monthly jet ${monthly.jet_fuel_gal.iloc[-1]:.3f}/gal", (monthly.index[-1], monthly.jet_fuel_gal.iloc[-1]), xytext=(-210, 20), textcoords="offset points", arrowprops={"arrowstyle":"->"})
    ax.set(ylabel="$/gal", xlim=(monthly.index[0], monthly.index[-1]+pd.Timedelta(days=150)))
    ax.legend(loc="upper left")
    finish(fig, "1.1")
    current = market.iloc[-1]
    prior = market[market.price_date <= current.price_date-pd.DateOffset(years=1)].iloc[-1]
    fig, ax = start(f"Crack ${f['crack']:.3f}/gal is {f['crack_multiple']:.1f}× its prior-years mean; jet ranks at {f['jet_rank']:.1%} of full history")
    heights = [prior.jet_fuel_gal, f["wti_change"], f["crack_change"], current.jet_fuel_gal]
    bottoms = [0, prior.jet_fuel_gal, prior.jet_fuel_gal+f["wti_change"], 0]
    ax.bar(["Jet a year ago", "WTI change", "Crack change", "Latest jet"], heights, bottom=bottoms, color=[COLORS[0], COLORS[1], COLORS[4], COLORS[0]])
    for i, (height, bottom) in enumerate(zip(heights, bottoms)):
        ax.text(i, height+bottom+.06, f"${height:+.3f}" if i in [1, 2] else f"${height:.3f}", ha="center")
    ax.set(ylabel="$/gal", ylim=(0, max(bottoms+heights)+1))
    finish(fig, "1.2")
    f = numbers["F2"]
    fig, ax = start(f"Price levels: WTI {f['price_level']:.2f}; daily returns: WTI {f['returns_wti']:.2f}, heating oil {f['returns_ho']:.2f}")
    last3 = corr[corr.price_date >= current.price_date-pd.DateOffset(years=3)]
    for col, label, color, style in [("price_level_corr_jet_wti_90d", "Price-level, misleading", "#777777", "--"), ("ret_corr_jet_wti_90d", "Jet–WTI log returns", COLORS[1], "-"), ("ret_corr_jet_ho_90d", "Jet–HO log returns", COLORS[2], "-")]:
        ax.plot(last3.price_date, last3[col], label=label, color=color, ls=style)
    ax.set(ylabel="90-calendar-day paired correlation", ylim=(-1, 1.05))
    ax.legend(loc="lower left")
    finish(fig, "2.1")
    f = numbers["F3"]
    fig, ax = start(f"Heating oil out-tracked WTI in {f['ho_wins']} of {f['years']} years; WTI cleared R² = 0.80 in {f['wti_effective']}")
    p = annual[annual.year.astype(str).ne("ALL")].pivot(index="year", columns="proxy", values="r2")
    x = np.arange(len(p))
    for i, (proxy, color, hatch) in enumerate([("HO", COLORS[2], ""), ("WTI", COLORS[1], "//"), ("BRENT", COLORS[3], "..")]):
        ax.bar(x+(i-1)*.26, p[proxy], .25, label=proxy, color=color, hatch=hatch)
    ax.axhline(.8, color="#222222", ls="--", label="Highly-effective benchmark")
    ax.set(xticks=x, xticklabels=p.index, ylabel="Weekly-return R²", ylim=(0, 1.05))
    ax.tick_params(axis="x", labelrotation=45)
    ax.legend(loc="lower left", ncols=4)
    finish(fig, "2.2")
    f = numbers["F4"]
    fig, axes = start(f"WTI changed ${f['wti_change']:.3f} vs jet ${f['jet_change']:.3f}/gal; heating oil ${f['ho_change']:.3f}", "Actual EIA prices; position marks: Synthetic fixture", 2)
    axes[0].barh(["Jet", "Heating oil", "WTI-equivalent"], [f["jet_change"], f["ho_change"], f["wti_change"]], color=[COLORS[0], COLORS[2], COLORS[1]])
    axes[0].axvline(f["jet_change"], ls="--", color=COLORS[0], label="Jet reference")
    axes[0].set(xlabel="Trailing-year change, $/gal")
    axes[0].legend()
    axes[1].axis("off")
    marks = [("JET_FUEL", 2.8, current.jet_fuel_gal), ("WTI", 1.7, current.wti_gal), ("HEATING_OIL", 2.6, current.heating_oil_gal)]
    table = axes[1].table(cellText=[[name, f"{locked:.3f}", f"{mark:.3f}", f"{mark-locked:+.3f}"] for name, locked, mark in marks], colLabels=["Underlying", "Locked", "Mark", "P&L/gal"], loc="center", cellLoc="left")
    table.auto_set_font_size(False)
    table.set_fontsize(9)
    table.scale(1, 1.8)
    axes[1].set_title("Synthetic fixture | Linear spot proxies", fontsize=11)
    finish(fig, "2.3")
    f, latest = numbers["F5"], numbers["F6"]
    zero = bt[bt.hedge_ratio.eq(0)].copy()
    fig, ax = start(f"One-year forward beat spot in {f['win_rate']:.1%} of {f['windows']} windows; mean {f['mean_savings']:+.3f} $/gal")
    ax.bar(zero.window_start, zero.savings_per_gal, width=7, color=np.where(zero.savings_per_gal > 0, COLORS[0], COLORS[1]))
    ax.axhline(0, color="#111111", lw=.8)
    last = zero.iloc[-1]
    ax.scatter([last.window_start], [last.savings_per_gal], color=COLORS[4], edgecolor="#111111", marker="D", zorder=4, s=55, label=f"Latest: {latest['latest_rank']:.1%} rank")
    ax.plot([], [], color=COLORS[0], lw=6, label="Hedge won")
    ax.plot([], [], color=COLORS[1], lw=6, label="Hedge lost")
    ax.set(ylabel="Realized average minus forward, $/gal")
    ax.legend(loc="lower right")
    finish(fig, "3.1")
    fig, ax = start(f"80% cover moved P95 overrun ${f['p95_unhedged']:.2f}B → ${f['p95_80']:.2f}B; expected cost change ${f['expected_hedge_cost_b']:+.2f}B/yr", "Reference carrier, 1.5B gal/yr")
    for hratio, group in bt.groupby("hedge_ratio"):
        mean, p95 = group.budget_overrun_b.mean(), group.budget_overrun_b.quantile(.95)
        ax.scatter(mean, p95, color=plt.cm.Blues(.35+.65*hratio/.8), s=140, edgecolors="#222222")
        ax.annotate(f"{hratio:.0%}", (mean, p95), xytext=(8, 6), textcoords="offset points")
    ax.set(xlabel="Mean budget overrun vs S0, $B", ylabel="P95 budget overrun vs S0, $B")
    ax.margins(.25)
    finish(fig, "3.2")
    f = numbers["F12"]
    fig, axes = start(f"Synthetic schedule: 80% cover saved ${f['route_savings_80_m']:.2f}M; B767s use {f['b767_gallon_share']:.1%} of scheduled gallons on {f['b767_departures']} daily departures", "Synthetic fixture | Latest complete historical window rank "+f"{latest['latest_rank']:.1%}", 2)
    route8 = routes[routes.hedge_ratio.eq(.8)]
    monthly = route8.groupby("cost_month")[["unhedged_cost_usd", "hedged_cost_usd"]].sum()/1e6
    axes[0].bar(monthly.index, monthly.hedged_cost_usd, width=20, color=COLORS[0], label="80% hedged")
    axes[0].plot(monthly.index, monthly.unhedged_cost_usd, color=COLORS[1], marker="o", label="Unhedged")
    axes[0].set(ylabel="Monthly cost, $M")
    axes[0].xaxis.set_major_locator(mdates.MonthLocator(interval=3))
    axes[0].xaxis.set_major_formatter(mdates.DateFormatter("%b %y"))
    axes[0].legend()
    byroute = route8.groupby(["route_id", "aircraft_type"]).hedge_savings_usd.sum().sort_values()/1e6
    axes[1].barh([r[0] for r in byroute.index], byroute, color=[COLORS[4] if r[1] == "B767" else COLORS[0] for r in byroute.index])
    axes[1].set(xlabel="Hedge savings, $M")
    finish(fig, "3.3")
    f = numbers["F7"]
    fig, ax = start(f"Current EWM drift {f['mu']:.1%}/yr ranks at {f['mu_rank']:.1%} of {f['calibrations']} calibrations; median {f['median_mu']:.1%}")
    q25, q75 = history.mu.quantile([.25, .75])
    ax.axhspan(q25, q75, color=COLORS[0], alpha=.12, label="μ historical interquartile range")
    ax.plot(history.week_ending, history.mu, color=COLORS[0], label="μ, left")
    right = ax.twinx()
    right.plot(history.week_ending, history.sigma, color=COLORS[1], ls="--", label="σ, right")
    ax.scatter(history.week_ending.iloc[-1], history.mu.iloc[-1], marker="D", color=COLORS[0], zorder=4)
    ax.set(ylabel="Annual drift μ")
    right.set(ylabel="Annual volatility σ")
    ax.legend(loc="upper left")
    right.legend(loc="upper right")
    finish(fig, "4.1")
    f = numbers["F8"]
    fig, axes = start(f"EWM band covered {f['EWM']['coverage']:.1%} (nominal 90%); high-drift outcomes below P05: {f['EWM']['high_drift_below']:.1%}", "Actual EIA walk-forward outcomes; GBM is not a forecast", 2)
    models = ["EWM", "MARTINGALE", "RISK_FREE"]
    bars = axes[0].bar(models, [f[m]["coverage"] for m in models], color=COLORS[:3])
    axes[0].bar_label(bars, labels=[f"{f[m]['coverage']:.1%}" for m in models], padding=3)
    axes[0].axhline(.9, ls="--", color="#222222", label="Nominal 90%")
    axes[0].set(ylabel="Realized P05–P95 coverage", ylim=(0, 1))
    axes[0].legend(loc="lower right")
    x = np.arange(3)
    for offset, key, label, color in [(-.2, "below_p05", "Overall below P05", COLORS[0]), (.2, "high_drift_below", "μ > 0.5 below P05", COLORS[1])]:
        bars = axes[1].bar(x+offset, [f[m][key] for m in models], .38, color=color, label=label)
        axes[1].bar_label(bars, labels=[f"{f[m][key]:.1%}" for m in models], padding=3, fontsize=9)
    axes[1].set(xticks=x, xticklabels=models, ylabel="Share of outcomes", ylim=(0, .55))
    axes[1].legend(loc="upper right")
    finish(fig, "4.2")
    f = numbers["F10"]
    fig, ax = start(f"Terminal median ${f['terminal_median']:.3f}/gal ({f['terminal_median']/current.jet_fuel_gal:.1f}× today); historical P95 average-price move {f['historical_p95_move']:+.1%}", "Reference carrier, 1.5B gal/yr | Extrapolation of trailing-year drift, not a forecast")
    ax.fill_between(fan.step, fan.p05_price_gal, fan.p95_price_gal, color=COLORS[0], alpha=.15, label="P05–P95")
    ax.fill_between(fan.step, fan.p25_price_gal, fan.p75_price_gal, color=COLORS[0], alpha=.3, label="P25–P75")
    ax.plot(fan.step, fan.p50_price_gal, color=COLORS[0], label="Median")
    ax.axhline(current.jet_fuel_gal, ls=":", color="#111111", label="S0")
    ax.axhline(current.jet_fuel_gal*np.exp(.04), ls="-.", color=COLORS[1], label="Forward F")
    ax.axhline(current.jet_fuel_gal*(1+f["historical_p95_move"]), ls="--", color=COLORS[2], label="Historical P95 average/S0 benchmark")
    ax.set(xlabel="Future week", ylabel="$/gal")
    ax.legend(loc="upper left")
    finish(fig, "4.3")
    f = numbers["F9"]
    fig, ax = start(f"3-sigma moves occur {f['ratio']:.1f}× the normal-implied rate; excess kurtosis {f['excess_kurtosis']:.1f}")
    x = np.arange(3)
    ax.bar(x-.2, tails.observed_share*100, .38, color=COLORS[0], label="Observed weekly jet returns")
    ax.bar(x+.2, tails.normal_share*100, .38, color=COLORS[1], hatch="//", label="Normal-implied")
    for i, row in tails.iterrows():
        ax.text(i, max(row.observed_share, row.normal_share)*100+.12, f"{row.ratio:.1f}×", ha="center", fontweight="bold")
    ax.set(xticks=x, xticklabels=["|z| > 2", "|z| > 3", "|z| > 4"], ylabel="Share of weeks, %", ylim=(0, 6))
    ax.legend(loc="upper right")
    finish(fig, "4.4")
    f = numbers["F10"]
    fig, ax = start(f"Unhedged mean ${f['mean_cost_b']:.2f}B ({f['mean_vs_spot']:+.1%} vs spot run-rate); CVaR95 ${f['cvar_unhedged']:.2f}B → ${f['cvar_80']:.2f}B at 80%", "Reference carrier, 1.5B gal/yr | GBM, not a forecast")
    for hratio, color in [(0., COLORS[1]), (.8, COLORS[0])]:
        group = hist[hist.hedge_ratio.eq(hratio)]
        ax.bar(group.bin_lower_cost_b, group.path_count, width=group.bin_upper_cost_b-group.bin_lower_cost_b, align="edge", alpha=.4, color=color, edgecolor=color, label=f"{hratio:.0%} cover")
        row = risk[risk.hedge_ratio.eq(hratio)].iloc[0]
        for metric, style in [("mean_cost_b", "-"), ("p95_cost_b", "--"), ("cvar_95_b", ":")]:
            ax.axvline(row[metric], color=color, ls=style, label=f"{hratio:.0%} {metric.replace('_cost_b','').replace('_95_b','95')}: {row[metric]:.2f}")
    ax.axvline(f["spot_run_rate_b"], color="#222222", ls="-.", label=f"Spot run-rate {f['spot_run_rate_b']:.2f}")
    ax.set(xlabel="Annual purchase cost, $B", ylabel="Paths per bin", xlim=(0, max(risk.cvar_95_b)*1.35))
    ax.legend(loc="upper right", fontsize=9, ncols=2)
    finish(fig, "5.1")
    fig, ax = start(f"80% cover changes mean cost: model ${f['simulation_hedge_change_b']:+.2f}B; history ${f['historical_hedge_change_b']:+.2f}B", "Reference carrier, 1.5B gal/yr | VaR reduction equals coverage by construction")
    vals = [f["simulation_hedge_change_b"], f["historical_hedge_change_b"]]
    bars = ax.barh(["GBM simulation", "Historical rolling windows"], vals, color=[COLORS[0] if v < 0 else COLORS[1] for v in vals])
    ax.bar_label(bars, labels=[f"${v:+.2f}B" for v in vals], padding=8)
    ax.axvline(0, color="#222222")
    ax.margins(x=.2)
    ax.set(xlabel="80% minus 0% expected annual cost, $B", title="The model’s drift–carry gap determines its expected savings")
    finish(fig, "5.2")
    f = numbers["F11"]
    fig, ax = start(f"Hedge break-even {f['break_even']:.1%}; 80% cover at −30%: ${f['minus30_cost_b']:+.2f}B, at +50%: ${f['plus50_cost_b']:+.2f}B", "Reference carrier, 1.5B gal/yr")
    ratios, shocks = np.array([0., .2, .4, .6, .8]), np.array([-.3, -.15, 0, .15, .3, .5])
    values = 1.5*current.jet_fuel_gal*ratios[:, None]*(np.exp(.04)-(1+shocks[None, :]))
    limit = np.max(abs(values))
    ax.imshow(values, cmap="RdBu_r", norm=TwoSlopeNorm(0, -limit, limit), aspect="auto")
    for y in range(5):
        for x in range(6):
            ax.text(x, y, f"{values[y,x]:+.2f}", ha="center", va="center", color="white" if abs(values[y,x]) > limit*.55 else "#111111", fontsize=12)
    ax.set(xticks=np.arange(6), xticklabels=[f"{s:+.0%}" for s in shocks], yticks=np.arange(5), yticklabels=[f"{h:.0%}" for h in ratios], xlabel="Spot price shock", ylabel="Hedge ratio", title="Hedged − unhedged cost, $B | Blue = saving; red = additional cost")
    ax.grid(False)
    finish(fig, "5.3")
    (out/"provenance.json").write_text(json.dumps(dict(offline=args.offline, source=evidence["source"], price_as_of=evidence["price_as_of"], visual_files=outputs, desktop_screenshots=False), indent=2), encoding="utf-8")
    print(f"Rendered {len(outputs)} insight units from {'offline development' if args.offline else 'verified Gold'} extracts")


if __name__ == "__main__":
    main()
