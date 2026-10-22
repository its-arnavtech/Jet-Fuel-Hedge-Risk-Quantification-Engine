"""Deploy immutable Phase 5 notebook source using existing secure workspace auth."""

import base64
import hashlib
import json
from pathlib import Path

from fuel_hedge.config import Settings, load_env
from fuel_hedge.databricks import ensure_project_schemas, workspace_client


def build_source(root, include_reporting=True):
    source = (root/"notebooks/phase5_insights.py").read_text(encoding="utf-8")
    simulation = (root/"src/fuel_hedge/simulation.py").read_text(encoding="utf-8")
    insights = (root/"src/fuel_hedge/insights.py").read_text(encoding="utf-8")
    insights = insights.replace("from fuel_hedge.simulation import SimulationConfig, calibrate, price_paths", "")
    # Standalone deployment also adds insights_ready; scheduled publication repeats this at job end.
    sql_text = (root/"sql/08_insights.sql").read_text(encoding="utf-8")
    if include_reporting:
        sql_text += (root/"sql/07_reporting_contract.sql").read_text(encoding="utf-8")
    sql = "\n".join("spark.sql("+repr(s.strip())+")" for s in sql_text.split(";") if s.strip())
    return source.replace("# INJECT_SIMULATION_MODULE", simulation).replace(
        "# INJECT_INSIGHTS_MODULE", insights).replace("# INJECT_INSIGHTS_SQL", sql)


def main():
    from databricks.sdk.errors import ResourceAlreadyExists
    from databricks.sdk.service import jobs, workspace
    root = Path(__file__).resolve().parents[1]
    load_env(root/".env")
    settings = Settings.from_env()
    client = workspace_client(settings)
    ensure_project_schemas(client, settings.catalog)
    source = build_source(root)
    digest = hashlib.sha256(source.encode()).hexdigest()
    folder = f"/Users/{client.current_user.me().user_name}/jet-fuel-hedge-engine/phase5"
    client.workspace.mkdirs(folder)
    remote = f"{folder}/insights_{digest[:16]}"
    try:
        client.workspace.import_(path=remote, content=base64.b64encode(source.encode()).decode(),
                                 format=workspace.ImportFormat.SOURCE, language=workspace.Language.PYTHON,
                                 overwrite=False)
    except ResourceAlreadyExists:
        exported = client.workspace.export(remote, format=workspace.ExportFormat.SOURCE)
        if base64.b64decode(exported.content).decode().replace("\r\n", "\n") != source.replace("\r\n", "\n"):
            raise ValueError("Versioned Phase 5 notebook source conflict")
    run = client.jobs.submit(run_name="jet-fuel-phase5-insights", timeout_seconds=7200,
        tasks=[jobs.SubmitTask(task_key="phase5_insights", timeout_seconds=7200,
               notebook_task=jobs.NotebookTask(notebook_path=remote, source=jobs.Source.WORKSPACE,
                                              base_parameters={"catalog": settings.catalog}))])
    result = dict(run_id=run.run_id, source_sha256=digest, execution_mode="mapInPandas")
    (root/"artifacts/phase5_deployment.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
