"""Local ingestion and transformation commands."""

import argparse
import json
from pathlib import Path

from .bronze import capture, read_completed
from .config import Settings, load_env
from .eia import EIAClient, EIAError
from .silver import build_silver, weekly_prices


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="EIA jet fuel medallion pipeline")
    parser.add_argument("--env-file", default=".env")
    sub = parser.add_subparsers(dest="command", required=True)
    ingest = sub.add_parser("ingest")
    ingest.add_argument("--start", required=True)
    ingest.add_argument("--end", required=True)
    ingest.add_argument("--bronze", default="artifacts/bronze")
    silver = sub.add_parser("silver")
    silver.add_argument("--bronze", default="artifacts/bronze")
    silver.add_argument("--output", default="artifacts/silver")
    args = parser.parse_args(argv)
    try:
        load_env(args.env_file)
        settings = Settings.from_env()
        if args.command == "ingest":
            manifest = capture(EIAClient(settings.eia_api_key), args.start, args.end, args.bronze)
            print(f"Completed Bronze capture: {manifest}")
        elif args.command == "silver":
            prices, quarantine = build_silver(read_completed(args.bronze))
            weekly = weekly_prices(prices)
            output = Path(args.output)
            output.mkdir(parents=True, exist_ok=True)
            prices.to_csv(output / "fuel_prices.csv", index=False)
            weekly.to_csv(output / "weekly_fuel_prices.csv", index=False)
            quarantine.to_json(output / "quarantine.json", orient="records", date_format="iso")
            (output / "quality.json").write_text(json.dumps({
                "daily_rows": len(prices), "weekly_rows": len(weekly),
                "quarantined_rows": len(quarantine), "source": "EIA", "is_synthetic": False,
                "min_date": str(prices.price_date.min().date()),
                "max_date": str(prices.price_date.max().date()),
            }, indent=2), encoding="utf-8")
            print(f"Silver rows: {len(prices)} daily, {len(weekly)} weekly; rejected: {len(quarantine)}")
    except (ValueError, EIAError) as exc:
        parser.exit(1, f"Pipeline failed: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
