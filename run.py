"""Orchestrator: extract, transform, test, export. Also the CLI."""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from .config import settings
from .extract import extract_all
from .quality import QualityReport, run_suite
from .transform import discover_models, resolve_order, run_all, to_mermaid
from .warehouse import Warehouse

logger = logging.getLogger(__name__)

EXPORT_TABLES = (
    "mart_daily_revenue",
    "mart_customer_value",
    "mart_category_performance",
    "mart_channel_funnel",
)


@dataclass(slots=True)
class RunReport:
    started_at: str
    engine: str
    extracted: dict[str, int] = field(default_factory=dict)
    models: list[dict] = field(default_factory=list)
    quality: dict = field(default_factory=dict)
    exports: dict[str, int] = field(default_factory=dict)
    duration_s: float = 0.0
    status: str = "success"

    def as_dict(self) -> dict:
        return {
            "started_at": self.started_at,
            "engine": self.engine,
            "status": self.status,
            "duration_s": round(self.duration_s, 2),
            "extracted": self.extracted,
            "models": self.models,
            "quality": {
                k: v for k, v in self.quality.items() if k != "results"
            },
            "quality_failures": [
                r for r in self.quality.get("results", []) if not r["passed"]
            ],
            "exports": self.exports,
        }


def run_pipeline(*, skip_tests: bool = False, export: bool = True) -> RunReport:
    started = time.perf_counter()
    report = RunReport(
        started_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
        engine=settings.engine,
    )

    with Warehouse(settings.warehouse_path, engine=settings.engine) as warehouse:
        report.engine = warehouse.engine

        logger.info("--- extract ---")
        report.extracted = extract_all(warehouse, settings)

        logger.info("--- transform ---")
        results = run_all(warehouse, settings.sql_dir)
        report.models = [
            {
                "name": r.name,
                "layer": r.layer,
                "materialized": r.materialized,
                "rows": r.rows,
                "duration_ms": round(r.duration_ms, 1),
            }
            for r in results
        ]

        quality: QualityReport | None = None
        if not skip_tests:
            logger.info("--- data quality ---")
            quality = run_suite(warehouse, settings.models_dir / "schema.yml")
            report.quality = quality.as_dict()
            artifacts = Path(settings.artifacts_dir)
            quality.write(artifacts / "data_quality_report.json")
            logger.info("quality: %s", quality.summary_line())

        if export:
            logger.info("--- export ---")
            out_dir = Path(settings.artifacts_dir) / "marts"
            for table in EXPORT_TABLES:
                if warehouse.table_exists(table):
                    report.exports[table] = warehouse.export_csv(table, out_dir / f"{table}.csv")

    report.duration_s = time.perf_counter() - started

    if quality is not None and not quality.ok:
        report.status = "failed_quality"
        if settings.fail_on_quality_error:
            raise SystemExit(_finish(report, code=1))

    _finish(report)
    return report


def _finish(report: RunReport, code: int = 0) -> int:
    artifacts = Path(settings.artifacts_dir)
    artifacts.mkdir(parents=True, exist_ok=True)
    (artifacts / "run_report.json").write_text(json.dumps(report.as_dict(), indent=2), encoding="utf-8")
    print(json.dumps(report.as_dict(), indent=2))
    return code


def cmd_run(args: argparse.Namespace) -> int:
    run_pipeline(skip_tests=args.skip_tests, export=not args.no_export)
    return 0


def cmd_test(args: argparse.Namespace) -> int:
    with Warehouse(settings.warehouse_path, engine=settings.engine) as warehouse:
        report = run_suite(warehouse, settings.models_dir / "schema.yml")
    print(report.summary_line())
    for failure in report.errors + report.warnings:
        print(f"\n{failure.severity.upper()} {failure.name}: {failure.failing_rows} rows")
        print(f"  {failure.sql}")
    return 0 if report.ok else 1


def cmd_lineage(args: argparse.Namespace) -> int:
    models = resolve_order(discover_models(settings.sql_dir))
    if args.mermaid:
        print(to_mermaid(models))
    else:
        for position, model in enumerate(models, start=1):
            deps = ", ".join(model.depends_on) or "-"
            print(f"{position:>2}. [{model.layer:<7}] {model.name:<28} {model.materialized:<5} <- {deps}")
    return 0


def cmd_query(args: argparse.Namespace) -> int:
    with Warehouse(settings.warehouse_path, engine=settings.engine) as warehouse:
        rows = warehouse.query_dicts(args.sql)
    print(json.dumps(rows[: args.limit], indent=2, default=str))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="elt", description="Retail ELT pipeline")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="extract, transform, test, export")
    p_run.add_argument("--skip-tests", action="store_true")
    p_run.add_argument("--no-export", action="store_true")
    p_run.set_defaults(func=cmd_run)

    p_test = sub.add_parser("test", help="run the data quality suite only")
    p_test.set_defaults(func=cmd_test)

    p_lineage = sub.add_parser("lineage", help="print the model DAG")
    p_lineage.add_argument("--mermaid", action="store_true")
    p_lineage.set_defaults(func=cmd_lineage)

    p_query = sub.add_parser("query", help="run ad hoc SQL against the warehouse")
    p_query.add_argument("sql")
    p_query.add_argument("--limit", type=int, default=20)
    p_query.set_defaults(func=cmd_query)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)-7s %(message)s",
    )
    try:
        return args.func(args)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
