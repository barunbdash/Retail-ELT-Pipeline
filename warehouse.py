"""Thin warehouse wrapper.

DuckDB is the target. SQLite is kept as a fallback so the pipeline still runs
in a stripped-down environment, which also forces the SQL models to stay
dialect-neutral: no vendor date functions, no QUALIFY, no LATERAL. Date parts
are derived with `substr` over ISO-8601 strings in the staging layer.
"""

from __future__ import annotations

import csv
import json
import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Sequence

logger = logging.getLogger(__name__)


def duckdb_available() -> bool:
    try:
        import duckdb  # noqa: F401
    except ImportError:
        return False
    return True


class Warehouse:
    """One connection, a few conveniences, no ORM."""

    def __init__(self, path: Path, engine: str = "duckdb") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if engine == "duckdb" and duckdb_available():
            import duckdb

            self.engine = "duckdb"
            self.connection = duckdb.connect(str(self.path))
        else:
            if engine == "duckdb":
                logger.warning("duckdb not installed, falling back to sqlite")
            self.engine = "sqlite"
            self.connection = sqlite3.connect(str(self.path))
            self.connection.execute("PRAGMA journal_mode=WAL")

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "Warehouse":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def execute(self, sql: str, params: Sequence[Any] | None = None) -> None:
        self.connection.execute(sql, params or [])
        if self.engine == "sqlite":
            self.connection.commit()

    def execute_script(self, sql: str) -> None:
        """Run a multi-statement script. Splits on `;` outside string literals."""
        for statement in split_statements(sql):
            if statement.strip():
                self.execute(statement)

    def query(self, sql: str, params: Sequence[Any] | None = None) -> list[tuple]:
        cursor = self.connection.execute(sql, params or [])
        return list(cursor.fetchall())

    def query_dicts(self, sql: str, params: Sequence[Any] | None = None) -> list[dict]:
        cursor = self.connection.execute(sql, params or [])
        columns = [d[0] for d in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def scalar(self, sql: str, params: Sequence[Any] | None = None) -> Any:
        rows = self.query(sql, params)
        return rows[0][0] if rows and rows[0] else None

    def table_exists(self, name: str) -> bool:
        if self.engine == "duckdb":
            rows = self.query(
                "SELECT 1 FROM information_schema.tables WHERE table_name = ?", [name]
            )
        else:
            rows = self.query("SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name = ?", [name])
        return bool(rows)

    def row_count(self, table: str) -> int:
        return int(self.scalar(f"SELECT COUNT(*) FROM {table}") or 0)

    def load_csv(self, path: Path, table: str) -> int:
        """Land a CSV as an all-TEXT raw table. Typing happens in staging."""
        path = Path(path)
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            fieldnames = reader.fieldnames or []
            if not fieldnames:
                raise ValueError(f"{path} has no header row")
            rows = [tuple(row.get(name, "") for name in fieldnames) for row in reader]

        columns = ", ".join(f'"{name}" VARCHAR' for name in fieldnames)
        placeholders = ", ".join("?" for _ in fieldnames)
        self.execute(f"DROP TABLE IF EXISTS {table}")
        self.execute(f"CREATE TABLE {table} ({columns})")
        if rows:
            self.connection.executemany(
                f"INSERT INTO {table} VALUES ({placeholders})", rows
            )
            if self.engine == "sqlite":
                self.connection.commit()
        return len(rows)

    def load_jsonl(self, path: Path, table: str) -> int:
        path = Path(path)
        records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if not records:
            raise ValueError(f"{path} is empty")
        fieldnames = list(records[0])
        columns = ", ".join(f'"{name}" VARCHAR' for name in fieldnames)
        placeholders = ", ".join("?" for _ in fieldnames)
        self.execute(f"DROP TABLE IF EXISTS {table}")
        self.execute(f"CREATE TABLE {table} ({columns})")
        self.connection.executemany(
            f"INSERT INTO {table} VALUES ({placeholders})",
            [tuple(str(record.get(name, "")) for name in fieldnames) for record in records],
        )
        if self.engine == "sqlite":
            self.connection.commit()
        return len(records)

    def export_csv(self, table: str, path: Path) -> int:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        cursor = self.connection.execute(f"SELECT * FROM {table}")
        columns = [d[0] for d in cursor.description]
        rows = cursor.fetchall()
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(columns)
            writer.writerows(rows)
        return len(rows)


def split_statements(script: str) -> list[str]:
    """Split on semicolons, ignoring ones inside quotes or line comments."""
    statements: list[str] = []
    buffer: list[str] = []
    quote: str | None = None
    index = 0
    while index < len(script):
        char = script[index]
        if quote:
            buffer.append(char)
            if char == quote:
                quote = None
            index += 1
            continue
        if char in {"'", '"'}:
            quote = char
            buffer.append(char)
            index += 1
            continue
        if script.startswith("--", index):
            end = script.find("\n", index)
            index = len(script) if end == -1 else end + 1
            buffer.append("\n")
            continue
        if char == ";":
            statements.append("".join(buffer))
            buffer = []
            index += 1
            continue
        buffer.append(char)
        index += 1
    statements.append("".join(buffer))
    return [s.strip() for s in statements if s.strip()]


@contextmanager
def open_warehouse(path: Path, engine: str = "duckdb") -> Iterator[Warehouse]:
    warehouse = Warehouse(path, engine=engine)
    try:
        yield warehouse
    finally:
        warehouse.close()
