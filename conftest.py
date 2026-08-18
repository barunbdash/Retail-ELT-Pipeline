import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from pipeline.warehouse import Warehouse  # noqa: E402


@pytest.fixture()
def warehouse(tmp_path):
    with Warehouse(tmp_path / "test.duckdb") as wh:
        yield wh


@pytest.fixture()
def sqlite_warehouse(tmp_path):
    with Warehouse(tmp_path / "test.sqlite", engine="sqlite") as wh:
        yield wh
