# Phase 1 repository audit

Audit date: 2026-10-10. Implementation baseline: `13bf91e`. Scope: every tracked source/config/doc/test/notebook/workflow, PDD requirements and external deployment assumptions.

## Status

**Audit passed. Phase 1 gate complete.** All five findings resolved in `d30f254` and `dcc5389`. Nineteen tests, Ruff, compilation and CI pass. Initial live deployment and replay succeed; all prices and metrics reconcile with local calculations. No findings are inferred solely from unavailable credentials or sandbox restrictions.

## Findings

### A1 — Shared schema names can overwrite unrelated workspace data

- Severity: high.
- Evidence: `src/fuel_hedge/databricks.py` creates generic `bronze`, `silver`, `gold`; notebook executes `CREATE OR REPLACE TABLE silver.fuel_prices`.
- Reproduction: run in a catalog already containing an unrelated `silver.fuel_prices` table. The notebook replaces its data/schema.
- Expected: dedicated project schemas with explicit ownership and no replacement of unrelated data.
- Fix plan: use `jet_fuel_bronze`, `jet_fuel_silver`, `jet_fuel_gold`; verify schema ownership marker before use; update paths, runbook and tests.
- GitHub: https://github.com/its-arnavtech/Jet-Fuel-Hedge-Risk-Quantification-Engine/issues/1
- Resolution: dedicated schemas and ownership rejection regression pass; live deployment uses only project schemas. Closed.

### A2 — Silver publication occurs before weekly quality validation

- Severity: medium.
- Evidence: notebook replaces `silver.fuel_prices` and `silver.weekly_fuel_prices`, then checks weekly gaps/minimum sample size.
- Reproduction: ingest a dataset missing a whole week. Job fails but invalid replacement tables remain visible and prior quality table can appear successful.
- Expected: validate candidate daily/weekly data before publication; retain a persistent run status/watermark so consumers can detect interrupted publication.
- Fix plan: build candidate temporary views, validate gaps/counts first, add run-status registry and associate quality results with successful run IDs. Require downstream phases to check latest run success.
- GitHub: https://github.com/its-arnavtech/Jet-Fuel-Hedge-Risk-Quantification-Engine/issues/2
- Resolution: candidate validation precedes publication; persistent registry SUCCESS matches live quality watermark, including replay. Closed.

### A3 — Daily volatility is published across long missing-observation gaps

- Severity: medium.
- Evidence: `silver.py` computes a single log return across an arbitrary gap and annualizes it with sqrt(252); cloud SQL does the same.
- Reproduction: remove several trading weeks while retaining >20 other observations in the 90-day window. The rolling volatility remains non-null despite irregular sampling.
- Expected: expose gaps and suppress the trading-day volatility estimate while a long gap is in the window; retain prices without imputation and keep weekly calibration gap rejection.
- Fix plan: null rolling daily volatility whenever any return gap exceeds four calendar days in the window; add quality counts and matched local/SQL tests. Four days allows common weekend/holiday closures; longer closures conservatively suppress the estimate.
- GitHub: https://github.com/its-arnavtech/Jet-Fuel-Hedge-Risk-Quantification-Engine/issues/3
- Resolution: long-gap regression passes; live six-gap count and all rolling estimates/nulls reconcile with local pandas. Closed.

### A4 — Live EIA unit codes were rejected by descriptive-only validation

- Severity: high.
- Reproduction/evidence: live capture returned 16,876 observations in `$/GAL` and `$/BBL`; initial local Silver raised `No valid EIA observations remain`.
- Expected: accept actual EIA unit codes with exact equivalence, reject incompatible units.
- GitHub: https://github.com/its-arnavtech/Jet-Fuel-Hedge-Risk-Quantification-Engine/issues/4
- Resolution: exact codes and descriptive equivalents supported; real-response regression passes. Live/local actual data: 4,213 daily and 874 weekly rows, zero quarantine; full reconciliation passed. Closed.

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

### A5 — Existing-capture upload stalls on replay

- Severity: medium.
- Evidence: initial deployment and SQL reconciliation succeeded, but a second deployment stalled before job submission. Authenticated remote download immediately matched local bytes.
- GitHub: https://github.com/its-arnavtech/Jet-Fuel-Hedge-Risk-Quantification-Engine/issues/5
- Resolution: pre-upload existence/content verification, conflict rejection, bounded SDK Config, stable Files API. Regressions pass. Replay run `76990162773186` SUCCESS; Bronze stays at four events and all Silver values still reconcile. Closed.

Initial run `176651287504745` and replay `76990162773186`: SUCCESS. All 4,213 daily and 874 weekly rows, prices, returns, calendar volatility/correlation, and nulls agree within rtol=1e-7 / atol=1e-9. Replay quality watermark `1d9c0ac4-ff20-4fb6-8d9c-d784316f4d0d` matches SUCCESS registry. Source range 2010-01-04 to 2026-10-06; four page events / 16,876 observations, zero quarantine, six long gaps flagged. `dcc5389` passes locked CI on Python 3.10/3.12 ([run](https://github.com/its-arnavtech/Jet-Fuel-Hedge-Risk-Quantification-Engine/actions/runs/38099331383)). Nineteen local tests, Ruff and compile checks pass; credential scan passed. Main merge is the release bookkeeping step after this audit closure.
