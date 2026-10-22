# Power BI connection and Gold data contract

Analytics and simulation Gold are **deployed and verified as of 2026-10-10**: 520 route/month/scenario rows, 8,198 operated synthetic flights, 29,584,950 gallons, three hedge marks, 30 sensitivity cells and five 100K-path risk scenarios. Costs reconcile with independent local calculations; invalid-position SQL checks pass. Connection values:

| Setting | Value |
| --- | --- |
| Server hostname | `dbc-236f6036-39b4.cloud.databricks.com` |
| HTTP path | `/sql/1.0/warehouses/e4f1304cb2d303ea` |
| Catalog | `workspace` |
| Reporting schema | `jet_fuel_gold` |
| Authentication | Databricks connector OAuth, or Azure Databricks connector with workspace PAT as supported by the selected connector |
| Initial mode | Import; free warehouse quotas make repeated DirectQuery queries less predictable |

Use Power BI Desktop's **Databricks** connector for AWS OAuth; select the matching connector/auth flow your Desktop version offers. The [Microsoft connector documentation](https://learn.microsoft.com/en-us/power-query/connectors/databricks) distinguishes AWS OAuth from PAT-based connector choices. The [Databricks guide](https://docs.databricks.com/aws/en/partners/bi/power-bi/) covers connection settings. Never put a token inside Power Query source or the repository; enter credentials in Power BI's credential dialog.

## Initial Gold tables and views

| Object | Grain and meaning |
| --- | --- |
| `route_fuel_costs` | Route × calendar month × hedge scenario; synthetic operated flights with actual historical EIA marks |
| `dim_route` | One synthetic route; airport, aircraft, burn, schedule and validity metadata |
| `dim_month` | One calendar month; join `cost_month` to route fact |
| `dim_hedge_scenario` | Five hypothetical hedge ratios and unique `scenario_id` |
| `dim_date` | Calendar date, most recent prior EIA observation/age, actual spot price and descriptive volatility |
| `v_route_burn` | Scenario-zero monthly operations/costs for summing volumes without scenario duplication |
| `v_price_correlation` | Actual daily jet/WTI prices, crack spread, 90-day correlation and volatility with gap flags |
| `v_hedge_mtm` | Synthetic open positions, matching-underlying spot proxy and long-futures P&L (positive is gain) |
| `v_hedge_sensitivity` | 30 combinations: five ratios × six price shocks; reference 1.5B gallon carrier, not fixture fleet |
| `v_fleet_summary` | Annualized synthetic schedule by aircraft type; `fleet_share_pct` is 0–100 |
| `analytics_quality` | Actual reconciled counts, source date and publication IDs |
| `pipeline_runs` | Gold publish status; newest row must be SUCCESS |
| `v_risk_metrics` | All simulated runs/ratios; initially empty until Phase 3 |

Use single-direction one-to-many relationships from `dim_route.route_id`, `dim_month.cost_month`, and `dim_hedge_scenario.scenario_id` to `route_fuel_costs`. Do not connect daily `dim_date.cost_month` as a unique monthly key; it repeats for every day. Set the scenario slicer to single select. Flight counts, gallons and unhedged costs repeat across scenarios: use `v_route_burn` for scenario-independent totals or a measure that requires one selected scenario. Do not sum risk percentiles across ratios or runs.

Historical route marks use the last available observation **at or before each flight date**. `spot_price_gal` on the monthly fact is a gallon-weighted monthly purchase price, not latest spot. Hedge cost is a hypothetical forward fixed at the operations-window start; it is not a real airline hedge program. `hedge_pnl_usd = hedged − unhedged` is negative for savings; `hedge_savings_usd` has the opposite sign. Position MTM uses positive long-futures gains and is a spot proxy, not a discounted forward valuation.

## Readiness and refresh

Before refresh, require newest `jet_fuel_silver.pipeline_runs` and `jet_fuel_gold.pipeline_runs` entries to be SUCCESS; Gold `analytics_quality.pipeline_run_id` must match latest Gold, and `source_pipeline_run_id` must match latest Silver. A new Silver publication requires Gold rebuild. Run `scripts/verify_phase2.py` for a complete reconciliation before handing off changed data. Refresh order: ingestion/Silver → operations/Gold → simulation risk → Power BI Import refresh. Never treat an old quality table as evidence for an interrupted newer run.
## Verified simulation Gold — Phase 3

The 100,000-path serverless run `386315486361989` passed independent NumPy/SQL reconciliation. Simulation ID `e35d376c-398b-4bea-8823-4f085f036fd9`, MLflow `4c5cf414a2af4078a5ea0aa8c66186ef`: 500,000 cost rows, five hedge ratios, 53 fan steps including S0, 47.92 seconds measured simulation/tracking work (job startup excluded).

Import `latest_simulation_run` as a one-row run selector; filter `risk_metrics`, `price_fan`, `cost_histogram`, and `simulation_quality` to that ID. These tables retain history. Check that `source_pipeline_run_id` matches current successful Silver publication before refreshing analysis. A prior run can remain available while a new one fails; it must be labeled stale if source changed.

`risk_metrics` grain: simulation ID × hedge ratio. `price_fan`: run × weekly step. `cost_histogram`: run × ratio × occupied bin; sum `path_count`, not bin boundaries. `simulation_quality`: one row per completed candidate run. Import aggregate Gold rather than all raw paths. Incremental VaR is P95 minus mean; CVaR is the mean at/above absolute P95. Both are USD billions, not percentages. The 80% hedge has exactly 80% incremental VaR reduction under this common-path affine model; this identity does not establish a real-world optimal hedge.

## Phase 5 project and model

Open `powerbi/JetFuelHedgeRisk/JetFuelHedgeRisk.pbip`. It references the adjacent `JetFuelHedgeRisk.SemanticModel` (TMDL) and `JetFuelHedgeRisk.Report` (PBIR). Rebuild source with `uv run python scripts/build_powerbi.py`; validate JSON/bindings with `uv run python scripts/verify_powerbi_contract.py`. Theme: `JetFuelHedgeRisk.Report/StaticResources/RegisteredResources/jet_fuel_theme.json`. Published schemas and a real Microsoft TOM serializer check are independent of Desktop rendering.

The credential-free GoldTable function remains the sole Databricks data-access path. Every fact imports a guarded current view; existing MTM/sensitivity queries are additionally gated on analytics readiness. Import mode only. Never add a credential to M, TMDL, PBIR or a screenshot. `_Measures` contains folders Headlines, Market, Proxy, Backtest, Simulation, Scenario and Status. The old `powerbi/measures.dax` meanings are retained, including scenario-safe gallons/unhedged totals and nonadditive SELECTEDVALUE risk metrics. Daily facts relate to dim_date; route facts relate to route/month/scenario, risk to scenario ratio. All relationships filter dimension→fact in one direction. Windows/calibrations/backtest/tails stay disconnected.

| Additional guarded view | Grain / purpose |
| --- | --- |
| market_decomposition_current; alias v_market_decomposition | Price date; converted crude, crack and full-sample price ranks |
| proxy_return_correlation_current | Price date; inclusive 90-day calendar RANGE log-return correlations and distinctly named legacy price-level correlation |
| proxy_effectiveness_annual_current | Year or ALL × proxy; paired weekly correlation/R²/beta and sample count |
| hedge_backtest_windows_current | Weekly start × ratio; 52 future purchases excluding S0, savings/rank and reference-carrier overrun |
| calibration_history_current | Week ending; unchanged production EWM calibration and full-history ranks |
| forecast_backtest_current | Window start × drift model; 10K-path average-price bands and realized outcomes |
| return_tail_frequency_current | Threshold 2/3/4; observed/normal tail frequencies, skew and excess kurtosis |
| insights_runs; insights_quality | Append-only publication registry and seven positive per-table count expectations |

All facts carry insight/source IDs, created timestamp and a source flag. Historical prices/validation are not synthetic operations. Reference-carrier costs are assumptions about volume; route/position views are explicitly synthetic fixtures. The full-history calibration chart has 822 calibrations, while only 770 can have a complete realized year; see DECISIONS #21 for the disclosed departure from the supplied completed-window benchmark.

The five 1280×720 pages contain 15 narrative units (some contain two chart/table panels):

1. What drove the jet fuel spike: monthly crude/crack stack and exact daily bridge.
2. Which instrument tracks jet: price-level vs return correlation, annual proxy R²/beta, trailing-year moves and synthetic linear marks.
3. Did hedging pay: complete rolling windows, reference-carrier insurance frontier, scenario-selected synthetic route counterfactual and B767 concentration.
4. How much to trust GBM: calibration extremes, walk-forward band coverage/below-P05 regimes, actual fan bands and observed fat tails.
5. Read model hedge decisions correctly: 0%/80% overlaid histogram/tail rules, model-vs-history mean change and signed sensitivity heatmap. VaR-reduction identity is a note, never a chart.

Three layered units use the certified Deneb AppSource visual. Desktop must allow the certified visual to load. Their exact embedded Vega-Lite specs are schema-validated and can be compiled/rendered with `scripts/render_powerbi_specs.py`; those previews are **not Desktop screenshots**. All headline/subtitle numbers and alt text bind to DAX measures over current views. Titles use signed changes or comparator branches, so refresh cannot silently preserve a reversed empirical claim. `powerbi/tests/headlines.dax` and `headline_numbers.dax` are query-view tests; `headline_numbers.sql` checks the warehouse equivalents against independent Python evidence with `scripts/verify_powerbi_contract.py --live`. SQL checks do not execute DAX.

## Refresh and verification sequence

Managed refresh order is **capture → Silver → Phase 5 insights → operations fixture → analytics Gold → production risk → reporting contract → Power BI Import**. One concurrent managed run; do not start manual publishers concurrently. Standalone initial deployment uses `scripts/deploy_phase5.py`, waits for the printed job SUCCESS, then `scripts/verify_phase5.py`. The managed job deployer publishes the next sequential task with a content-addressed notebook path.

Require analytics_ready, risk_ready **and insights_ready** true before Import. Guarded views return empty when source/registry/counts disagree; do not replace blanks with zero. Separate Import queries are not transactional, so refresh only after complete job success. The header displays source price date, simulation completion, readiness and run ID in the tooltip. Historical EIA observation lag is visible; it is not erased by a successful pipeline timestamp.

```powershell
uv run python scripts/deploy_phase5.py
# Wait for the printed job to reach SUCCESS.
uv run python scripts/verify_phase5.py
uv run python scripts/verify_reporting.py
uv run python scripts/verify_powerbi_contract.py --live
uv run python scripts/render_insight_storyboard.py
uv run python scripts/render_powerbi_specs.py
```

Offline development is explicit: `scripts/build_local_insights.py`, `scripts/verify_phase5.py --offline`, then both renderers with `--offline`. Evidence and plot badges clearly distinguish these from live Gold. Independent MC verification caches are keyed by complete calibration/window input plus oracle function source; changed inputs require new work.

## Desktop handoff and native validation checklist

Power BI Desktop Store version 2.159.883.0 is installed. Native control approval timed out before project open during the initial attempt. **No Desktop report open, authentication, Import refresh, DAX execution or five-page screenshots have been claimed.** Follow these steps if native access remains unavailable:

1. Finish live publication and require all three readiness flags; run the verifiers above.
2. Open `powerbi/JetFuelHedgeRisk/JetFuelHedgeRisk.pbip` in Desktop. Enable supported project/developer settings if your installation requests them. Resolve any parser error before continuing; do not discard model source.
3. In Databricks' credential dialog authenticate with your existing OAuth or supported PAT flow. You enter credentials yourself; they never go into repository files. Approve the certified Deneb visual according to your organization's existing policy, if prompted.
4. Refresh Import only after the whole managed refresh succeeds. Confirm all headers show the current `price_as_of`, simulation completion and Ready. Empty facts must remain unavailable, not zero.
5. On page 3 select exactly one scenario (80% for the default comparison), then check route monthly totals, route savings and gallons; multi-selection must return blank for scenario-dependent cost/saving.
6. Run both headline DAX query-view files and the grain queries in `powerbi/tests/`. Compare their numeric output with live phase5_verification.json and the SQL contract. Record actual DAX execution evidence separately; TOM parsing alone does not evaluate measures.
7. Inspect all five 16:9 pages: no clipped titles, correct colors/labels/markers, reference lines and fan bands, zero-centred matrix colors, no totals of nonadditive quantities. Inspect all layered visual tooltips. Check unavailable-state behavior using a copy of the model or a held Import snapshot, not destructive production mutations.
8. Save screenshots as `docs/evidence/powerbi/page-01.png` through `page-05.png` and record Desktop build, source/run IDs, actual refresh time and DAX test results. Only then mark Desktop validation complete. The matplotlib storyboards and compiled-spec previews must not be put in this directory as substitutes.
