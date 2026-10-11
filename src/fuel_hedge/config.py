"""Explicit local configuration; credentials never appear in representations."""

from dataclasses import dataclass, field
import os
from pathlib import Path
import re
from urllib.parse import urlparse

ALLOWED_ENV = {
    "DATABRICKS_HOST", "DATABRICKS_TOKEN", "DATABRICKS_WAREHOUSE_ID",
    "DATABRICKS_CATALOG", "EIA_API_KEY",
}


def load_env(path: str | Path = ".env") -> None:
    """Read literal KEY=value pairs without shell expansion; process env takes precedence."""
    path = Path(path)
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if not sep or key.strip() not in ALLOWED_ENV:
            raise ValueError("Unsupported configuration entry in local environment file")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if value:
            os.environ.setdefault(key.strip(), value)


def identifier(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        raise ValueError("Catalog/schema names must be simple SQL identifiers")
    return value


@dataclass(frozen=True)
class Settings:
    host: str = ""
    token: str = field(default="", repr=False)
    warehouse_id: str = ""
    catalog: str = "workspace"
    eia_api_key: str = field(default="", repr=False)

    @classmethod
    def from_env(cls) -> "Settings":
        host = os.getenv("DATABRICKS_HOST", "").rstrip("/")
        if host:
            parsed = urlparse(host)
            valid_suffix = (".cloud.databricks.com", ".azuredatabricks.net", ".gcp.databricks.com")
            if (parsed.scheme != "https" or not parsed.hostname
                    or not parsed.hostname.endswith(valid_suffix)
                    or parsed.username or parsed.password or parsed.port
                    or parsed.path or parsed.query or parsed.fragment):
                raise ValueError("DATABRICKS_HOST must be an HTTPS Databricks workspace origin")
        return cls(
            host=host, token=os.getenv("DATABRICKS_TOKEN", ""),
            warehouse_id=os.getenv("DATABRICKS_WAREHOUSE_ID", ""),
            catalog=identifier(os.getenv("DATABRICKS_CATALOG", "workspace")),
            eia_api_key=os.getenv("EIA_API_KEY", ""),
        )
