"""
Persists every check run to SQLite so:
  1. row_count_anomaly has real historical data to compute a baseline against
     (not just the current run).
  2. The dashboard can show trends/sparklines over time, not just a snapshot.
  3. Alerting can check "was this already failing yesterday" to avoid re-alerting
     on every single run for a known, ongoing issue (not implemented here, but
     the schema supports it).
"""

from __future__ import annotations

import pathlib
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

DB_PATH = pathlib.Path(__file__).resolve().parent / "dq_history.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS check_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    table_name TEXT NOT NULL,
    check_type TEXT NOT NULL,
    passed INTEGER NOT NULL,
    message TEXT NOT NULL,
    metric_value REAL,
    run_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS row_counts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    table_name TEXT NOT NULL,
    row_count INTEGER NOT NULL,
    run_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_check_runs_table ON check_runs(table_name, run_at);
CREATE INDEX IF NOT EXISTS idx_row_counts_table ON row_counts(table_name, run_at);
"""


class ResultsStore:
    def __init__(self, db_path: pathlib.Path = DB_PATH):
        self.db_path = db_path
        with self._connect() as con:
            con.executescript(SCHEMA)

    @contextmanager
    def _connect(self):
        con = sqlite3.connect(self.db_path)
        try:
            yield con
            con.commit()
        finally:
            con.close()

    def record_check_result(
        self, table_name: str, check_type: str, passed: bool, message: str, metric_value: float | None
    ) -> None:
        with self._connect() as con:
            con.execute(
                "INSERT INTO check_runs (table_name, check_type, passed, message, metric_value, run_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (table_name, check_type, int(passed), message, metric_value, datetime.now(timezone.utc).isoformat()),
            )

    def record_row_count(self, table_name: str, row_count: int) -> None:
        with self._connect() as con:
            con.execute(
                "INSERT INTO row_counts (table_name, row_count, run_at) VALUES (?, ?, ?)",
                (table_name, row_count, datetime.now(timezone.utc).isoformat()),
            )

    def get_historical_row_counts(self, table_name: str, window_days: int) -> list[int]:
        with self._connect() as con:
            cur = con.execute(
                "SELECT row_count FROM row_counts WHERE table_name = ? "
                "ORDER BY run_at DESC LIMIT ?",
                (table_name, window_days),
            )
            return [row[0] for row in cur.fetchall()]

    def get_latest_results(self, table_name: str | None = None) -> list[dict]:
        with self._connect() as con:
            con.row_factory = sqlite3.Row
            if table_name:
                cur = con.execute(
                    "SELECT * FROM check_runs WHERE table_name = ? ORDER BY run_at DESC LIMIT 50", (table_name,)
                )
            else:
                cur = con.execute("SELECT * FROM check_runs ORDER BY run_at DESC LIMIT 200")
            return [dict(row) for row in cur.fetchall()]

    def get_monitored_tables(self) -> list[str]:
        with self._connect() as con:
            cur = con.execute("SELECT DISTINCT table_name FROM check_runs")
            return [row[0] for row in cur.fetchall()]
