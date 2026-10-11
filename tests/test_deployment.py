import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from fuel_hedge.bronze import capture
from fuel_hedge.databricks import PROJECT_MARKER, SCHEMAS, ensure_project_schemas, stage_envelopes
from fuel_hedge.eia import ENDPOINT


class StagingTests(unittest.TestCase):
    def test_completed_capture_becomes_one_immutable_jsonl_file(self):
        class Client:
            def pages(self, start, end):
                for offset in [0, 1]:
                    yield {"source": "EIA", "endpoint": ENDPOINT, "frequency": "daily",
                           "start": start, "end": end, "offset": offset,
                           "fetched_at": "2025-01-01T00:00:00+00:00",
                           "payload": {"response": {"data": [{"period": "2025-01-01"}]}}}

        with tempfile.TemporaryDirectory() as directory:
            capture(Client(), "2025-01-01", "2025-01-02", directory)
            staged = stage_envelopes(directory)
            self.assertEqual(len(staged), 1)
            lines = next(iter(staged.values())).splitlines()
            self.assertEqual([json.loads(line)["offset"] for line in lines], [0, 1])
            self.assertIn("payload_json", json.loads(lines[0]))
            self.assertNotIn("payload", json.loads(lines[0]))
            self.assertEqual(stage_envelopes(directory), staged)

    def test_owned_schemas_only(self):
        client = SimpleNamespace(schemas=Mock())
        client.schemas.get.return_value = SimpleNamespace(comment="another project")
        with self.assertRaisesRegex(ValueError, "unowned"):
            ensure_project_schemas(client, "workspace")
        client.schemas.create.assert_not_called()
        client.schemas.get.return_value.comment = PROJECT_MARKER
        ensure_project_schemas(client, "workspace")
        self.assertEqual(client.schemas.get.call_args.args[0], f"workspace.{SCHEMAS[-1]}")
        self.assertTrue(all(name.startswith("jet_fuel_") for name in SCHEMAS))

    def test_notebook_validates_candidates_before_publication(self):
        # Regression guard for publication order; actual SQL is verified in Databricks.
        notebook = Path(__file__).resolve().parents[1] / "notebooks/phase1_pipeline.py"
        source = notebook.read_text()
        self.assertLess(source.index('if weekly.where'),
                        source.index('CREATE OR REPLACE TABLE jet_fuel_silver.fuel_prices'))
        self.assertIn("pipeline_run_id", source)
        self.assertIn("status='SUCCESS'", source)


if __name__ == "__main__":
    unittest.main()
