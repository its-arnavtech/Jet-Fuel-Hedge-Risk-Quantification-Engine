# Development and Free Edition runbook

Read `docs/PLAN.md`, `CHANGELOG.md`, `docs/DECISIONS.md`, and the latest audit before resuming.

## Local setup

Use Python 3.10 or newer:

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[databricks,dev]"
.venv\Scripts\python -m unittest discover -s tests -v
.venv\Scripts\ruff check src tests scripts
```

For a locked environment, use `uv sync --frozen --extra databricks --extra dev`; `uv.lock` records dependency resolution. CI tests both Python 3.10 and 3.12 using the locked development environment.

Copy `.env.example` to `.env` only if `.env` does not already exist. Fill `DATABRICKS_HOST` with the workspace **origin**, e.g. `https://dbc-example.cloud.databricks.com`, not a settings page URL. Fill `DATABRICKS_TOKEN` locally, or use Databricks CLI OAuth unified auth. Fill `EIA_API_KEY` from https://www.eia.gov/opendata/register.php. Do not store credentials in notebooks or source control. Verify `git check-ignore .env` before entering secrets. The warehouse ID is optional for notebook-job deployment; it will be useful for SQL/Power BI checks later.

## Capture and transform actual EIA data

```powershell
fuel-hedge ingest --start 2010-01-01 --end 2026-10-09
fuel-hedge silver
```

Use the latest completed business day at execution time. EIA publication can lag the observation date. Daily jobs should recapture an overlap (at least 30 calendar days) to capture revisions; periodically recapture the full history for older revisions. Each invocation appends immutable page events; only a successfully completed manifest is publishable. Replays do not duplicate Silver business dates. A failed capture leaves raw events for diagnosis and is excluded from publication. Files and outputs live under ignored `artifacts/`.

Raw response metadata is retained after stripping EIA's echoed API key. `payload_sha256` hashes the **redacted canonical JSON**, not raw network bytes. HTTP error bodies and credential-bearing request URLs are never logged. Gulf Coast jet fuel and NY Harbor heating oil are USD/gallon; WTI/Brent are USD/barrel. WTI can be negative (April 2020); GBM jet fuel inputs must be positive.

Silver quarantines invalid latest revisions; it never falls back to an older withdrawn value. Missing optional proxies stay null; there is no price forward fill. API unit codes `$/GAL` and `$/BBL` (or their exact descriptive equivalents) are accepted; cents or barrel/gallon mismatches are rejected. Daily volatility uses sample daily log-return standard deviation × sqrt(252) within the preceding 90 calendar days, with at least 20 returns. It is suppressed whenever a return gap exceeds four calendar days in the window; `long_return_gap` and quality counts expose those cases. This conservatively permits common weekend/holiday closures while avoiding misleading daily estimates across long missing spans. Weekly calibration samples the latest valid observation per complete Friday-ended week, rejects missing weeks, and requires 26 observations. Calibration must later impose its explicit lookback window.

## Databricks Phase 1 deployment

```powershell
.venv\Scripts\python scripts/deploy_phase1.py --wait
```

The script validates local completed captures, uses the SDK and your user identity, creates managed `jet_fuel_bronze`, `jet_fuel_silver`, `jet_fuel_gold` schemas in the selected catalog and `jet_fuel_bronze.landing` volume, stages complete captures, imports `notebooks/phase1_pipeline.py`, and submits a bounded serverless notebook job. Existing schemas must carry the project ownership comment; unowned schemas are rejected. No paid cluster is configured. The Gold schema is created for the medallion layout but contains no Phase 1 Gold data.

The notebook streams immutable capture JSONL from `/Volumes/<catalog>/jet_fuel_bronze/landing/captures` into append-only `jet_fuel_bronze.eia_price_events` with `availableNow=True` and a persistent volume checkpoint. Never delete the checkpoint casually; Silver deduplicates by observation but Bronze append counts would change on replay. Silver tables are rebuilt from all raw observations so historical corrections propagate. Do not run concurrent publishers for this pipeline. Never overwrite existing capture content.

Verify the actual run result and inspect:

```sql
SELECT * FROM workspace.jet_fuel_silver.ingestion_quality;
SELECT * FROM workspace.jet_fuel_silver.pipeline_runs ORDER BY started_at DESC;
SELECT * FROM workspace.jet_fuel_silver.price_quarantine;
SELECT COUNT(*) AS duplicates FROM (
  SELECT price_date FROM workspace.jet_fuel_silver.fuel_prices GROUP BY price_date HAVING COUNT(*) > 1
);
```

Change `workspace` to your configured catalog. Candidates are checked before publication. Multiple Delta tables are not a single atomic transaction: the newest `pipeline_runs` row must be `SUCCESS` and its run ID must match `ingestion_quality.pipeline_run_id` before downstream consumption. A failed/interrupted publication leaves `STARTED` and must not be consumed. Record observed counts, latest date, source flags and run URL in the changelog/audit. A submitted run is not a successful deployment. Free Edition quotas can stop compute; retain data and rerun after reset. If remote EIA access is blocked, local capture plus volume staging remains the intended path.

## Full analytics, simulation and reporting

After Silver succeeds, run `scripts/deploy_phase2.py`, wait for the printed job to succeed, then `scripts/verify_phase2.py`. Run `scripts/deploy_phase3.py`, wait for SUCCESS, then `scripts/verify_phase3.py`. It independently reproduces all 100K paths and reconciles exact SQL risk, full fan and MLflow completion. Run `scripts/verify_reporting.py` to publish/check the reporting contract and its adversarial source/publication cases. Verification uses the configured SQL warehouse; every persistent name is catalog-qualified because Statement Execution sessions are independent.

The simulation uses the public MLflow registry URI `databricks-uc` explicitly, avoiding unsupported serverless Spark configuration lookup. Registry SUCCESS follows MLflow context completion and quality publication. Price paths, costs and Gold summaries retain simulation IDs; select the latest successful run and check its source. Failed candidates remain STARTED for diagnosis and are excluded from guarded reporting. Do not delete/relabel them to manufacture readiness.

## Daily managed refresh

Managed job ID: `1025825966695931`. Seven **sequential** tasks, maximum one concurrent run:

1. `refresh_capture`: full actual EIA recapture from 2010 to previous UTC day, using secret scope `jet-fuel-hedge-engine`, key `eia-api-key`. Responses redact the key. Complete capture is assembled before same-volume publication; temporary files stay outside the stream source.
2. `phase1_pipeline`: bounded Bronze stream and revision-aware Silver.
3. `phase5_insights`: independent historical evidence and 10K-path/window/model walk-forward validation. Append-only run/quality history; current views fail closed on STARTED/source/count mismatches.
4. `refresh_operations`: explicitly synthetic fixtures anchored to latest Silver date, immutable content-addressed snapshot.
5. `phase2_gold`: six analytics views, dimensions, monthly scenarios and reconciliation.
6. `phase3_risk`: 100K distributed paths, exact aggregates and MLflow.
7. `reporting_contract`: current-source readiness and guarded reporting views.

```powershell
# Initial deployment/test: schedule defaults PAUSED.
uv run python scripts/deploy_refresh_job.py --run-now
# Only after all seven tasks and verifiers pass:
uv run python scripts/deploy_refresh_job.py --enable-schedule
# Pause without deleting data or job history:
uv run python scripts/deploy_refresh_job.py
```

The enabled schedule is daily **18:00 America/Chicago**. Versioned notebook paths and source hashes make deployed code inspectable. `artifacts/refresh_job.json` stores the non-secret workspace/job ID and hashes for idempotent updates; retain it. After cloning elsewhere, recover that file with the documented host/job ID before redeployment to avoid duplicate jobs. Existing job tags must identify this project. Each task has a 30-minute timeout, the job two hours, zero automatic retries; failures are visible in Jobs run history and readiness. No email notifications were configured.

Do not run separate manual publishers concurrently with this job; max-concurrency applies to this managed job, not unrelated/manual submissions. If quota/network errors occur, inspect the failed task, wait for quota reset or fix the cause, then rerun the whole job. Do not remove the stream checkpoint. If EIA egress becomes restricted, capture locally, stage with Phase 1, and run phases in order. Source publication can lag observation dates; display the watermark, not execution date, as data freshness.

Power BI Import should run after the full managed job succeeds and readiness flags are true. Guarded views exclude incomplete/stale publications but separate Import queries are not a transactional snapshot. Keep refreshes outside pipeline publication windows. Historical simulation retention grows by 100K price paths and 500K costs per successful run; no automatic destructive retention policy is configured. Monitor Free Edition storage/compute limits and archive approved history separately if needed.

The independent local phase verifiers compare cloud output against local actual captures. After a future cloud-only refresh, recapture the same EIA window locally and run `fuel-hedge silver` before comparing; stale local CSVs are not a valid oracle for changed cloud source data. Reporting verification derives route/fan counts from the current published configuration rather than assuming every trailing-year window spans 13 months.

## Release checks

```powershell
uv run python scripts/build_walkthrough.py
uv run python scripts/check_repository.py
uv run python -m unittest discover -s tests -v
uv run ruff check .
uv run python -m compileall -q src scripts notebooks
```

Text IO is explicitly UTF-8 for cross-platform handoff. The repository scan validates all publishable text and rejects configured credential values or token-shaped strings without printing them. Never commit ignored captures, local credentials or environment state. DOCX remains unchanged.

## Troubleshooting notes

- `gh auth status` may report invalid credentials inside the Windows sandbox even when host authentication works; use an approved host-context command, without printing tokens.
- Windows sandbox temporary-directory ACLs can block filesystem tests. Set TEMP and TMP to an absolute writable directory such as `<repo>/.tmp/tests`, then rerun. Do not change product logic for this environment artifact.
- Databricks and MLflow SDKs are optional project dependencies; local unit tests require only NumPy/pandas.
- Do not use the PDD's RDD API, cache/persist, fixed cluster, identity partition expression or infinite streaming trigger on Free Edition.
- Phase 2 must wait for the Phase 1 audit issue/fix gate. Power BI readiness must wait for actual Gold deployment and quality checks.


## Phase 5 insight/report validation

Run `scripts/deploy_phase5.py`, wait for the printed job SUCCESS, then `scripts/verify_phase5.py`. It reads live Silver through SQL and independently verifies every column of all seven current insight tables, including 10K-path quantiles and simulation calibration equality. It writes docs/evidence/phase5_verification.json only after success. Never use the explicit --offline evidence as proof of live publication. Old result files should be checked against their source/run IDs and verification timestamp.

Run `scripts/verify_reporting.py` for the existing publication/source adversaries plus stale insight source, STARTED insight and actual/expected count mismatch. It runs fixtures against the actual view SELECT without mutating production tables. Then `scripts/verify_powerbi_contract.py --live` checks the warehouse equivalents of headline numbers. TMDL parsing uses `scripts/verify_tmdl.ps1 -AssemblyFolder <official TOM library folder>`; the development check used Microsoft.AnalysisServices 19.118.3 from NuGet. Desktop Store binaries may be protected; do not change their permissions.

Rebuild with `scripts/build_powerbi.py`, validate every PBIP JSON and embedded Vega-Lite spec, then render the 15 matplotlib units and the exact layered PBIR specs. `scripts/render_insight_storyboard.py` defaults to verified Gold extracts; --offline is explicit. `scripts/render_powerbi_specs.py` compiles the real three layered specs, not approximations. Keep compiled-spec previews separate from native Desktop screenshots. Native authentication, refresh, DAX query execution and screenshot handoff are in POWER_BI.md.

If compute is temporarily disabled, keep append-only history, guards and source hashes intact. An imported notebook is not a successful run. The initial Phase 5 attempt hit this condition and required workspace compute restoration; no credentials were changed or printed. Do not deploy concurrently with the managed refresh. New Phase 5 source does not change production simulation calibration/defaults.
