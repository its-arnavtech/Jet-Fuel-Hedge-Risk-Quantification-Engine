"""Validate Microsoft schemas, model bindings and headline SQL contract.

Does not claim to execute DAX. Native model parse and DAX execution are separate gates.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import urllib.parse
import urllib.request

import jsonschema

from build_powerbi import MEASURES, PROJECT, REPORT, measures


def fetch_schema(url):
    url = url.replace("/schema.embedded.json", "/schema-embedded.json")
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in {"developer.microsoft.com", "raw.githubusercontent.com", "vega.github.io"}:
        raise ValueError("Schema must come from official Microsoft HTTPS sources")
    if parsed.hostname == "raw.githubusercontent.com" and not parsed.path.startswith("/microsoft/"):
        raise ValueError("Only Microsoft schema repository allowed")
    cache = Path(".tmp/powerbi_schema_cache")
    cache.mkdir(parents=True, exist_ok=True)
    path = cache/(hashlib.sha256(url.encode()).hexdigest()+".json")
    if not path.exists():
        with urllib.request.urlopen(url, timeout=30) as response:
            path.write_bytes(response.read())
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    measures()
    validations = []
    for path in sorted(PROJECT.rglob("*")):
        if path.suffix not in {".json", ".pbip", ".pbir", ".pbism"} or ".pbi" in path.parts:
            continue
        instance = json.loads(path.read_text(encoding="utf-8"))
        schema = fetch_schema(instance["$schema"])
        # RefResolver retains each schema's base URI, including relative embedded references.
        resolver = jsonschema.RefResolver(base_uri=instance["$schema"], referrer=schema,
            handlers={"https": fetch_schema})
        jsonschema.Draft7Validator(schema, resolver=resolver).validate(instance)
        validations.append(str(path.relative_to(PROJECT)))
    tables = {}
    for path in (PROJECT/"JetFuelHedgeRisk.SemanticModel/definition/tables").glob("*.tmdl"):
        text = path.read_text(encoding="utf-8")
        tables[path.stem] = set(re.findall(r"(?m)^\tcolumn (?:'([^']+)'|([^\s]+))", text))
        tables[path.stem] = {a or b for a, b in tables[path.stem]}
    bindings = 0
    layered_specs = 0
    for path in REPORT.glob("definition/pages/*/visuals/*/visual.json"):
        visual = json.loads(path.read_text(encoding="utf-8"))
        aliases = {}
        def walk(value):
            nonlocal bindings
            if isinstance(value, dict):
                if "From" in value:
                    aliases.update({source["Name"]: source["Entity"] for source in value["From"] if "Entity" in source})
                for kind in ["Column", "Measure"]:
                    if kind in value:
                        obj = value[kind]
                        source = obj["Expression"]["SourceRef"]
                        table, name = source.get("Entity", aliases.get(source.get("Source"))), obj["Property"]
                        if kind == "Measure":
                            if table != "_Measures" or name not in MEASURES:
                                raise ValueError(f"Unknown measure: {table}.{name}")
                        elif name not in tables.get(table, set()):
                            raise ValueError(f"Unknown column: {table}.{name}")
                        bindings += 1
                for child in value.values():
                    walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)
        walk(visual)
        if visual["visual"]["visualType"].startswith("deneb"):
            value = visual["visual"]["objects"]["vega"][0]["properties"]["jsonSpec"]["expr"]["Literal"]["Value"]
            spec = json.loads(value[1:-1].replace("''", "'"))
            spec_schema = fetch_schema(spec["$schema"])
            jsonschema.Draft7Validator(spec_schema).validate(spec)
            layered_specs += 1
        if "general" not in visual["visual"]["visualContainerObjects"]:
            raise ValueError("Every visual requires alt text")
    titles = [name for name in MEASURES if name.startswith("Title ")]
    if len(titles) != 15:
        raise ValueError("Exactly 15 headline units required")
    evidence = dict(json_schemas_passed=True, json_files=len(validations), schema_validated_files=validations,
                    field_bindings_checked=bindings, layered_specs_validated=layered_specs, titles=len(titles),
                    tmdl_parsed=False, dax_executed=False, desktop_rendered=False)
    if args.live:
        from fuel_hedge.config import Settings, load_env
        from fuel_hedge.databricks import workspace_client
        from verify_phase1 import query
        load_env()
        settings = Settings.from_env()
        client = workspace_client(settings)
        statement = (Path("powerbi/tests/headline_numbers.sql")).read_text(encoding="utf-8")
        statement = statement.replace("jet_fuel_gold.", settings.catalog+".jet_fuel_gold.")
        result = query(client, settings.warehouse_id, statement)
        expected = json.loads(Path("docs/evidence/phase5_verification.json").read_text(encoding="utf-8"))["findings"]
        import numpy as np
        for row in result.to_dict("records"):
            value = expected[row["finding"]]
            for key in row["metric"].split("."):
                value = value[key]
            np.testing.assert_allclose(float(row["value"]), value, atol=1e-9, rtol=0)
        evidence["sql_headline_numbers_checked"] = len(result)
    out = Path("docs/evidence/powerbi_contract.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print(json.dumps({k:v for k,v in evidence.items() if k != "schema_validated_files"}, indent=2))


if __name__ == "__main__":
    main()
