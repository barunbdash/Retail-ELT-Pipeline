"""Read the SQL models, resolve their dependency graph, run them in order.

A model is a `.sql` file holding a single SELECT plus a small header:

    -- materialized: table | view
    -- description: what this model is for
    -- depends_on: stg_orders, dim_customer

Materialisation is applied by this runner rather than written into each file,
which keeps the SQL portable and makes `view` versus `table` a one-word change.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from .warehouse import Warehouse

logger = logging.getLogger(__name__)

_MATERIALIZED = re.compile(r"^--\s*materialized:\s*(\w+)", re.MULTILINE)
_DESCRIPTION = re.compile(r"^--\s*description:\s*(.+)$", re.MULTILINE)
_DEPENDS_ON = re.compile(r"^--\s*depends_on:\s*(.+)$", re.MULTILINE)

LAYER_ORDER = {"staging": 0, "core": 1, "marts": 2}


class CircularDependencyError(RuntimeError):
    pass


@dataclass(slots=True)
class Model:
    name: str
    layer: str
    path: Path
    sql: str
    materialized: str = "table"
    description: str = ""
    depends_on: list[str] = field(default_factory=list)

    @property
    def select_sql(self) -> str:
        """The body with the header comments stripped off."""
        lines = [
            line
            for line in self.sql.splitlines()
            if not re.match(r"^--\s*(materialized|description|depends_on):", line)
        ]
        return "\n".join(lines).strip()


def parse_model(path: Path) -> Model:
    sql = path.read_text(encoding="utf-8")
    materialized = (_MATERIALIZED.search(sql).group(1).strip() if _MATERIALIZED.search(sql) else "table")
    if materialized not in {"table", "view"}:
        raise ValueError(f"{path.name}: materialized must be 'table' or 'view', got {materialized!r}")
    description = _DESCRIPTION.search(sql)
    depends = _DEPENDS_ON.search(sql)
    return Model(
        name=path.stem,
        layer=path.parent.name,
        path=path,
        sql=sql,
        materialized=materialized,
        description=description.group(1).strip() if description else "",
        depends_on=[d.strip() for d in depends.group(1).split(",") if d.strip()] if depends else [],
    )


def discover_models(sql_dir: Path) -> list[Model]:
    sql_dir = Path(sql_dir)
    if not sql_dir.exists():
        raise FileNotFoundError(f"sql directory not found: {sql_dir}")
    models = [parse_model(path) for path in sorted(sql_dir.rglob("*.sql"))]
    if not models:
        raise RuntimeError(f"no .sql models under {sql_dir}")
    return models


def resolve_order(models: list[Model]) -> list[Model]:
    """Kahn's algorithm. Ties break by layer then name so runs are reproducible."""
    by_name = {model.name: model for model in models}
    # Raw tables are loaded by extract.py and are not models, so they are not
    # part of the graph.
    edges = {
        model.name: {dep for dep in model.depends_on if dep in by_name} for model in models
    }
    dependents: dict[str, set[str]] = {name: set() for name in by_name}
    for name, deps in edges.items():
        for dep in deps:
            dependents[dep].add(name)

    ready = sorted(
        (name for name, deps in edges.items() if not deps),
        key=lambda n: (LAYER_ORDER.get(by_name[n].layer, 99), n),
    )
    ordered: list[Model] = []
    remaining = {name: set(deps) for name, deps in edges.items()}

    while ready:
        name = ready.pop(0)
        ordered.append(by_name[name])
        for child in sorted(dependents[name]):
            remaining[child].discard(name)
            if not remaining[child] and child not in {m.name for m in ordered} and child not in ready:
                ready.append(child)
        ready.sort(key=lambda n: (LAYER_ORDER.get(by_name[n].layer, 99), n))

    if len(ordered) != len(models):
        stuck = sorted(set(by_name) - {m.name for m in ordered})
        raise CircularDependencyError(f"cycle or missing dependency involving: {stuck}")
    return ordered


@dataclass(slots=True)
class ModelResult:
    name: str
    layer: str
    materialized: str
    rows: int
    duration_ms: float


def run_model(warehouse: Warehouse, model: Model) -> ModelResult:
    started = time.perf_counter()
    body = model.select_sql

    if model.materialized == "view":
        warehouse.execute(f"DROP VIEW IF EXISTS {model.name}")
        warehouse.execute(f"CREATE VIEW {model.name} AS {body}")
    else:
        warehouse.execute(f"DROP TABLE IF EXISTS {model.name}")
        warehouse.execute(f"CREATE TABLE {model.name} AS {body}")

    rows = warehouse.row_count(model.name)
    duration = (time.perf_counter() - started) * 1000
    logger.info("built %-26s %-5s %8d rows  %6.0f ms", model.name, model.materialized, rows, duration)
    return ModelResult(model.name, model.layer, model.materialized, rows, duration)


def run_all(warehouse: Warehouse, sql_dir: Path, select: list[str] | None = None) -> list[ModelResult]:
    models = resolve_order(discover_models(sql_dir))
    if select:
        wanted = set(select)
        models = [m for m in models if m.name in wanted or m.layer in wanted]
    return [run_model(warehouse, model) for model in models]


def to_mermaid(models: list[Model]) -> str:
    """Render the lineage graph as Mermaid so it can go straight into the README."""
    lines = ["graph LR"]
    layers: dict[str, list[Model]] = {}
    for model in models:
        layers.setdefault(model.layer, []).append(model)

    for layer in sorted(layers, key=lambda layer_name: LAYER_ORDER.get(layer_name, 99)):
        lines.append(f"  subgraph {layer}")
        for model in sorted(layers[layer], key=lambda m: m.name):
            lines.append(f"    {model.name}[{model.name}]")
        lines.append("  end")

    known = {model.name for model in models}
    for model in models:
        for dependency in model.depends_on:
            if dependency in known:
                lines.append(f"  {dependency} --> {model.name}")
            else:
                lines.append(f"  {dependency}([{dependency}]) --> {model.name}")
    return "\n".join(lines)
