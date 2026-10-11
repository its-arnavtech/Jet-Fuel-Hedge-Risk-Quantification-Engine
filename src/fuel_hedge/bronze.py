"""Append-only page events; completed manifests define publishable captures."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from uuid import uuid4

from .eia import EIAClient


def canonical_json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def capture(client: EIAClient, start: str, end: str, root: str | Path) -> Path:
    root = Path(root)
    events = root / "events"
    manifests = root / "manifests"
    events.mkdir(parents=True, exist_ok=True)
    manifests.mkdir(parents=True, exist_ok=True)
    capture_id = str(uuid4())
    pages = []
    count = 0
    for page in client.pages(start, end):
        payload_json = canonical_json(page["payload"])
        event = {**page, "capture_id": capture_id, "event_id": str(uuid4()),
                 "payload_sha256": hashlib.sha256(payload_json.encode()).hexdigest()}
        path = events / f'{event["event_id"]}.json'
        with path.open("x", encoding="utf-8") as stream:
            stream.write(canonical_json(event))
        pages.append(path.name)
        count += len(page["payload"]["response"]["data"])
    if not pages:
        raise ValueError("A capture must contain at least one page")
    manifest = {"capture_id": capture_id, "status": "complete", "pages": pages,
                "observation_count": count, "start": start, "end": end,
                "completed_at": datetime.now(timezone.utc).isoformat()}
    path = manifests / f"{capture_id}.json"
    temporary = path.with_suffix(".pending")
    with temporary.open("x", encoding="utf-8") as stream:
        stream.write(canonical_json(manifest))
    temporary.replace(path)
    return path


def read_completed(root: str | Path) -> list[dict]:
    root = Path(root)
    result = []
    for path in sorted((root / "manifests").glob("*.json")):
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if manifest.get("status") != "complete":
            continue
        capture_rows = []
        for name in manifest["pages"]:
            if Path(name).name != name or not name.endswith(".json"):
                raise ValueError("Invalid Bronze manifest event path")
            event = json.loads((root / "events" / name).read_text(encoding="utf-8"))
            actual = hashlib.sha256(canonical_json(event["payload"]).encode()).hexdigest()
            if actual != event["payload_sha256"] or event["capture_id"] != manifest["capture_id"]:
                raise ValueError("Bronze capture integrity check failed")
            capture_rows.append(event)
        if sum(len(e["payload"]["response"]["data"]) for e in capture_rows) != manifest["observation_count"]:
            raise ValueError("Bronze observation count mismatch")
        result.extend(capture_rows)
    if not result:
        raise ValueError("No completed Bronze captures found")
    return result
