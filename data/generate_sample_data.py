"""
Generates three synthetic tables (bronze_orders, silver_orders,
gold_restaurant_metrics) mimicking the medallion layers from the streaming
lakehouse project. On top of "clean" data, this deliberately injects issues
so running the framework produces real failures, not just green checkmarks:

  - bronze_orders: a null spike in `restaurant_id` for a batch of rows
  - silver_orders: an out-of-range `prep_time_minutes` value (negative, from
    a hypothetical upstream clock skew bug)
  - gold_restaurant_metrics: dated slightly stale, to trip the freshness check

Run: python data/generate_sample_data.py
"""

from __future__ import annotations

import pathlib
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

OUT_DIR = pathlib.Path(__file__).resolve().parent / "tables"
RNG = np.random.default_rng(7)

N_RESTAURANTS = 20


def generate_bronze_orders(now: datetime, inject_issues: bool = True) -> pd.DataFrame:
    n = 500
    rows = []
    for i in range(n):
        restaurant_id = f"r_{RNG.integers(0, N_RESTAURANTS):03d}"
        ts = now - timedelta(minutes=int(RNG.integers(0, 45)))
        prep_time = max(2, RNG.normal(18, 5))
        rows.append(
            {
                "order_id": f"o_{i:05d}",
                "restaurant_id": restaurant_id,
                "event_timestamp": ts,
                "prep_time_minutes": round(prep_time, 1),
            }
        )
    df = pd.DataFrame(rows)

    if inject_issues:
        # Null spike: a batch of 15 rows lost their restaurant_id, simulating
        # a broken upstream join or a malformed producer message.
        null_idx = RNG.choice(df.index, size=15, replace=False)
        df.loc[null_idx, "restaurant_id"] = None

    return df


def generate_silver_orders(bronze: pd.DataFrame, inject_issues: bool = True) -> pd.DataFrame:
    df = bronze.dropna(subset=["restaurant_id"]).copy()

    if inject_issues:
        # Clock-skew bug: a few rows get a negative prep time, which should
        # never happen physically and should trip the range check.
        bad_idx = RNG.choice(df.index, size=3, replace=False)
        df.loc[bad_idx, "prep_time_minutes"] = -5.0

    return df.reset_index(drop=True)


def generate_gold_restaurant_metrics(silver: pd.DataFrame, now: datetime, inject_issues: bool = True) -> pd.DataFrame:
    grouped = silver.groupby("restaurant_id")["prep_time_minutes"].agg(avg_prep_time_minutes_7d="mean").reset_index()

    stale_offset = timedelta(minutes=200) if inject_issues else timedelta(minutes=10)
    grouped["event_timestamp"] = now - stale_offset
    return grouped


def main(now: datetime | None = None, inject_issues: bool = True) -> None:
    now = now or datetime.now(timezone.utc)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    bronze = generate_bronze_orders(now, inject_issues=inject_issues)
    silver = generate_silver_orders(bronze, inject_issues=inject_issues)
    gold = generate_gold_restaurant_metrics(silver, now, inject_issues=inject_issues)

    bronze.to_parquet(OUT_DIR / "bronze_orders.parquet", index=False)
    silver.to_parquet(OUT_DIR / "silver_orders.parquet", index=False)
    gold.to_parquet(OUT_DIR / "gold_restaurant_metrics.parquet", index=False)

    print(f"Wrote bronze_orders: {len(bronze)} rows ({bronze['restaurant_id'].isnull().sum()} null restaurant_ids)")
    print(f"Wrote silver_orders: {len(silver)} rows ({(silver['prep_time_minutes'] < 0).sum()} negative prep times)")
    print(f"Wrote gold_restaurant_metrics: {len(gold)} rows (dated {stale_note(inject_issues)})")


def stale_note(inject_issues: bool) -> str:
    return "~200min old, should trip freshness SLA" if inject_issues else "fresh"


if __name__ == "__main__":
    main()
