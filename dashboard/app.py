"""
A lightweight health dashboard over the check-run history in SQLite.

Run: streamlit run dashboard/app.py
"""

from __future__ import annotations

import pathlib
import sys

import pandas as pd
import streamlit as st

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from storage.results_store import ResultsStore
from core.config_loader import load_monitors
from lineage.graph import LineageGraph

st.set_page_config(page_title="Data Quality Observability", layout="wide")
st.title("📊 Data Quality & Observability Dashboard")

store = ResultsStore()
monitors = load_monitors()
graph = LineageGraph.from_monitors(monitors)

tables = [m.table for m in monitors]

if not store.get_monitored_tables():
    st.warning("No check runs recorded yet. Run `python run_checks.py` first.")
    st.stop()

cols = st.columns(len(tables))
for col, table in zip(cols, tables):
    latest = store.get_latest_results(table)
    if not latest:
        col.info(f"**{table}**\nNo data yet")
        continue
    most_recent_run_at = latest[0]["run_at"]
    recent = [r for r in latest if r["run_at"] == most_recent_run_at]
    failed = [r for r in recent if not r["passed"]]

    if failed:
        col.error(f"**{table}**\n{len(failed)} check(s) failing")
    else:
        col.success(f"**{table}**\nAll checks passing")

st.divider()

selected = st.selectbox("Inspect table", tables)
monitor = next(m for m in monitors if m.table == selected)

st.subheader(f"`{selected}` — owner: {monitor.owner}")

impacted = graph.downstream_impact(selected)
if impacted:
    st.caption(f"Downstream dependents: {', '.join(impacted)}")
upstream = graph.upstream_candidates(selected)
if upstream:
    st.caption(f"Upstream sources: {', '.join(upstream)}")

results = store.get_latest_results(selected)
if results:
    df = pd.DataFrame(results)
    df["passed"] = df["passed"].map({1: "✅ pass", 0: "❌ fail"})
    st.dataframe(
        df[["run_at", "check_type", "passed", "message", "metric_value"]].sort_values("run_at", ascending=False),
        use_container_width=True,
    )

row_counts = store.get_historical_row_counts(selected, window_days=30)
if row_counts:
    st.subheader("Row count history")
    st.line_chart(pd.DataFrame({"row_count": list(reversed(row_counts))}))
