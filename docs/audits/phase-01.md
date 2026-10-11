# Phase 1 repository audit

Audit date: 2026-10-10. Implementation baseline: `13bf91e`. Scope: every tracked source/config/doc/test/notebook/workflow, PDD requirements and external deployment assumptions.

## Status

**Audit in progress. Phase 1 gate not passed.** Twelve unit tests, Ruff and compilation pass; live ingestion/deployment and additional deployment-helper tests pending. Findings below are ready to file and must be resolved before Phase 2. No findings are inferred solely from unavailable credentials or sandbox restrictions.

## Findings

### A1 — Shared schema names can overwrite unrelated workspace data

- Severity: high.
- Evidence: `src/fuel_hedge/databricks.py` creates generic `bronze`, `silver`, `gold`; notebook executes `CREATE OR REPLACE TABLE silver.fuel_prices`.
- Reproduction: run in a catalog already containing an unrelated `silver.fuel_prices` table. The notebook replaces its data/schema.
- Expected: dedicated project schemas with explicit ownership and no replacement of unrelated data.
- Fix plan: use `jet_fuel_bronze`, `jet_fuel_silver`, `jet_fuel_gold`; verify schema ownership marker before use; update paths, runbook and tests.
- GitHub: https://github.com/its-arnavtech/Jet-Fuel-Hedge-Risk-Quantification-Engine/issues/1
- Resolution: dedicated schemas and ownership marker implemented/tested; cloud validation pending.

### A2 — Silver publication occurs before weekly quality validation

- Severity: medium.
- Evidence: notebook replaces `silver.fuel_prices` and `silver.weekly_fuel_prices`, then checks weekly gaps/minimum sample size.
- Reproduction: ingest a dataset missing a whole week. Job fails but invalid replacement tables remain visible and prior quality table can appear successful.
- Expected: validate candidate daily/weekly data before publication; retain a persistent run status/watermark so consumers can detect interrupted publication.
- Fix plan: build candidate temporary views, validate gaps/counts first, add run-status registry and associate quality results with successful run IDs. Require downstream phases to check latest run success.
- GitHub: https://github.com/its-arnavtech/Jet-Fuel-Hedge-Risk-Quantification-Engine/issues/2
- Resolution: candidate validation before publication and persistent status/watermark implemented; cloud validation pending.

### A3 — Daily volatility is published across long missing-observation gaps

- Severity: medium.
- Evidence: `silver.py` computes a single log return across an arbitrary gap and annualizes it with sqrt(252); cloud SQL does the same.
- Reproduction: remove several trading weeks while retaining >20 other observations in the 90-day window. The rolling volatility remains non-null despite irregular sampling.
- Expected: expose gaps and suppress the trading-day volatility estimate while a long gap is in the window; retain prices without imputation and keep weekly calibration gap rejection.
- Fix plan: null rolling daily volatility whenever any return gap exceeds four calendar days in the window; add quality counts and matched local/SQL tests. Four days allows common weekend/holiday closures; longer closures conservatively suppress the estimate.
- GitHub: https://github.com/its-arnavtech/Jet-Fuel-Hedge-Risk-Quantification-Engine/issues/3
- Resolution: long-gap suppression and quality counts implemented; regression passes, cloud reconciliation pending.

### A4 — Live EIA unit codes were rejected by descriptive-only validation

- Severity: high.
- Reproduction/evidence: live capture returned 16,876 observations in `$/GAL` and `$/BBL`; initial local Silver raised `No valid EIA observations remain`.
- Expected: accept actual EIA unit codes with exact equivalence, reject incompatible units.
- GitHub: https://github.com/its-arnavtech/Jet-Fuel-Hedge-Risk-Quantification-Engine/issues/4
- Resolution: exact codes and descriptive equivalents supported in local/cloud contracts; actual-response fixture and regression added. Local actual data: 4,213 daily and 874 weekly rows, zero quarantined. Cloud validation pending.

## Coverage

| Area | Assessment |
| --- | --- |
| Full PDD understanding and phase traceability | Recorded in PLAN/DECISIONS |
| Secret handling | `.env` ignored; literal config; EIA echoed key redacted; network errors do not disclose URLs |
| API contract/retries/pagination | Tested with fixtures; live source contract pending |
| Bronze immutability/completed-capture isolation | Unit tested; staged JSONL helper needs coverage |
| Silver revisions/nulls/units/negative WTI | Unit tested |
| Calendar volatility/correlation and weekly regularity | Unit tested; A3 open |
| Serverless APIs and storage | No RDD/cache/indefinite triggers; live SQL execution pending |
| Data publication and workspace isolation | A1/A2 open |
| Reproducible environment/CI | CI defined; dependency lock and remote CI verification pending |
| Documentation/handoff | Plan and changelog in repo and pushed; actual Gold readiness explicitly pending |

## Closure evidence

Pending GitHub issue URLs, fix commit, test results, real EIA row counts, Databricks run status/table checks, and main merge.
