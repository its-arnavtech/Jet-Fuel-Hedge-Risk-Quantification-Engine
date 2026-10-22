# Jet fuel hedge engine implementation plan

Last updated: 2026-10-10 (America/Chicago).

Source: `pdd_airline_fuel_hedge_engine.docx`, v1.0, sections 1–10 and appendices A–B, read in full including all six SQL examples, schema definitions, equations, code, and environment instructions. No substantive footnotes, endnotes, or comments were present.

## Objective and delivery contract

Build a reproducible airline treasury analytics pipeline from EIA historical prices through Unity Catalog Bronze, Silver, and Gold Delta tables on **Databricks Free Edition**. Model a 1.5 billion gallon/year reference carrier, calibrate a GBM with exponentially weighted moments, simulate 100,000 weekly price paths, and compare 0%, 20%, 40%, 60%, and 80% futures hedges. Publish trustworthy costs and tail-risk distributions, route/fleet analytics, charts, and a Power BI connection guide. Notify the user as soon as deployed Gold data passes checks.

The PDD is a portfolio specification, not evidence for its company-specific claims. Do not repeat unsupported claims about airline hedging programs, current stacks, or employment signals as verified findings. Synthetic route/flight/position data must be labeled in tables, docs, and reports. Real historical prices must retain EIA provenance.

## Working rules and handoff

1. Read this plan, `CHANGELOG.md`, `docs/DECISIONS.md`, and the most recent `docs/audits/` report before continuing.
2. Update the changelog after meaningful work, checks, audit findings, blockers, and phase transitions. Include exact next actions and verification commands.
3. Finish a phase's implementation and checks; audit the **whole repository** (requirements, data correctness, math, SQL, security, compatibility, reproducibility, documentation).
4. Record actionable findings with reproduction, severity, expected behavior, fix, and validation. File them as GitHub issues in `its-arnavtech/Jet-Fuel-Hedge-Risk-Quantification-Engine`, store the real URLs, fix them, and verify again. Never fabricate an issue URL or mark unavailable integration checks passed.
5. Do not begin the next phase until the audit is complete and its findings are resolved. If GitHub access is unavailable, preserve ready-to-file findings and fixes locally, but leave the phase gate pending.
6. User preference: use descriptive feature/phase branch names, e.g. `phase-1-ingestion-silver`, and merge/push to `main` after the phase audit and fixes pass. Commit/push meaningful milestones while working. Never add credentials or private response payloads to Git, logs, exceptions, notebooks, or reports. Preserve the source DOCX.

## Phase 1 — Requirements, foundation, ingestion, and Silver

Status: **complete and audited**. Live deployment and idempotent replay succeeded; 19 tests and CI pass; issues #1–#5 resolved. Main merge recorded in changelog.

- [x] Read the entire PDD and establish requirements, phase gates, handoff docs, and a correction log.
- [x] Verify current Free Edition, serverless, authentication, and Power BI constraints against primary documentation.
- [x] Package and configuration, isolated local credential path, CI, unit tests, deterministic synthetic fixtures.
- [x] EIA API v2 client: daily jet fuel, WTI, Brent, heating oil; explicit series/unit contract, pagination, retries/timeouts, missing observations, provenance, date filtering.
- [x] Immutable Bronze response events with fetch IDs, source metadata, hashes, timestamps; safe replay and ingestion checkpoints; raw payload retention.
- [x] Silver: deduplicate revisions deterministically, align dates, validate units and positive jet fuel prices, preserve null proxy values, compute crack spread, log returns, actual calendar 90-day volatility and Pearson correlation.
- [x] Downsample to a regular weekly series for EWM calibration; daily ingestion frequency must not become weekly annualization by accident.
- [x] Databricks bootstrap and driver-side staging to a managed Unity Catalog volume; bounded `availableNow` streaming; catalog/schema validation; no RDD APIs or fixed cluster configuration. Live validation and replay passed.
- [x] Validate local behavior, error paths, idempotence/revisions, sparse dates, unit conversions and calendars; run live Phase 1 checks. 4,213 daily and 874 weekly rows fully reconcile between local pandas and live Spark SQL, including replay (Bronze stays at four events).
- [x] Whole-repo audit → GitHub issues #1–#5 → fixes → verified audit closure.

Exit evidence: tests/CI commands; immutable Bronze and reproducible Silver; live Unity Catalog counts/quality checks when accessible; all audit issues filed and resolved. Deployment and replay passed.

## Phase 2 — Operations and SQL analytics Gold

Status: **complete and audited**. 520 Gold fact rows reconcile; issues #6–#7 resolved; 22 tests and CI pass. Initial Gold readiness notification delivered to user.

- [x] Deterministic BTS-style synthetic routes, individual flights, and explicitly synthetic futures/swap hedge positions; schemas missing from PDD supplied.
- [x] Route validity dates, canceled-flight policy, flight uniqueness, monthly aggregation and cost-time alignment.
- [x] All six analyses: route burn, 90-day Pearson correlation, matching-underlying MTM, VaR/CVaR view ready for Phase 3, sensitivity grid, fleet summary.
- [x] Gold monthly costs by scenario without duplicate source counts; reference carrier and synthetic fleet distinct.
- [x] Underlying-aware marks and explicit unsupported/invalid valuation flags.
- [x] Initial published dashboard and all dataset queries verified.
- [x] Unity Catalog Gold, stable grains/dimensions, source lineage/quality and Power BI dictionary.
- [x] Whole-repo audit → issues #6–#7 → fixes → verified audit closure.

Exit evidence: fixture-backed query results, local/live SQL tests, row counts, reconciliation, and Gold quality results. Inform the user when this first Gold subset is actually deployed and ready, identifying which simulation tables await Phase 3.

## Phase 3 — Distributed GBM, risk Gold, and experiment tracking

Status: **complete and audited; #8–#9 closed, full 100K run and CI pass**. Phase 2 merged to main as `c6e3749`.

- [x] EWM lambda 0.94 on regular weekly log returns; annual variance and drift correction; latest chronological positive S0; record calibration window and sample count.
- [x] Deterministic Box–Muller normal generation; explicit base seed/path ID; batched Spark DataFrame/mapInPandas execution, supported on serverless, bounded per-worker memory.
- [x] 100,000 paths × 52 steps/year × horizon; same random paths for each hedge ratio; purchase averages across weekly purchase periods; annual gallons scale with horizon.
- [x] Forward `F0 = S0 * exp(r*T)` (simplified financing assumption, not a calibrated commodity forward curve); rates/consumption/horizon/hedges configurable.
- [x] Separate `silver.simulation_raw_paths` distributions, path quantile/fan summaries, run registry, and `gold.risk_metrics` aggregate table. Explicit run ID selection; never MAX(UUID).
- [x] Store mean, median, absolute P95 cost, incremental VaR = P95 − mean, CVaR = mean cost at/above absolute P95, and zero-safe VaR reduction versus unhedged.
- [x] MLflow parameters, seed, sample counts, provenance, duration, code version, output-table/run links, risk metrics; do not swallow tracking failures.
- [x] Cost histograms, price fan chart, hedge effectiveness comparison and scenario heat map in Databricks SQL.
- [x] Degenerate sigma, deterministic drift, monotonic affine hedge behavior, GBM moment checks, seed/partition invariance and NumPy/SQL risk reconciliation.
- [x] Run full 100K job on Free Edition; record observed runtime/quotas and actual evidence, not a four-worker claim.
- [x] Whole-repo audit → GitHub issues → fixes → verified audit closure.

Exit evidence: reproducible full run, five ratio results and corresponding raw counts, MLflow run, math tests, SQL agreement, and live Gold verification.

## Phase 4 — Power BI, walkthrough, and final release

Status: **complete and audited; #10–#11 resolved, final refresh/verifiers/CI pass**.

- [x] Reproducible notebook walkthrough from ingestion through calibrated risk outputs and charts; explicit source and modeling limitations.
- [x] Power BI handoff: verified workspace hostname, SQL warehouse HTTP path, catalog/schema and Gold tables; OAuth or supported workspace token auth, Import-first approach for quotas, refresh instructions.
- [x] Power Query starter, schema/relationships, DAX measure guidance; avoid summing percentiles or duplicating monthly consumption across scenarios.
- [x] README architecture, GBM derivation, metric definitions, installation/deployment, actual findings, provenance, troubleshooting and runbook.
- [x] Configure bounded daily source refresh/orchestration with a project secret scope (if supported); verify incremental revision replay and failure visibility. Preserve manual local capture/staging fallback for restricted outbound networking.
- [x] Five-minute demo script and screen-recording checklist; Loom video itself needs user recording/account access if unavailable.
- [x] Final whole-repo audit → GitHub issues → fixes → verified audit closure.
- [x] Completion report distinguishes locally tested, deployed, externally validated, and outstanding user actions. Mark complete only when required delivery work is finished.

## Requirements coverage

| PDD source | Deliverables | Phase |
| --- | --- | --- |
| 1–3 objectives and airline context | Treasury costs, assumptions, provenance, reference carrier | 1–4 |
| 4 architecture and simulation flow | Bronze/Silver/Gold, serverless pipeline, distributed risk | 1–3 |
| 5.1 prices | Raw events + enriched Silver fuel prices | 1 |
| 5.2 routes and missing flights | Valid-time routes and synthetic flight facts | 2 |
| 5.3 hedge positions | Positions, supported instrument valuation, source flags | 2 |
| 5.4 route costs | Monthly scenario fact, route/date dimensions | 2 |
| 5.5 risk metrics and missing raw paths | Run registry, raw distribution, aggregate risk | 3 |
| 6.1–6.6 SQL | Six corrected, testable queries | 2–3 |
| 7.1–7.3 methodology | EWM calibration, deterministic GBM, correct tails | 3 |
| 8 and Appendix B infrastructure | Free Edition serverless adaptation, secrets, deployment | 1–4 |
| 9 roadmap and 10 packaging | Walkthrough, charts, README, demo script | 4 |
| Appendix A sources | EIA actual prices; synthetic BTS-style ops clearly labeled | 1–2 |
| User addition 2026-10-10 | Live Free Edition medallion data and Power BI-ready Gold notification | 1–4 |

## External prerequisites and current blockers

- Databricks workspace credentials and warehouse are configured locally; all four phases and live refresh verification succeeded.
- EIA key configured locally; actual history captured. Synthetic operations are explicitly labeled.
- GitHub CLI works outside sandbox; incremental commits/pushes authorized. Connector remains inaccessible. Use host-context CLI for audit issues.
- Native DOCX rendering is unavailable in this Windows runtime: no bundled LibreOffice supplied; text and OOXML contents were fully inspected. Source DOCX is unchanged; no generated DOCX is a deliverable.

## Primary references checked 2026-10-10

- https://docs.databricks.com/aws/en/getting-started/free-edition-limitations
- https://docs.databricks.com/aws/en/compute/serverless/limitations
- https://docs.databricks.com/aws/en/dev-tools/auth/oauth-u2m
- https://docs.databricks.com/aws/en/partners/bi/power-bi/
- https://learn.microsoft.com/en-us/power-query/connectors/databricks
- https://www.eia.gov/opendata/browser/petroleum/pri/spt

Implementation release: `docs/RELEASE.md`. User handoff actions: connect/build Power BI report, record/upload the prepared Loom walkthrough. No unresolved implementation blocker.


## Phase 5 — Insight-driven Power BI (2026-10-21)

Status: implementation and local verification complete; live refresh/audit gate in progress on phase-5-powerbi-insights.

- [x] Read all baseline docs, notebooks, simulation/Silver/operations, SQL and reporting/deployment source.
- [x] Add testable historical decomposition, paired proxy returns, weekly effectiveness, complete hedge windows, calibration history, deterministic drift-model backtest and tail frequencies.
- [x] Append-only insight registry/quality, seven guarded facts and additive readiness; sequential task immediately after Silver.
- [x] Five-page PBIP/TMDL/PBIR, dedicated DAX folders/dynamic titles, exactly 15 narrative units, theme, labels/badges, alt text and query-view/SQL contracts.
- [x] Independent pandas/Box–Muller oracle; every offline deterministic/Monte Carlo value reconciled to 1e-9. Published-schema validation and real Microsoft TOM parse pass.
- [x] Render and inspect all 15 matplotlib narrative units plus compile the actual three layered PBIR specifications. Keep offline and Desktop evidence distinct.
- [ ] Live current-source reconciliation, reporting adversarial cases and full seven-task managed refresh.
- [ ] Whole-repo audit, GitHub issue evidence/closure, both Python CI versions, main merge.
- [ ] Native Desktop authentication/refresh/DAX/page screenshots, or explicit unavailable-access handoff per user allowance.

No production simulation default or existing data-history deletion is part of Phase 5.
