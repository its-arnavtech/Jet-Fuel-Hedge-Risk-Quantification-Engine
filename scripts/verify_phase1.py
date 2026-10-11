"""Verify live Silver against local EIA transformation and persist evidence."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time

import numpy as np
import pandas as pd

from fuel_hedge.config import Settings, load_env
from fuel_hedge.databricks import workspace_client


def query(client, warehouse_id, statement):
    result = client.statement_execution.execute_statement(
        warehouse_id=warehouse_id, statement=statement, wait_timeout="10s")
    deadline = time.monotonic() + 600
    while result.status.state.value in {"PENDING", "RUNNING"}:
        if time.monotonic() > deadline:
            client.statement_execution.cancel_execution(result.statement_id)
            raise TimeoutError("SQL verification timed out")
        time.sleep(2)
        result = client.statement_execution.get_statement(result.statement_id)
    if result.status.state.value != "SUCCEEDED":
        raise RuntimeError(f"SQL verification failed: {result.status.error}")
    columns = [c.name for c in result.manifest.schema.columns]
    data = list(result.result.data_array or [])
    chunk = result.result.next_chunk_index
    while chunk is not None:
        more = client.statement_execution.get_statement_result_chunk_n(result.statement_id, chunk)
        data.extend(more.data_array or [])
        chunk = more.next_chunk_index
    return pd.DataFrame(data, columns=columns)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--local", default="artifacts/silver")
    parser.add_argument("--output", default="artifacts/phase1_verification.json")
    args = parser.parse_args()
    load_env()
    settings = Settings.from_env()
    if not settings.warehouse_id:
        raise ValueError("DATABRICKS_WAREHOUSE_ID is required for SQL verification")
    client = workspace_client(settings)
    schema = f"{settings.catalog}.jet_fuel_silver"
    runs = query(client, settings.warehouse_id,
                 f"SELECT * FROM {schema}.pipeline_runs ORDER BY started_at DESC LIMIT 1")
    quality = query(client, settings.warehouse_id, f"SELECT * FROM {schema}.ingestion_quality")
    if (len(runs) != 1 or len(quality) != 1 or runs.iloc[0].status != "SUCCESS"
            or runs.iloc[0].pipeline_run_id != quality.iloc[0].pipeline_run_id):
        raise ValueError("Latest pipeline publication is not verified successful")
    columns = ["price_date", "jet_fuel_gal", "wti_spot_bbl", "brent_spot_bbl", "heating_oil_gal",
               "crack_spread", "log_return", "rolling_vol_90d", "rolling_corr_90d"]
    cloud = query(client, settings.warehouse_id,
                  f"SELECT {','.join(columns)} FROM {schema}.fuel_prices ORDER BY price_date")
    local = pd.read_csv(Path(args.local) / "fuel_prices.csv")
    if cloud.price_date.tolist() != local.price_date.tolist():
        raise ValueError("Cloud/local dates or row counts differ")
    for column in columns[1:]:
        np.testing.assert_allclose(pd.to_numeric(cloud[column]).to_numpy(dtype=float),
                                   pd.to_numeric(local[column]).to_numpy(dtype=float),
                                   rtol=1e-7, atol=1e-9, equal_nan=True,
                                   err_msg=f"Cloud/local mismatch: {column}")
    weekly = query(client, settings.warehouse_id,
                   f"SELECT week_ending, observation_date, jet_fuel_gal, log_return "
                   f"FROM {schema}.weekly_fuel_prices ORDER BY week_ending")
    weekly_local = pd.read_csv(Path(args.local) / "weekly_fuel_prices.csv")
    for column in ["week_ending", "observation_date"]:
        if weekly[column].tolist() != weekly_local[column].tolist():
            raise ValueError(f"Cloud/local weekly {column} mismatch")
    for column in ["jet_fuel_gal", "log_return"]:
        np.testing.assert_allclose(pd.to_numeric(weekly[column]).to_numpy(dtype=float),
                                   weekly_local[column].to_numpy(dtype=float),
                                   rtol=1e-7, atol=1e-9, equal_nan=True)
    evidence = {"checked_at": datetime.now(timezone.utc).isoformat(),
                "daily_rows_reconciled": len(cloud), "weekly_rows_reconciled": len(weekly),
                "publication_run_id": runs.iloc[0].pipeline_run_id,
                "quality": quality.to_dict("records")[0], "passed": True}
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    main()
