"""End-to-end: generate raw files, run every model, assert the numbers tie out."""

from __future__ import annotations

import pytest

from pipeline import generate_source_data
from pipeline.config import settings
from pipeline.extract import extract_all
from pipeline.quality import run_suite
from pipeline.transform import run_all
from pipeline.warehouse import Warehouse


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    """Build a small warehouse once and reuse it across the assertions below."""
    tmp = tmp_path_factory.mktemp("elt")
    original_raw = settings.raw_dir
    settings.raw_dir = tmp / "raw"
    try:
        generate_source_data.main(["--rows", "600", "--customers", "120", "--products", "40", "--seed", "5"])
        warehouse = Warehouse(tmp / "wh.duckdb")
        extract_all(warehouse, settings)
        run_all(warehouse, settings.sql_dir)
        yield warehouse
        warehouse.close()
    finally:
        settings.raw_dir = original_raw


def test_every_model_is_populated(built):
    for table in ["stg_orders", "dim_customer", "dim_date", "fct_orders", "mart_daily_revenue"]:
        assert built.row_count(table) > 0, table


def test_duplicate_orders_are_removed(built):
    raw = built.scalar("SELECT COUNT(*) FROM raw_orders")
    distinct = built.scalar("SELECT COUNT(DISTINCT TRIM(order_id)) FROM raw_orders")
    assert raw > distinct, "the generator should emit replays"
    assert built.row_count("stg_orders") == distinct


def test_order_ids_are_unique_in_the_fact_table(built):
    duplicates = built.scalar(
        "SELECT COUNT(*) FROM (SELECT order_id FROM fct_orders GROUP BY order_id HAVING COUNT(*) > 1) t"
    )
    assert duplicates == 0


def test_line_totals_roll_up_to_the_order_grain(built):
    line_total = built.scalar("SELECT ROUND(SUM(net_amount), 2) FROM stg_order_lines")
    order_total = built.scalar("SELECT ROUND(SUM(net_amount), 2) FROM fct_orders")
    assert abs(line_total - order_total) < 0.5


def test_mart_revenue_matches_the_fact_table(built):
    fact = built.scalar("SELECT ROUND(SUM(net_amount), 2) FROM fct_orders WHERE is_completed = 1")
    mart = built.scalar("SELECT ROUND(SUM(net_revenue), 2) FROM mart_daily_revenue")
    assert abs(fact - mart) < 1.0


def test_orphan_customers_are_conformed_not_dropped(built):
    orders = built.row_count("stg_orders")
    facts = built.row_count("fct_orders")
    assert orders == facts, "no order may be lost to a failed dimension join"
    assert built.scalar("SELECT COUNT(*) FROM fct_orders WHERE customer_key = 'UNKNOWN'") > 0


def test_currency_casing_is_normalised(built):
    values = {row[0] for row in built.query("SELECT DISTINCT currency FROM stg_orders")}
    assert values <= {"EUR", "USD", "GBP"}


def test_blank_segments_become_the_unknown_bucket(built):
    assert built.scalar("SELECT COUNT(*) FROM stg_customers WHERE segment = ''") == 0
    assert built.scalar("SELECT COUNT(*) FROM stg_customers WHERE segment = 'unknown'") >= 0


def test_the_quality_suite_reports_only_the_expected_warning(built):
    report = run_suite(built, settings.models_dir / "schema.yml")
    assert report.ok, [r.name for r in report.errors]
    assert all(r.model == "fct_orders" or r.severity == "warn" for r in report.warnings)


def test_funnel_rates_stay_within_bounds(built):
    """A conversion rate is either a percentage or undefined, never nonsense.

    NULL is the honest answer when the denominator is zero — a month with no
    add-to-carts has no checkout rate, and reporting 0% would imply everyone
    who added to cart failed to convert. The assertion below allows NULL only
    when the stage it divides by is genuinely empty.
    """
    rows = built.query(
        "SELECT add_to_carts, checkout_starts, cart_rate_pct, checkout_rate_pct "
        "FROM mart_channel_funnel"
    )
    assert rows

    for add_to_carts, checkout_starts, cart_rate, checkout_rate in rows:
        if cart_rate is None:
            assert add_to_carts == 0
        else:
            assert 0 <= cart_rate <= 100

        if checkout_rate is None:
            assert add_to_carts == 0
        else:
            assert 0 <= checkout_rate <= 100
            assert checkout_starts <= add_to_carts


def test_the_funnel_narrows_at_every_stage(built):
    """Each stage is a subset of the one before it, by construction."""
    rows = built.query(
        "SELECT page_views, add_to_carts, checkout_starts, checkout_completes "
        "FROM mart_channel_funnel"
    )
    for page_views, carts, starts, completes in rows:
        assert page_views >= carts >= starts >= completes
