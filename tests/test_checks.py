"""
Tests target the two riskiest parts of this framework:
  1. Each check type actually flags the failure mode it claims to catch
     (not just "runs without error").
  2. The lineage graph correctly computes downstream impact from the
     `upstream` edges declared in config -- this is what makes alerts
     useful instead of just noisy.
"""

from __future__ import annotations

import pathlib
import sys
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from core.checks import (
    check_not_null,
    check_unique,
    check_freshness,
    check_row_count_anomaly,
    check_range,
    check_schema_drift,
)
from core.config_loader import MonitorConfig, CheckConfig
from lineage.graph import LineageGraph


def test_not_null_catches_nulls():
    df = pd.DataFrame({"a": [1, None, 3]})
    results = check_not_null(df, {"columns": ["a"]})
    assert results[0].passed is False
    assert results[0].metric_value == 1


def test_not_null_passes_clean_data():
    df = pd.DataFrame({"a": [1, 2, 3]})
    results = check_not_null(df, {"columns": ["a"]})
    assert results[0].passed is True


def test_unique_catches_duplicates():
    df = pd.DataFrame({"id": [1, 2, 2, 3]})
    results = check_unique(df, {"columns": ["id"]})
    assert results[0].passed is False
    assert results[0].metric_value == 1


def test_freshness_fails_on_stale_data():
    now = datetime.now(timezone.utc)
    df = pd.DataFrame({"ts": [now - timedelta(hours=5)]})
    results = check_freshness(df, {"timestamp_column": "ts"}, sla_minutes=60, now=now)
    assert results[0].passed is False


def test_freshness_passes_on_recent_data():
    now = datetime.now(timezone.utc)
    df = pd.DataFrame({"ts": [now - timedelta(minutes=5)]})
    results = check_freshness(df, {"timestamp_column": "ts"}, sla_minutes=60, now=now)
    assert results[0].passed is True


def test_row_count_anomaly_flags_sudden_drop():
    df = pd.DataFrame({"x": range(10)})  # current count = 10
    historical = [500, 510, 495, 505, 490]  # baseline ~500
    results = check_row_count_anomaly(df, {"z_score_threshold": 3.0}, historical)
    assert results[0].passed is False


def test_row_count_anomaly_passes_normal_variation():
    df = pd.DataFrame({"x": range(505)})
    historical = [500, 510, 495, 505, 490]
    results = check_row_count_anomaly(df, {"z_score_threshold": 3.0}, historical)
    assert results[0].passed is True


def test_row_count_anomaly_warms_up_with_insufficient_history():
    df = pd.DataFrame({"x": range(5)})
    results = check_row_count_anomaly(df, {"z_score_threshold": 3.0}, historical_counts=[100])
    assert results[0].passed is True  # can't judge yet, shouldn't false-alarm


def test_range_catches_out_of_bounds():
    df = pd.DataFrame({"prep_time": [5, 10, -3, 200]})
    results = check_range(df, {"column": "prep_time", "min_value": 0, "max_value": 180})
    assert results[0].passed is False
    assert results[0].metric_value == 2  # -3 and 200 both out of range


def test_schema_drift_catches_missing_column():
    df = pd.DataFrame({"a": [1], "b": [2]})
    results = check_schema_drift(df, {"expected_columns": {"a": "int", "b": "int", "c": "int"}})
    assert results[0].passed is False
    assert "c" in results[0].message


def test_schema_drift_passes_matching_schema():
    df = pd.DataFrame({"a": [1], "b": [2]})
    results = check_schema_drift(df, {"expected_columns": {"a": "int", "b": "int"}})
    assert results[0].passed is True


def _monitor(table, upstream=None):
    return MonitorConfig(
        table=table,
        owner="test@example.com",
        freshness_sla_minutes=60,
        row_count_baseline_window_days=7,
        checks=[],
        upstream=upstream or [],
    )


def test_lineage_downstream_impact_multi_hop():
    monitors = [
        _monitor("bronze"),
        _monitor("silver", upstream=["bronze"]),
        _monitor("gold", upstream=["silver"]),
    ]
    graph = LineageGraph.from_monitors(monitors)
    # a bronze failure should be traceable all the way to gold, two hops away
    assert set(graph.downstream_impact("bronze")) == {"silver", "gold"}
    assert graph.downstream_impact("gold") == []


def test_lineage_upstream_candidates():
    monitors = [
        _monitor("bronze"),
        _monitor("silver", upstream=["bronze"]),
    ]
    graph = LineageGraph.from_monitors(monitors)
    assert graph.upstream_candidates("silver") == ["bronze"]
    assert graph.upstream_candidates("bronze") == []
