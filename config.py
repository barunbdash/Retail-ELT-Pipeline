"""Paths and knobs, all overridable from the environment."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(slots=True)
class Settings:
    raw_dir: Path = field(
        default_factory=lambda: Path(os.getenv("ELT_RAW_DIR", str(REPO_ROOT / "data" / "raw")))
    )
    warehouse_path: Path = field(
        default_factory=lambda: Path(
            os.getenv("ELT_WAREHOUSE", str(REPO_ROOT / "data" / "warehouse.duckdb"))
        )
    )
    sql_dir: Path = field(default_factory=lambda: Path(os.getenv("ELT_SQL_DIR", str(REPO_ROOT / "sql"))))
    models_dir: Path = field(
        default_factory=lambda: Path(os.getenv("ELT_MODELS_DIR", str(REPO_ROOT / "models")))
    )
    artifacts_dir: Path = field(
        default_factory=lambda: Path(os.getenv("ELT_ARTIFACTS_DIR", str(REPO_ROOT / "artifacts")))
    )
    # duckdb when available; sqlite keeps the pipeline runnable anywhere.
    engine: str = field(default_factory=lambda: os.getenv("ELT_ENGINE", "duckdb"))
    fail_on_quality_error: bool = field(
        default_factory=lambda: os.getenv("ELT_FAIL_ON_QUALITY_ERROR", "1") not in {"0", "false", "False"}
    )


settings = Settings()
