"""
Loads config/monitors.yaml into typed Python objects. This is the "no code
per table" mechanism: adding a new table to monitor means adding a YAML block,
not writing a new Python check function.
"""

from __future__ import annotations

import pathlib
from dataclasses import dataclass, field
from typing import Any

import yaml

CONFIG_PATH = pathlib.Path(__file__).resolve().parent.parent / "config" / "monitors.yaml"


@dataclass
class CheckConfig:
    type: str
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class MonitorConfig:
    table: str
    owner: str
    freshness_sla_minutes: int
    row_count_baseline_window_days: int
    checks: list[CheckConfig] = field(default_factory=list)
    upstream: list[str] = field(default_factory=list)


def load_monitors(path: pathlib.Path = CONFIG_PATH) -> list[MonitorConfig]:
    raw = yaml.safe_load(path.read_text())
    monitors = []
    for m in raw.get("monitors", []):
        checks = []
        for c in m.get("checks", []):
            check_type = c.pop("type")
            checks.append(CheckConfig(type=check_type, params=c))
        monitors.append(
            MonitorConfig(
                table=m["table"],
                owner=m["owner"],
                freshness_sla_minutes=m["freshness_sla_minutes"],
                row_count_baseline_window_days=m.get("row_count_baseline_window_days", 7),
                checks=checks,
                upstream=m.get("upstream", []),
            )
        )
    return monitors


if __name__ == "__main__":
    for m in load_monitors():
        print(f"{m.table} (owner={m.owner}, sla={m.freshness_sla_minutes}min, upstream={m.upstream})")
        for c in m.checks:
            print(f"    - {c.type}: {c.params}")
