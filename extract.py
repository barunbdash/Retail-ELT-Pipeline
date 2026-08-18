"""Land the raw source files into the warehouse as untyped tables.

Extract does no cleaning at all: every column arrives as text and every row
that was in the file is in the table. Casting, deduplication and normalisation
happen in staging, where the logic is version controlled and testable. That
separation is the whole point of ELT over ETL.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from .config import Settings, settings
from .warehouse import Warehouse

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Source:
    table: str
    relative_path: str
    fmt: str = "csv"


SOURCES: tuple[Source, ...] = (
    Source("raw_customers", "crm/customers.csv"),
    Source("raw_products", "catalog/products.csv"),
    Source("raw_orders", "orders/orders.csv"),
    Source("raw_order_lines", "orders/order_lines.csv"),
    Source("raw_web_events", "web/events.jsonl", fmt="jsonl"),
)


def extract_all(warehouse: Warehouse, config: Settings | None = None) -> dict[str, int]:
    config = config or settings
    raw_dir = Path(config.raw_dir)
    if not raw_dir.exists():
        raise FileNotFoundError(
            f"{raw_dir} does not exist. Run `python -m pipeline.generate_source_data` first."
        )

    counts: dict[str, int] = {}
    for source in SOURCES:
        path = raw_dir / source.relative_path
        if not path.exists():
            raise FileNotFoundError(f"missing source file: {path}")
        loader = warehouse.load_jsonl if source.fmt == "jsonl" else warehouse.load_csv
        rows = loader(path, source.table)
        counts[source.table] = rows
        logger.info("loaded %-18s %8d rows from %s", source.table, rows, source.relative_path)
    return counts
