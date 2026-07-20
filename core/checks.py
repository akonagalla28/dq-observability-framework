"""
Each function here implements ONE check type referenced in monitors.yaml.
Adding a new check type = adding one function + registering it in CHECKS below
-- the engine dispatches to these generically based on the `type` field in config,
so no per-table branching logic exists anywhere in the codebase.

Every check returns a CheckResult: pass/fail, a human-readable message, and
optional metric value (used by the dashboard for sparklines/trends).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import pandas as pd


@dataclass
class CheckResult:
    check_type: str
    passed: bool
    message: str
    metric_value: float | None = None


def check_not_null(df: pd.DataFrame, params: dict[str, Any]) -> list[CheckResult]:
    results = []
    for col in params["columns"]:
        null_count = int(df[col].isnull().sum())
        passed = null_count == 0
        results.append(
            CheckResult(
                check_type=f"not_null[{col}]",
                passed=passed,
                message=f"{null_count} null value(s) in '{col}'" if not passed else f"'{col}' has no nulls",
                metric_value=null_count,
            )
        )
    return results


def check_unique(df: pd.DataFrame, params: dict[str, Any]) -> list[CheckResult]:
    results = []
    for col in params["columns"]:
        dup_count = int(df[col].duplicated().sum())
        passed = dup_count == 0
        results.append(
            CheckResult(
                check_type=f"unique[{col}]",
                passed=passed,
                message=f"{dup_count} duplicate value(s) in '{col}'" if not passed else f"'{col}' is unique",
                metric_value=dup_count,
            )
        )
    return results


def check_freshness(df: pd.DataFrame, params: dict[str, Any], sla_minutes: int, now: datetime | None = None) -> list[CheckResult]:
    now = now or datetime.now(timezone.utc)
    ts_col = params["timestamp_column"]
    if df.empty:
        return [CheckResult("freshness", False, "Table is empty -- cannot evaluate freshness", None)]

    latest = pd.to_datetime(df[ts_col]).max()
    if latest.tzinfo is None:
        latest = latest.tz_localize(timezone.utc)
    age_minutes = (now - latest).total_seconds() / 60
    passed = age_minutes <= sla_minutes
    return [
        CheckResult(
            check_type="freshness",
            passed=passed,
            message=f"Latest row is {age_minutes:.0f}min old (SLA: {sla_minutes}min)",
            metric_value=age_minutes,
        )
    ]


def check_row_count_anomaly(
    df: pd.DataFrame,
    params: dict[str, Any],
    historical_counts: list[int],
) -> list[CheckResult]:
    """
    Flags a volume anomaly using a z-score against historical daily row counts.
    Needs at least 3 historical data points to compute a meaningful baseline;
    with fewer, it passes by default (can't yet judge "normal").
    """
    current_count = len(df)
    threshold = params.get("z_score_threshold", 3.0)

    if len(historical_counts) < 3:
        return [
            CheckResult(
                "row_count_anomaly",
                True,
                f"Row count {current_count} (baseline still warming up, {len(historical_counts)} historical points)",
                current_count,
            )
        ]

    mean = sum(historical_counts) / len(historical_counts)
    variance = sum((x - mean) ** 2 for x in historical_counts) / len(historical_counts)
    stddev = variance ** 0.5

    if stddev == 0:
        z_score = 0.0 if current_count == mean else float("inf")
    else:
        z_score = (current_count - mean) / stddev

    passed = abs(z_score) <= threshold
    return [
        CheckResult(
            check_type="row_count_anomaly",
            passed=passed,
            message=f"Row count {current_count} vs baseline mean {mean:.0f} (z-score={z_score:.2f}, threshold={threshold})",
            metric_value=current_count,
        )
    ]


def check_range(df: pd.DataFrame, params: dict[str, Any]) -> list[CheckResult]:
    col = params["column"]
    min_v, max_v = params.get("min_value"), params.get("max_value")
    out_of_range = df[(df[col] < min_v) | (df[col] > max_v)] if min_v is not None or max_v is not None else df.iloc[0:0]
    passed = len(out_of_range) == 0
    return [
        CheckResult(
            check_type=f"range[{col}]",
            passed=passed,
            message=f"{len(out_of_range)} row(s) outside [{min_v}, {max_v}] in '{col}'"
            if not passed
            else f"All values in '{col}' within [{min_v}, {max_v}]",
            metric_value=len(out_of_range),
        )
    ]


def check_schema_drift(df: pd.DataFrame, params: dict[str, Any]) -> list[CheckResult]:
    expected = params["expected_columns"]
    actual_cols = set(df.columns)
    expected_cols = set(expected.keys())

    missing = expected_cols - actual_cols
    extra = actual_cols - expected_cols
    passed = not missing  # extra columns are a warning-level signal, not a hard fail

    parts = []
    if missing:
        parts.append(f"missing columns: {sorted(missing)}")
    if extra:
        parts.append(f"unexpected new columns: {sorted(extra)}")
    message = "; ".join(parts) if parts else "Schema matches expected definition"

    return [CheckResult("schema_drift", passed, message, None)]


CHECKS = {
    "not_null": check_not_null,
    "unique": check_unique,
    "freshness": check_freshness,
    "row_count_anomaly": check_row_count_anomaly,
    "range": check_range,
    "schema_drift": check_schema_drift,
}
