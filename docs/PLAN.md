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
- [x] Databricks bootstrap and driver-side staging to a managed Unity Catalog volume; bounded `availableNow` streaming; catalog/schema validation; no RDD APIs or fixed cluster configuration. Code written; live validation pending.
- [x] Validate local behavior, error paths, idempotence/revisions, sparse dates, unit conversions and calendars; run live Phase 1 checks. 4,213 daily and 874 weekly rows fully reconcile between local pandas and live Spark SQL, including replay (Bronze stays at four events).
- [x] Whole-repo audit → GitHub issues #1–#5 → fixes → verified audit closure.

Exit evidence: tests/CI commands; immutable Bronze and reproducible Silver; live Unity Catalog counts/quality checks when accessible; all audit issues filed and resolved. Deployment validation stays pending until workspace access is supplied.

## Phase 2 — Operations and SQL analytics Gold

Status: **not started; depends on Phase 1 gate**.

- [ ] Deterministic BTS-style synthetic routes, individual flights, and explicitly synthetic futures/swap hedge positions; schemas missing from PDD supplied.
- [ ] Route validity dates, canceled-flight policy, flight uniqueness, monthly aggregation and cost-time alignment.
- [ ] All six analyses: route fuel burn, 90-calendar-day Pearson correlation, open-position mark-to-market, VaR/CVaR (schema/query ready for Phase 3 data), hedge sensitivity CROSS JOIN, fleet annual consumption summary.
- [ ] Gold monthly route costs by **scenario** without double-counting flights/position notional; explicit annual reference-carrier versus synthetic-fleet consumption.
- [ ] Instrument/underlying-aware marks with barrel-to-gallon conversion; reject unsupported option/collar valuation rather than pricing as futures.
- [ ] Initial Databricks dashboard SQL for price trends, route ranking, hedge status and sensitivity.
- [ ] Unity Catalog Gold tables, stable keys, date and route dimensions, freshness/source flags, validation metrics and Power BI data dictionary.
- [ ] Whole-repo audit → GitHub issues → fixes → verified audit closure.

Exit evidence: fixture-backed query results, local/live SQL tests, row counts, reconciliation, and Gold quality results. Inform the user when this first Gold subset is actually deployed and ready, identifying which simulation tables await Phase 3.

## Phase 3 — Distributed GBM, risk Gold, and experiment tracking

Status: **not started; depends on Phase 2 gate**.

- [ ] EWM lambda 0.94 on regular weekly log returns; annual variance and drift correction; latest chronological positive S0; record calibration window and sample count.
- [ ] Deterministic Box–Muller normal generation; explicit base seed/path ID; batched Spark DataFrame/mapInPandas execution, supported on serverless, bounded per-worker memory.
- [ ] 100,000 paths × 52 steps/year × horizon; same random paths for each hedge ratio; purchase averages across weekly purchase periods; annual gallons scale with horizon.
- [ ] Forward `F0 = S0 * exp(r*T)` (simplified financing assumption, not a calibrated commodity forward curve); rates/consumption/horizon/hedges configurable.
- [ ] Separate `silver.simulation_raw_paths` distributions, path quantile/fan summaries, run registry, and `gold.risk_metrics` aggregate table. Explicit run ID selection; never MAX(UUID).
- [ ] Store mean, median, absolute P95 cost, incremental VaR = P95 − mean, CVaR = mean cost at/above absolute P95, and zero-safe VaR reduction versus unhedged.
- [ ] MLflow parameters, seed, sample counts, provenance, duration, code version, output-table/run links, risk metrics; do not swallow tracking failures.
- [ ] Cost histograms, price fan chart, hedge effectiveness comparison and scenario heat map in Databricks SQL.
- [ ] Degenerate sigma, deterministic drift, monotonic affine hedge behavior, GBM moment checks, seed/partition invariance and NumPy/SQL risk reconciliation.
- [ ] Run full 100K job on Free Edition; record observed runtime/quotas and actual evidence, not a four-worker claim.
- [ ] Whole-repo audit → GitHub issues → fixes → verified audit closure.

Exit evidence: reproducible full run, five ratio results and corresponding raw counts, MLflow run, math tests, SQL agreement, and live Gold verification.

## Phase 4 — Power BI, walkthrough, and final release

Status: **not started; depends on Phase 3 gate**.

- [ ] Reproducible notebook walkthrough from ingestion through calibrated risk outputs and charts; explicit source and modeling limitations.
- [ ] Power BI handoff: verified workspace hostname, SQL warehouse HTTP path, catalog/schema and Gold tables; OAuth or supported workspace token auth, Import-first approach for quotas, refresh instructions.
- [ ] Power Query starter, schema/relationships, DAX measure guidance; avoid summing percentiles or duplicating monthly consumption across scenarios.
- [ ] README architecture, GBM derivation, metric definitions, installation/deployment, actual findings, provenance, troubleshooting and runbook.
- [ ] Configure bounded daily source refresh/orchestration with a project secret scope (if supported); verify incremental revision replay and failure visibility. Preserve manual local capture/staging fallback for restricted outbound networking.
- [ ] Five-minute demo script and screen-recording checklist; Loom video itself needs user recording/account access if unavailable.
- [ ] Final whole-repo audit → GitHub issues → fixes → verified audit closure.
- [ ] Completion report distinguishes locally tested, deployed, externally validated, and outstanding user actions. Mark complete only when required delivery work is finished.

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

- Databricks workspace URL and token are configured in Git-ignored `.env`; live validation is next. SQL warehouse discovery pending.
- EIA API key (free registration) for real price ingestion. A public sample/demo must never silently replace real data.
- GitHub CLI works outside sandbox; incremental commits/pushes authorized. Connector remains inaccessible. Use host-context CLI for audit issues.
- Native DOCX rendering is unavailable in this Windows runtime: no bundled LibreOffice supplied; text and OOXML contents were fully inspected. Source DOCX is unchanged; no generated DOCX is a deliverable.

## Primary references checked 2026-10-10

- https://docs.databricks.com/aws/en/getting-started/free-edition-limitations
- https://docs.databricks.com/aws/en/compute/serverless/limitations
- https://docs.databricks.com/aws/en/dev-tools/auth/oauth-u2m
- https://docs.databricks.com/aws/en/partners/bi/power-bi/
- https://learn.microsoft.com/en-us/power-query/connectors/databricks
- https://www.eia.gov/opendata/browser/petroleum/pri/spt
