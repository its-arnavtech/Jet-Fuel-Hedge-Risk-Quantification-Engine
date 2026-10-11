"""Run from repository root after pip install -e '.[databricks]'."""

import argparse
import json
from pathlib import Path

from fuel_hedge.config import Settings, load_env
from fuel_hedge.databricks import deploy_phase1


def main():
    parser = argparse.ArgumentParser(description="Stage real EIA captures and run Free Edition Phase 1")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--bronze", default="artifacts/bronze")
    parser.add_argument("--wait", action="store_true")
    args = parser.parse_args()
    load_env(args.env_file)
    result = deploy_phase1(Settings.from_env(), args.bronze,
                           Path(__file__).resolve().parents[1] / "notebooks/phase1_pipeline.py",
                           wait=args.wait)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
