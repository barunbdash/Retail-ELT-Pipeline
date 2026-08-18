import pytest

from pipeline.warehouse import split_statements


def test_split_statements_ignores_semicolons_in_strings():
    sql = "SELECT ';' AS a; SELECT 2"
    assert len(split_statements(sql)) == 2


def test_split_statements_ignores_line_comments():
    sql = "-- a; comment\nSELECT 1;\nSELECT 2"
    assert len(split_statements(sql)) == 2


def test_split_statements_drops_empty_fragments():
    assert split_statements("SELECT 1;;;") == ["SELECT 1"]


def test_load_csv_lands_every_row_as_text(warehouse, tmp_path):
    path = tmp_path / "in.csv"
    path.write_text("a,b\n1,x\n2,\n3,z\n", encoding="utf-8")
    assert warehouse.load_csv(path, "raw_t") == 3
    assert warehouse.row_count("raw_t") == 3
    assert warehouse.query("SELECT b FROM raw_t WHERE a = '2'")[0][0] == ""


def test_load_csv_rejects_a_headerless_file(warehouse, tmp_path):
    path = tmp_path / "empty.csv"
    path.write_text("", encoding="utf-8")
    with pytest.raises(ValueError):
        warehouse.load_csv(path, "raw_t")


def test_table_exists_is_accurate(warehouse):
    assert not warehouse.table_exists("nope")
    warehouse.execute("CREATE TABLE yes (x INTEGER)")
    assert warehouse.table_exists("yes")


def test_export_csv_roundtrips(warehouse, tmp_path):
    warehouse.execute("CREATE TABLE t AS SELECT 1 AS a, 'b' AS b")
    out = tmp_path / "out" / "t.csv"
    assert warehouse.export_csv("t", out) == 1
    assert out.read_text(encoding="utf-8").splitlines()[0] == "a,b"


def test_sqlite_fallback_runs_the_same_api(sqlite_warehouse):
    sqlite_warehouse.execute("CREATE TABLE t AS SELECT 1 AS a")
    assert sqlite_warehouse.engine == "sqlite"
    assert sqlite_warehouse.row_count("t") == 1
