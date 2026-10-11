# Power BI connection and Gold data contract

Initial Gold is **deployed and verified as of 2026-10-10**: 520 route/month/scenario rows, 8,198 operated synthetic flights, 29,584,950 gallons, three hedge marks, and 30 sensitivity cells. All costs reconcile with independent local calculations; invalid-position SQL checks pass. Simulated risk tables are delivered in Phase 3. Connection values:

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
