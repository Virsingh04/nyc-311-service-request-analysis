from __future__ import annotations
import json
import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]

@dataclass(frozen=True)
class Settings:
    project: dict
    mysql_host: str
    mysql_port: int
    mysql_database: str
    mysql_user: str
    mysql_password: str
    socrata_token: str | None

def load_settings(path: str | Path | None = None) -> Settings:
    load_dotenv(ROOT / ".env")
    cfg_path = Path(path) if path else ROOT / "config/project.json"
    with cfg_path.open(encoding="utf-8") as f:
        project = json.load(f)
    return Settings(project, os.getenv("MYSQL_HOST", "127.0.0.1"), int(os.getenv("MYSQL_PORT", "3306")),
                    os.getenv("MYSQL_DATABASE", "nyc311_analytics"), os.getenv("MYSQL_USER", "nyc311_user"),
                    os.getenv("MYSQL_PASSWORD", ""), os.getenv("SOCRATA_APP_TOKEN") or None)
