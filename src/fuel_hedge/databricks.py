"""Free Edition deployment helpers. SDK is optional for local-only processing."""

from collections import defaultdict
import base64
from datetime import timedelta
import io
from pathlib import Path

from .bronze import canonical_json, read_completed
from .config import Settings

PROJECT_MARKER = "Jet Fuel Hedge Risk Quantification Engine managed schema v1"
SCHEMAS = ("jet_fuel_bronze", "jet_fuel_silver", "jet_fuel_gold")


def ensure_project_schemas(client, catalog: str) -> None:
    from databricks.sdk.errors import NotFound, ResourceAlreadyExists
    for schema in SCHEMAS:
        name = f"{catalog}.{schema}"
        try:
            existing = client.schemas.get(name)
        except NotFound:
            try:
                client.schemas.create(name=schema, catalog_name=catalog, comment=PROJECT_MARKER)
            except ResourceAlreadyExists:
                existing = client.schemas.get(name)
                if existing.comment != PROJECT_MARKER:
                    raise ValueError(f"Refusing to use unowned project schema {name}") from None
        else:
            if existing.comment != PROJECT_MARKER:
                raise ValueError(f"Refusing to use unowned project schema {name}")


def stage_envelopes(bronze_root: str | Path) -> dict[str, bytes]:
    """One immutable JSONL file per complete capture prevents publishing partial captures."""
    captures = defaultdict(list)
    for event in read_completed(bronze_root):
        envelope = {k: event[k] for k in [
            "capture_id", "event_id", "fetched_at", "payload_sha256",
            "source", "endpoint", "frequency", "start", "end", "offset",
        ]}
        envelope["payload_json"] = canonical_json(event["payload"])
        captures[event["capture_id"]].append(envelope)
    return {
        capture_id: ("\n".join(canonical_json(e) for e in sorted(events, key=lambda e: e["offset"])) + "\n").encode()
        for capture_id, events in captures.items()
    }


def workspace_client(settings: Settings):
    if not settings.host:
        raise ValueError("DATABRICKS_HOST is required")
    from databricks.sdk import WorkspaceClient
    # No token: allow SDK unified authentication (e.g. CLI OAuth). Never log credentials.
    return WorkspaceClient(host=settings.host, token=settings.token or None)


def deploy_phase1(settings: Settings, bronze_root: str | Path, notebook: str | Path,
                  *, wait: bool = False) -> dict:
    from databricks.sdk.errors import ResourceAlreadyExists
    from databricks.sdk.service import jobs, workspace
    from databricks.sdk.service.catalog import VolumeType

    staged = stage_envelopes(bronze_root)  # Validate local integrity before remote mutations.
    client = workspace_client(settings)
    user = client.current_user.me().user_name
    if not user:
        raise ValueError("Databricks identity has no workspace user name")
    ensure_project_schemas(client, settings.catalog)
    try:
        client.volumes.create(catalog_name=settings.catalog, schema_name="jet_fuel_bronze",
                              name="landing", volume_type=VolumeType.MANAGED)
    except ResourceAlreadyExists:
        pass
    volume = f"/Volumes/{settings.catalog}/jet_fuel_bronze/landing"
    client.files.create_directory(f"{volume}/captures")
    for capture_id, content in staged.items():
        path = f"{volume}/captures/{capture_id}.jsonl"
        try:
            client.files.upload(path, io.BytesIO(content), overwrite=False)
        except ResourceAlreadyExists:
            existing = client.files.download(path)
            with existing.contents as stream:
                if stream.read() != content:
                    raise ValueError("Remote capture conflicts with immutable local content") from None
    folder = f"/Users/{user}/jet-fuel-hedge-engine"
    client.workspace.mkdirs(folder)
    remote = f"{folder}/phase1_pipeline"
    client.workspace.import_(path=remote, format=workspace.ImportFormat.SOURCE,
                             language=workspace.Language.PYTHON, overwrite=True,
                             content=base64.b64encode(Path(notebook).read_bytes()).decode())
    submitted = client.jobs.submit(
        run_name="jet-fuel-phase1-medallion", timeout_seconds=3600,
        tasks=[jobs.SubmitTask(
            task_key="bronze_silver", notebook_task=jobs.NotebookTask(
                notebook_path=remote, base_parameters={"catalog": settings.catalog},
                source=jobs.Source.WORKSPACE,
            ), timeout_seconds=3600,
        )],
    )
    run_id = submitted.run_id
    if wait:
        run = submitted.result(timeout=timedelta(minutes=60))
        state = run.state.result_state.value if run.state and run.state.result_state else "UNKNOWN"
        if state != "SUCCESS":
            raise RuntimeError(f"Phase 1 Databricks run {run_id} did not succeed ({state})")
    return {"run_id": run_id, "notebook_path": remote, "captures": len(staged),
            "volume": volume, "verified_success": wait}
