import pytest

from pipeline.config import settings
from pipeline.transform import (
    CircularDependencyError,
    Model,
    discover_models,
    parse_model,
    resolve_order,
    to_mermaid,
)


def make(name, layer, deps, materialized="table"):
    return Model(name=name, layer=layer, path=None, sql="SELECT 1", materialized=materialized, depends_on=deps)


def test_header_is_parsed(tmp_path):
    path = tmp_path / "stg_thing.sql"
    path.write_text(
        "-- materialized: view\n-- description: a thing\n-- depends_on: raw_thing, other\n\nSELECT 1 AS x",
        encoding="utf-8",
    )
    model = parse_model(path)
    assert model.materialized == "view"
    assert model.description == "a thing"
    assert model.depends_on == ["raw_thing", "other"]
    assert model.select_sql == "SELECT 1 AS x"


def test_invalid_materialisation_is_rejected(tmp_path):
    path = tmp_path / "bad.sql"
    path.write_text("-- materialized: cube\nSELECT 1", encoding="utf-8")
    with pytest.raises(ValueError):
        parse_model(path)


def test_dependencies_come_before_dependents():
    models = [
        make("mart_a", "marts", ["fct_a"]),
        make("fct_a", "core", ["stg_a"]),
        make("stg_a", "staging", ["raw_a"]),
    ]
    order = [m.name for m in resolve_order(models)]
    assert order.index("stg_a") < order.index("fct_a") < order.index("mart_a")


def test_cycles_are_detected():
    models = [make("a", "core", ["b"]), make("b", "core", ["a"])]
    with pytest.raises(CircularDependencyError):
        resolve_order(models)


def test_ordering_is_deterministic():
    models = [make("c", "core", []), make("a", "core", []), make("b", "core", [])]
    assert [m.name for m in resolve_order(models)] == [m.name for m in resolve_order(models)]


def test_raw_sources_are_not_treated_as_models():
    order = resolve_order([make("stg_a", "staging", ["raw_a"])])
    assert [m.name for m in order] == ["stg_a"]


def test_mermaid_includes_every_edge():
    diagram = to_mermaid([make("fct_a", "core", ["stg_a"]), make("stg_a", "staging", ["raw_a"])])
    assert "stg_a --> fct_a" in diagram
    assert "raw_a" in diagram


def test_the_real_project_dag_resolves():
    models = resolve_order(discover_models(settings.sql_dir))
    names = [m.name for m in models]
    assert names.index("stg_orders") < names.index("fct_orders")
    assert names.index("dim_customer") < names.index("fct_orders")
    assert names.index("fct_orders") < names.index("mart_daily_revenue")
