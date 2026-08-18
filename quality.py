"""Declarative data quality checks.

Tests are declared per model in `models/schema.yml` and compiled into SQL that
counts violating rows. A test that returns zero rows passes. That is the same
contract dbt uses, and it means every failure comes with a query you can paste
into a console to see the offending records.

Severity matters: `error` fails the run, `warn` is recorded and reported. Not
every anomaly should stop a pipeline at 03:00, but every anomaly should be
visible in the morning.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .warehouse import Warehouse

logger = logging.getLogger(__name__)

SEVERITIES = {"error", "warn"}


@dataclass(slots=True)
class TestSpec:
    model: str
    column: str | None
    test: str
    severity: str = "error"
    args: dict[str, Any] = field(default_factory=dict)

    @property
    def name(self) -> str:
        target = f"{self.model}.{self.column}" if self.column else self.model
        return f"{self.test}:{target}"


@dataclass(slots=True)
class TestResult:
    name: str
    model: str
    test: str
    severity: str
    passed: bool
    failing_rows: int
    duration_ms: float
    sql: str
    detail: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


def _quote(value: Any) -> str:
    if isinstance(value, (int, float)):
        return str(value)
    escaped = str(value).replace("'", "''")
    return f"'{escaped}'"


def compile_test(spec: TestSpec) -> str:
    """Turn a test declaration into a SQL query that returns violating rows."""
    model, column = spec.model, spec.column
    test = spec.test
    args = spec.args

    if test == "not_null":
        return f"SELECT * FROM {model} WHERE {column} IS NULL"

    if test == "unique":
        return (
            f"SELECT {column}, COUNT(*) AS n FROM {model} "
            f"WHERE {column} IS NOT NULL GROUP BY {column} HAVING COUNT(*) > 1"
        )

    if test == "accepted_values":
        values = ", ".join(_quote(v) for v in args["values"])
        return f"SELECT * FROM {model} WHERE {column} IS NOT NULL AND {column} NOT IN ({values})"

    if test == "relationships":
        to_model, to_column = args["to"], args["field"]
        return (
            f"SELECT c.{column} FROM {model} AS c "
            f"LEFT JOIN {to_model} AS p ON p.{to_column} = c.{column} "
            f"WHERE c.{column} IS NOT NULL AND p.{to_column} IS NULL"
        )

    if test == "non_negative":
        return f"SELECT * FROM {model} WHERE {column} < 0"

    if test == "between":
        low, high = args["min"], args["max"]
        return f"SELECT * FROM {model} WHERE {column} IS NOT NULL AND ({column} < {low} OR {column} > {high})"

    if test == "expression":
        # `condition` states what must hold; the query returns rows where it does not.
        return f"SELECT * FROM {model} WHERE NOT ({args['condition']})"

    if test == "row_count_between":
        low, high = args["min"], args["max"]
        return (
            f"SELECT COUNT(*) AS n FROM {model} "
            f"HAVING COUNT(*) < {low} OR COUNT(*) > {high}"
        )

    if test == "freshness":
        # Compares the model's max date against the max in a reference model,
        # so it works without a clock and stays deterministic in CI.
        reference = args.get("compare_to", model)
        max_lag = args.get("max_lag_days", 1)
        return (
            f"SELECT a.latest AS model_latest, b.latest AS reference_latest FROM "
            f"(SELECT MAX({column}) AS latest FROM {model}) AS a, "
            f"(SELECT MAX({args['reference_column']}) AS latest FROM {reference}) AS b "
            f"WHERE a.latest < b.latest AND {max_lag} >= 0"
        )

    raise ValueError(f"unknown test type: {test!r}")


def run_test(warehouse: Warehouse, spec: TestSpec) -> TestResult:
    sql = compile_test(spec)
    started = time.perf_counter()
    try:
        rows = warehouse.query(sql)
        failing = len(rows)
        detail = ""
        if failing:
            detail = f"first violation: {rows[0]}"
    except Exception as exc:
        return TestResult(
            name=spec.name,
            model=spec.model,
            test=spec.test,
            severity=spec.severity,
            passed=False,
            failing_rows=-1,
            duration_ms=(time.perf_counter() - started) * 1000,
            sql=sql,
            detail=f"test errored: {exc}",
        )

    return TestResult(
        name=spec.name,
        model=spec.model,
        test=spec.test,
        severity=spec.severity,
        passed=failing == 0,
        failing_rows=failing,
        duration_ms=(time.perf_counter() - started) * 1000,
        sql=sql,
        detail=detail,
    )


def load_specs(schema_path: Path) -> list[TestSpec]:
    """Parse `models/schema.yml`.

    PyYAML is used when installed. The fallback parser below covers the subset
    of YAML this file uses, so the pipeline has no hard dependency on it.
    """
    schema_path = Path(schema_path)
    text = schema_path.read_text(encoding="utf-8")
    try:
        import yaml

        document = yaml.safe_load(text)
    except ImportError:  # pragma: no cover - exercised by test_quality_yaml_fallback
        document = _parse_simple_yaml(text)

    specs: list[TestSpec] = []
    for model in document.get("models", []):
        model_name = model["name"]
        for test in model.get("tests", []):
            specs.append(_build_spec(model_name, None, test))
        for column in model.get("columns", []):
            for test in column.get("tests", []):
                specs.append(_build_spec(model_name, column["name"], test))
    return specs


def _build_spec(model: str, column: str | None, test: Any) -> TestSpec:
    if isinstance(test, str):
        return TestSpec(model=model, column=column, test=test)
    name = next(iter(test))
    args = dict(test[name] or {})
    severity = args.pop("severity", "error")
    if severity not in SEVERITIES:
        raise ValueError(f"severity must be one of {sorted(SEVERITIES)}, got {severity!r}")
    return TestSpec(model=model, column=column, test=name, severity=severity, args=args)


def _parse_simple_yaml(text: str) -> dict:
    """Minimal YAML reader covering the shapes used in models/schema.yml."""
    root: dict = {"models": []}
    model: dict | None = None
    column: dict | None = None
    context = None

    for raw_line in text.splitlines():
        line = raw_line.split(" #", 1)[0].rstrip()
        if not line.strip() or line.strip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        stripped = line.strip()

        if stripped == "models:":
            continue
        if stripped.startswith("- name:") and indent <= 4:
            model = {"name": stripped.split(":", 1)[1].strip(), "columns": [], "tests": []}
            root["models"].append(model)
            column = None
            context = None
            continue
        if model is None:
            continue
        if stripped in {"columns:", "tests:"}:
            context = stripped[:-1]
            if context == "tests" and indent >= 6 and column is not None:
                context = "column_tests"
            continue
        if stripped.startswith("- name:") and context == "columns":
            column = {"name": stripped.split(":", 1)[1].strip(), "tests": []}
            model["columns"].append(column)
            continue
        if stripped.startswith("- "):
            payload = stripped[2:].strip()
            target = column["tests"] if context == "column_tests" and column else model["tests"]
            if ":" in payload and not payload.startswith("{"):
                key, value = payload.split(":", 1)
                target.append({key.strip(): _parse_scalar(value.strip())})
            else:
                target.append(payload)
            continue
    return root


def _split_top_level(text: str, separator: str = ",") -> list[str]:
    """Split on a separator that is not nested inside {} [] or quotes."""
    parts: list[str] = []
    depth = 0
    quote: str | None = None
    buffer: list[str] = []
    for char in text:
        if quote:
            buffer.append(char)
            if char == quote:
                quote = None
            continue
        if char in {"'", '"'}:
            quote = char
            buffer.append(char)
            continue
        if char in "{[":
            depth += 1
        elif char in "}]":
            depth -= 1
        if char == separator and depth == 0:
            parts.append("".join(buffer))
            buffer = []
            continue
        buffer.append(char)
    parts.append("".join(buffer))
    return [p.strip() for p in parts if p.strip()]


def _parse_scalar(value: str) -> Any:
    """Handle the YAML scalars, flow sequences and flow mappings used here."""
    value = value.strip()
    if not value:
        return {}
    if value.startswith("{") and value.endswith("}"):
        mapping: dict[str, Any] = {}
        for item in _split_top_level(value[1:-1]):
            if ":" not in item:
                continue
            key, raw = item.split(":", 1)
            mapping[key.strip().strip("'\"")] = _parse_scalar(raw)
        return mapping
    if value.startswith("[") and value.endswith("]"):
        return [_parse_scalar(item) for item in _split_top_level(value[1:-1])]
    if (value.startswith("'") and value.endswith("'")) or (value.startswith('"') and value.endswith('"')):
        return value[1:-1]
    lowered = value.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    if lowered in {"null", "none", "~"}:
        return None
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value


@dataclass(slots=True)
class QualityReport:
    results: list[TestResult]

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def errors(self) -> list[TestResult]:
        return [r for r in self.results if not r.passed and r.severity == "error"]

    @property
    def warnings(self) -> list[TestResult]:
        return [r for r in self.results if not r.passed and r.severity == "warn"]

    @property
    def ok(self) -> bool:
        return not self.errors

    def as_dict(self) -> dict:
        return {
            "total": len(self.results),
            "passed": self.passed,
            "errors": len(self.errors),
            "warnings": len(self.warnings),
            "results": [r.as_dict() for r in self.results],
        }

    def write(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.as_dict(), indent=2), encoding="utf-8")

    def summary_line(self) -> str:
        return (
            f"{self.passed}/{len(self.results)} passed, "
            f"{len(self.errors)} error(s), {len(self.warnings)} warning(s)"
        )


def run_suite(warehouse: Warehouse, schema_path: Path) -> QualityReport:
    specs = load_specs(schema_path)
    results = []
    for spec in specs:
        result = run_test(warehouse, spec)
        level = logging.INFO if result.passed else (logging.ERROR if spec.severity == "error" else logging.WARNING)
        logger.log(
            level,
            "%-6s %-46s %s",
            "PASS" if result.passed else spec.severity.upper(),
            result.name,
            "" if result.passed else f"{result.failing_rows} failing rows",
        )
        results.append(result)
    return QualityReport(results)
