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

## Guarded Import starter and report layout

Prefer `route_fuel_costs_current`, `risk_metrics_current`, `price_fan_current`, `cost_histogram_current` plus `reporting_readiness`. The views fail closed when publication/source/quality IDs do not agree. Before refreshing Import, query readiness and require both flags true; an empty view indicates unavailable data, not zero cost/risk. Power BI imports multiple tables separately, so schedule Import after the full job succeeds and avoid concurrent manual publishers. Source data can lag today's date; display `price_as_of` prominently.

1. Create a blank query, paste `powerbi/GoldTable.pq` in Advanced Editor, and name it `GoldTable`. It uses the documented AWS OAuth entry point `DatabricksMultiCloud.Catalogs`; authenticate through the connector dialog. For PAT-based access, use the Azure Databricks connector's generated source and substitute that source in the function. Do not embed credentials in M.
2. Add queries such as `= GoldTable("risk_metrics_current")`. Import the current facts, readiness and `dim_route`, `dim_month`, `dim_hedge_scenario`. Rename the route fact **Route Costs**, risk fact **Risk Metrics**, and scenario dimension **Hedge Scenario** to match the DAX starter.
3. Connect dimensions one-to-many, single direction. Scenario ID relates to route fact. For risk, relate `Hedge Scenario.hedge_ratio` to `Risk Metrics.hedge_ratio` (unique in both current tables); keep filtering from dimension to fact. Do not create bidirectional fact-to-fact relationships.
4. Add measures from `powerbi/measures.dax` individually. Use a single-select scenario slicer. Mean/P95/VaR/CVaR return blank when several scenarios are selected; do not sum percentiles. Independent gallons/unhedged totals explicitly remove scenario filters to avoid fivefold duplication.
5. Page 1: source date/readiness cards, historical price/correlation trend, route costs and MTM table. Page 2: mean/P95/VaR/CVaR cards, coverage comparison, fan lines/bands and histogram. Page 3: sensitivity matrix (shock × coverage), synthetic fleet mix and assumptions text.

The Power Query source shape and DAX column names were checked against official documentation/live schemas. Power BI Desktop parsing, authentication and report rendering have not been executed by the agent; connect/import in Desktop as the handoff validation. The published Databricks definition and dataset queries are separately verified.

