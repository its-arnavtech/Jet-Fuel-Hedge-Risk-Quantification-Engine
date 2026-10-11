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

## Troubleshooting and handoff

- `gh auth status` may report invalid credentials inside the Windows sandbox even when host authentication works; use an approved host-context command, without printing tokens.
- Windows sandbox temporary-directory ACLs can block filesystem tests. Set TEMP and TMP to an absolute writable directory such as `<repo>/.tmp/tests`, then rerun. Do not change product logic for this environment artifact.
- Databricks and MLflow SDKs are optional project dependencies; local unit tests require only NumPy/pandas.
- Do not use the PDD's RDD API, cache/persist, fixed cluster, identity partition expression or infinite streaming trigger on Free Edition.
- Phase 2 must wait for the Phase 1 audit issue/fix gate. Power BI readiness must wait for actual Gold deployment and quality checks.
