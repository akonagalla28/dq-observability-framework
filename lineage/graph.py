"""
A minimal lineage graph, built directly from the `upstream` field each table
declares in monitors.yaml -- no separate lineage config to keep in sync.

Two things this makes possible:
  1. Downstream impact: "bronze_orders just failed its freshness check --
     which tables will look stale next?"
  2. Root-cause suggestion: "gold_restaurant_metrics failed row_count_anomaly --
     check upstream tables first before assuming the bug is in this table's
     own transformation logic."
"""

from __future__ import annotations

from dataclasses import dataclass, field

from core.config_loader import MonitorConfig


@dataclass
class LineageGraph:
    # table -> tables it directly depends on
    upstream: dict[str, list[str]] = field(default_factory=dict)
    # table -> tables that directly depend on it (the reverse edges)
    downstream: dict[str, list[str]] = field(default_factory=dict)

    @classmethod
    def from_monitors(cls, monitors: list[MonitorConfig]) -> "LineageGraph":
        graph = cls()
        all_tables = {m.table for m in monitors}
        for m in monitors:
            graph.upstream[m.table] = m.upstream
            graph.downstream.setdefault(m.table, [])
        for m in monitors:
            for up in m.upstream:
                if up in all_tables:
                    graph.downstream.setdefault(up, []).append(m.table)
        return graph

    def downstream_impact(self, table: str) -> list[str]:
        """BFS over downstream edges: everything that would look stale/wrong
        if `table` is currently broken."""
        visited = []
        queue = list(self.downstream.get(table, []))
        seen = set(queue)
        while queue:
            node = queue.pop(0)
            visited.append(node)
            for nxt in self.downstream.get(node, []):
                if nxt not in seen:
                    seen.add(nxt)
                    queue.append(nxt)
        return visited

    def upstream_candidates(self, table: str) -> list[str]:
        """Direct upstream tables to check first when `table` fails a check
        that could plausibly originate further up the pipeline (e.g. a row
        count anomaly is more often caused by a broken upstream source than
        by this table's own transform)."""
        return list(self.upstream.get(table, []))
