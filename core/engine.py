"""
The engine is intentionally thin: for each monitored table, load its data,
dispatch to the right check functions based on config, persist results, and
fire an alert (with lineage context) if anything failed.

This is the "glue" module -- it contains no data-quality logic itself
(that lives in core/checks.py) and no storage logic (that lives in
storage/results_store.py). That separation is what makes each piece testable
in isolation.
"""

from __future__ import annotations

import pathlib
from dataclasses import dataclass
from datetime import datetime, timezone

import pandas as pd

from core.checks import CHECKS, CheckResult
from core.config_loader import MonitorConfig, load_monitors
from lineage.graph import LineageGraph
from storage.results_store import ResultsStore
from alerting.notifier import Notifier, build_alert_message, get_notifier

DATA_DIR = pathlib.Path(__file__).resolve().parent.parent / "data" / "tables"


@dataclass
class TableRunSummary:
    table: str
    total_checks: int
    failed_checks: list[str]

    @property
    def passed(self) -> bool:
        return len(self.failed_checks) == 0


def load_table(table_name: str) -> pd.DataFrame:
    path = DATA_DIR / f"{table_name}.parquet"
    if not path.exists():
        raise FileNotFoundError(f"No data found for table '{table_name}' at {path}")
    return pd.read_parquet(path)


def run_checks_for_table(
    monitor: MonitorConfig,
    df: pd.DataFrame,
    store: ResultsStore,
    now: datetime | None = None,
) -> TableRunSummary:
    now = now or datetime.now(timezone.utc)
    failed: list[str] = []
    total = 0

    for check_cfg in monitor.checks:
        fn = CHECKS[check_cfg.type]

        if check_cfg.type == "freshness":
            results = fn(df, check_cfg.params, monitor.freshness_sla_minutes, now=now)
        elif check_cfg.type == "row_count_anomaly":
            history = store.get_historical_row_counts(monitor.table, monitor.row_count_baseline_window_days)
            results = fn(df, check_cfg.params, history)
        else:
            results = fn(df, check_cfg.params)

        for r in results:
            total += 1
            store.record_check_result(monitor.table, r.check_type, r.passed, r.message, r.metric_value)
            if not r.passed:
                failed.append(f"{r.check_type}: {r.message}")

    store.record_row_count(monitor.table, len(df))
    return TableRunSummary(table=monitor.table, total_checks=total, failed_checks=failed)


def run_all(
    notifier: Notifier | None = None,
    store: ResultsStore | None = None,
    now: datetime | None = None,
) -> list[TableRunSummary]:
    monitors = load_monitors()
    store = store or ResultsStore()
    notifier = notifier or get_notifier()
    graph = LineageGraph.from_monitors(monitors)

    summaries = []
    for monitor in monitors:
        df = load_table(monitor.table)
        summary = run_checks_for_table(monitor, df, store, now=now)
        summaries.append(summary)

        if not summary.passed:
            message = build_alert_message(
                table=monitor.table,
                owner=monitor.owner,
                failed_checks=summary.failed_checks,
                downstream_impacted=graph.downstream_impact(monitor.table),
            )
            notifier.send(message)

    return summaries


if __name__ == "__main__":
    results = run_all()
    for s in results:
        status = "PASS" if s.passed else "FAIL"
        print(f"[{status}] {s.table}: {s.total_checks} checks run, {len(s.failed_checks)} failed")
