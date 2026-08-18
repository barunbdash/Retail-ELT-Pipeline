"""Generate the raw source files the pipeline consumes.

Three source systems, deliberately messy in the ways real ones are: duplicate
rows from an at-least-once event bus, nulls in columns the source swears are
mandatory, a currency column with mixed casing, negative quantities from
returns booked as orders, and a handful of orphan foreign keys.

The mess is seeded and reproducible, so the data quality checks fail the same
way on every machine.

    python -m pipeline.generate_source_data --rows 20000
"""

from __future__ import annotations

import argparse
import csv
import json
import random
from datetime import date, datetime, timedelta
from pathlib import Path

from .config import settings

COUNTRIES = ["DE", "FR", "NL", "US", "GB", "ES", "IT", "PL"]
CHANNELS = ["web", "mobile_app", "marketplace", "retail_store"]
CATEGORIES = {
    "coffee": (8.5, 42.0),
    "tea": (5.0, 28.0),
    "equipment": (35.0, 480.0),
    "accessories": (4.0, 65.0),
    "subscription": (18.0, 60.0),
}
STATUSES = ["completed", "completed", "completed", "completed", "cancelled", "refunded"]
PAYMENT_METHODS = ["card", "paypal", "sepa", "invoice", "apple_pay"]


def _write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def generate_customers(rng: random.Random, count: int) -> list[dict]:
    signup_start = date(2022, 1, 1)
    rows = []
    for i in range(1, count + 1):
        signup = signup_start + timedelta(days=rng.randint(0, 1200))
        rows.append(
            {
                "customer_id": f"C{i:06d}",
                "signup_date": signup.isoformat(),
                "country": rng.choice(COUNTRIES),
                # ~2% of rows have no segment: the CRM lets it be blank.
                "segment": rng.choice(["consumer", "business", "education"]) if rng.random() > 0.02 else "",
                "marketing_opt_in": rng.choice(["true", "false", "TRUE", "False", "1", "0"]),
                "acquisition_channel": rng.choice(["organic", "paid_search", "referral", "social", "email"]),
            }
        )
    return rows


def generate_products(rng: random.Random, count: int) -> list[dict]:
    rows = []
    for i in range(1, count + 1):
        category = rng.choice(list(CATEGORIES))
        low, high = CATEGORIES[category]
        price = round(rng.uniform(low, high), 2)
        rows.append(
            {
                "product_id": f"P{i:05d}",
                "product_name": f"{category.title()} item {i}",
                "category": category,
                "list_price": price,
                "cost_price": round(price * rng.uniform(0.35, 0.72), 2),
                "is_active": rng.choice(["true", "true", "true", "false"]),
            }
        )
    return rows


def generate_orders(
    rng: random.Random, customers: list[dict], products: list[dict], count: int
) -> tuple[list[dict], list[dict]]:
    start = datetime(2024, 1, 1)
    orders: list[dict] = []
    lines: list[dict] = []

    for i in range(1, count + 1):
        customer = rng.choice(customers)
        ordered_at = start + timedelta(
            days=rng.randint(0, 560), hours=rng.randint(0, 23), minutes=rng.randint(0, 59)
        )
        status = rng.choice(STATUSES)
        order_id = f"O{i:08d}"

        orders.append(
            {
                "order_id": order_id,
                # 1.5% of orders reference a customer that does not exist in the CRM
                # extract: the dimension is exported an hour before the fact table.
                "customer_id": customer["customer_id"] if rng.random() > 0.015 else f"C{rng.randint(900000, 999999)}",
                "ordered_at": ordered_at.isoformat(sep=" ", timespec="seconds"),
                "status": status,
                "channel": rng.choice(CHANNELS),
                "payment_method": rng.choice(PAYMENT_METHODS),
                # Mixed casing straight from the payment provider.
                "currency": rng.choice(["EUR", "eur", "EUR", "USD", "usd", "GBP"]),
                "shipping_cost": round(rng.uniform(0.0, 12.9), 2) if rng.random() > 0.05 else "",
            }
        )

        for line_number in range(1, rng.randint(1, 5) + 1):
            product = rng.choice(products)
            quantity = rng.randint(1, 6)
            if status == "refunded" and rng.random() < 0.4:
                quantity = -quantity  # returns booked as negative-quantity lines
            discount = round(rng.choice([0.0, 0.0, 0.0, 0.05, 0.1, 0.2]), 2)
            lines.append(
                {
                    "order_id": order_id,
                    "line_number": line_number,
                    "product_id": product["product_id"],
                    "quantity": quantity,
                    "unit_price": product["list_price"],
                    "discount_pct": discount,
                }
            )

    # At-least-once delivery: replay roughly 0.8% of orders verbatim.
    duplicates = rng.sample(orders, k=max(1, int(len(orders) * 0.008)))
    orders.extend(duplicates)
    duplicate_ids = {row["order_id"] for row in duplicates}
    lines.extend([line for line in lines if line["order_id"] in duplicate_ids])

    rng.shuffle(orders)
    return orders, lines


def generate_web_events(rng: random.Random, customers: list[dict], count: int) -> list[dict]:
    """Simulate sessions, not independent events.

    Drawing event types independently produces months where add-to-carts
    outnumber page views, which is impossible and makes the funnel mart
    meaningless. Walking each session down the funnel keeps every stage a
    subset of the one before it, so conversion rates stay in [0, 100] by
    construction rather than by luck.
    """
    start = datetime(2024, 1, 1)
    events: list[dict] = []
    session_number = 0

    while len(events) < count:
        session_number += 1
        session_id = f"S{session_number:08d}"
        customer = rng.choice(customers)
        device = rng.choice(["desktop", "mobile", "tablet"])
        opened = start + timedelta(minutes=rng.randint(0, 560 * 24 * 60))
        clock = opened

        def emit(event_type: str) -> None:
            nonlocal clock
            clock += timedelta(seconds=rng.randint(5, 900))
            events.append(
                {
                    "event_id": f"E{len(events):09d}",
                    "customer_id": customer["customer_id"],
                    "event_type": event_type,
                    "occurred_at": clock.isoformat(sep=" ", timespec="seconds"),
                    "session_id": session_id,
                    "device": device,
                }
            )

        for _ in range(rng.randint(1, 6)):
            emit("page_view")
        for _ in range(rng.randint(0, 2)):
            emit("search")

        if rng.random() < 0.22:
            emit("add_to_cart")
            if rng.random() < 0.55:
                emit("checkout_start")
                if rng.random() < 0.62:
                    emit("checkout_complete")

    return events[:count]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate raw source files")
    parser.add_argument("--rows", type=int, default=20000, help="number of orders")
    parser.add_argument("--customers", type=int, default=3000)
    parser.add_argument("--products", type=int, default=250)
    parser.add_argument("--seed", type=int, default=17)
    args = parser.parse_args(argv)

    rng = random.Random(args.seed)
    raw = Path(settings.raw_dir)

    customers = generate_customers(rng, args.customers)
    products = generate_products(rng, args.products)
    orders, lines = generate_orders(rng, customers, products, args.rows)
    events = generate_web_events(rng, customers, args.rows * 3)

    _write_csv(raw / "crm" / "customers.csv", customers, list(customers[0]))
    _write_csv(raw / "catalog" / "products.csv", products, list(products[0]))
    _write_csv(raw / "orders" / "orders.csv", orders, list(orders[0]))
    _write_csv(raw / "orders" / "order_lines.csv", lines, list(lines[0]))

    events_path = raw / "web" / "events.jsonl"
    events_path.parent.mkdir(parents=True, exist_ok=True)
    events_path.write_text(
        "\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8"
    )

    print(
        json.dumps(
            {
                "customers": len(customers),
                "products": len(products),
                "orders": len(orders),
                "order_lines": len(lines),
                "web_events": len(events),
                "raw_dir": str(raw),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
