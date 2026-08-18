import pytest

from pipeline.config import settings
from pipeline.quality import (
    QualityReport,
    TestSpec,
    _parse_scalar,
    _parse_simple_yaml,
    compile_test,
    load_specs,
    run_test,
)


@pytest.fixture()
def seeded(warehouse):
    warehouse.execute("CREATE TABLE parent AS SELECT 'a' AS id UNION ALL SELECT 'b'")
    warehouse.execute(
        "CREATE TABLE child AS "
        "SELECT 'a' AS parent_id, 5 AS amount UNION ALL "
        "SELECT 'a', -1 UNION ALL "
        "SELECT 'zz', 3"
    )
    return warehouse


def test_not_null_finds_nulls(warehouse):
    warehouse.execute("CREATE TABLE t AS SELECT 1 AS x UNION ALL SELECT NULL")
    result = run_test(warehouse, TestSpec("t", "x", "not_null"))
    assert not result.passed and result.failing_rows == 1


def test_unique_finds_duplicates(warehouse):
    warehouse.execute("CREATE TABLE t AS SELECT 1 AS x UNION ALL SELECT 1 UNION ALL SELECT 2")
    assert run_test(warehouse, TestSpec("t", "x", "unique")).failing_rows == 1


def test_relationships_finds_orphans(seeded):
    result = run_test(seeded, TestSpec("child", "parent_id", "relationships", args={"to": "parent", "field": "id"}))
    assert result.failing_rows == 1


def test_non_negative_finds_negatives(seeded):
    assert run_test(seeded, TestSpec("child", "amount", "non_negative")).failing_rows == 1


def test_accepted_values_passes_when_clean(warehouse):
    warehouse.execute("CREATE TABLE t AS SELECT 'eur' AS c UNION ALL SELECT 'usd'")
    spec = TestSpec("t", "c", "accepted_values", args={"values": ["eur", "usd"]})
    assert run_test(warehouse, spec).passed


def test_expression_test_flags_broken_arithmetic(warehouse):
    warehouse.execute("CREATE TABLE t AS SELECT 10.0 AS gross, 2.0 AS disc, 7.0 AS net")
    spec = TestSpec("t", None, "expression", args={"condition": "ABS(gross - disc - net) < 0.05"})
    assert not run_test(warehouse, spec).passed


def test_row_count_between_bounds(warehouse):
    warehouse.execute("CREATE TABLE t AS SELECT 1 AS x UNION ALL SELECT 2")
    assert run_test(warehouse, TestSpec("t", None, "row_count_between", args={"min": 1, "max": 5})).passed
    assert not run_test(warehouse, TestSpec("t", None, "row_count_between", args={"min": 10, "max": 20})).passed


def test_a_test_against_a_missing_table_fails_loudly(warehouse):
    result = run_test(warehouse, TestSpec("does_not_exist", "x", "not_null"))
    assert not result.passed and "errored" in result.detail


def test_unknown_test_type_is_rejected():
    with pytest.raises(ValueError):
        compile_test(TestSpec("t", "x", "teleport"))


def test_string_values_are_escaped_not_injected():
    sql = compile_test(TestSpec("t", "c", "accepted_values", args={"values": ["o'brien"]}))
    assert "o''brien" in sql


def test_warn_severity_does_not_fail_the_report(warehouse):
    warehouse.execute("CREATE TABLE t AS SELECT NULL AS x")
    report = QualityReport([run_test(warehouse, TestSpec("t", "x", "not_null", severity="warn"))])
    assert report.ok
    assert len(report.warnings) == 1


def test_error_severity_fails_the_report(warehouse):
    warehouse.execute("CREATE TABLE t AS SELECT NULL AS x")
    report = QualityReport([run_test(warehouse, TestSpec("t", "x", "not_null"))])
    assert not report.ok


def test_invalid_severity_is_rejected(tmp_path):
    path = tmp_path / "schema.yml"
    path.write_text(
        "models:\n  - name: t\n    columns:\n      - name: x\n        tests:\n"
        "          - not_null: {severity: shout}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        load_specs(path)


def test_flow_scalars_parse():
    assert _parse_scalar("{min: 1, max: 4}") == {"min": 1, "max": 4}
    assert _parse_scalar("[a, b, c]") == ["a", "b", "c"]
    assert _parse_scalar("0.5") == 0.5


def test_yaml_fallback_matches_the_project_schema():
    text = (settings.models_dir / "schema.yml").read_text(encoding="utf-8")
    parsed = _parse_simple_yaml(text)
    names = {m["name"] for m in parsed["models"]}
    assert {"stg_orders", "fct_orders", "mart_daily_revenue"} <= names


def test_project_schema_loads_and_compiles():
    specs = load_specs(settings.models_dir / "schema.yml")
    assert len(specs) > 40
    for spec in specs:
        assert compile_test(spec).lower().startswith("select")
