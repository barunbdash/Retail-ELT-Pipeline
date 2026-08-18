"""Airflow orchestration for the retail ELT pipeline.

The DAG deliberately mirrors the layers of the warehouse rather than wrapping
the whole run in one task. Splitting extract, staging, core, marts and the
quality suite into separate tasks means a failure tells you *where* it broke
from the Airflow UI alone, and a retry re-runs only the failed layer instead of
reloading every source file.

The quality suite runs twice: once after staging, so a bad source file fails
before it can propagate into the dimensional model, and once at the end across
everything. Catching it early is the difference between a five-minute rerun and
a full rebuild.

This module imports nothing from Airflow at module scope beyond the DAG API, so
`pytest` can import and lint it without Airflow installed being a hard failure.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

from airflow import DAG
from airflow.operators.empty import EmptyOperator
from airflow.operators.python import PythonOperator

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from pipeline.config import settings  # noqa: E402
from pipeline.extract import extract_all  # noqa: E402
from pipeline.quality import run_suite  # noqa: E402
from pipeline.transform import discover_models, resolve_order, run_model  # noqa: E402
from pipeline.warehouse import Warehouse  # noqa: E402

DEFAULT_ARGS = {
    "owner": "data-engineering",
    "depends_on_past": False,
    "email_on_failure": True,
    "retries": 2,
    # Object storage throttling is the usual transient failure here, and it
    # clears in seconds. A short exponential backoff handles it without a page.
    "retry_delay": timedelta(minutes=3),
    "retry_exponential_backoff": True,
    "max_retry_delay": timedelta(minutes=20),
    "execution_timeout": timedelta(hours=1),
}


def _warehouse() -> Warehouse:
    return Warehouse(settings.warehouse_path, engine=settings.engine)


def task_extract(**context) -> dict:
    with _warehouse() as warehouse:
        counts = extract_all(warehouse, settings)
    context["ti"].xcom_push(key="row_counts", value=counts)
    return counts


def _run_layer(layer: str) -> dict:
    models = [m for m in resolve_order(discover_models(settings.sql_dir)) if m.layer == layer]
    with _warehouse() as warehouse:
        return {m.name: run_model(warehouse, m).rows for m in models}


def task_build_staging(**_) -> dict:
    return _run_layer("staging")


def task_build_core(**_) -> dict:
    return _run_layer("core")


def task_build_marts(**_) -> dict:
    return _run_layer("marts")


def _quality_gate(stage: str) -> dict:
    """Run the suite and fail the task on any error-severity violation."""
    with _warehouse() as warehouse:
        report = run_suite(warehouse, settings.models_dir / "schema.yml")

    artifacts = Path(settings.artifacts_dir)
    report.write(artifacts / f"data_quality_{stage}.json")

    if not report.ok:
        failures = "\n".join(
            f"  {r.name}: {r.failing_rows} failing rows\n    {r.sql}" for r in report.errors
        )
        raise ValueError(f"data quality failed at {stage}:\n{failures}")
    return {"stage": stage, "summary": report.summary_line()}


def task_test_staging(**_) -> dict:
    return _quality_gate("staging")


def task_test_final(**_) -> dict:
    return _quality_gate("final")


def task_export_marts(**_) -> dict:
    out_dir = Path(settings.artifacts_dir) / "marts"
    exports = {}
    with _warehouse() as warehouse:
        for table in (
            "mart_daily_revenue",
            "mart_customer_value",
            "mart_category_performance",
            "mart_channel_funnel",
        ):
            if warehouse.table_exists(table):
                exports[table] = warehouse.export_csv(table, out_dir / f"{table}.csv")
    return exports


with DAG(
    dag_id="retail_elt",
    description="Raw source files to a tested dimensional warehouse",
    default_args=DEFAULT_ARGS,
    schedule="0 3 * * *",
    start_date=datetime(2024, 1, 1),
    # Backfilling this pipeline would reload the same full extracts repeatedly,
    # so catchup stays off. A genuinely incremental version would turn it on.
    catchup=False,
    max_active_runs=1,
    tags=["elt", "warehouse", "duckdb"],
) as dag:
    start = EmptyOperator(task_id="start")

    extract = PythonOperator(task_id="extract", python_callable=task_extract)
    build_staging = PythonOperator(task_id="build_staging", python_callable=task_build_staging)
    test_staging = PythonOperator(task_id="test_staging", python_callable=task_test_staging)
    build_core = PythonOperator(task_id="build_core", python_callable=task_build_core)
    build_marts = PythonOperator(task_id="build_marts", python_callable=task_build_marts)
    test_final = PythonOperator(task_id="test_final", python_callable=task_test_final)
    export = PythonOperator(task_id="export_marts", python_callable=task_export_marts)

    end = EmptyOperator(task_id="end")

    start >> extract >> build_staging >> test_staging >> build_core >> build_marts >> test_final >> export >> end
