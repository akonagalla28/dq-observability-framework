"""
Sends alerts when a check fails. Slack is the primary channel (most teams
already live there); a console notifier is included so the framework is
fully runnable and testable with zero external services configured.

Alerts are lineage-aware: if a table has known downstream dependents, the
alert says so, so the on-call engineer immediately knows the blast radius
instead of having to go look it up.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod

import requests


class Notifier(ABC):
    @abstractmethod
    def send(self, message: str) -> None: ...


class ConsoleNotifier(Notifier):
    """Default notifier -- prints to stdout. Always available, no config needed."""

    def send(self, message: str) -> None:
        print(f"[ALERT] {message}")


class SlackNotifier(Notifier):
    def __init__(self, webhook_url: str | None = None):
        self.webhook_url = webhook_url or os.environ.get("SLACK_WEBHOOK_URL")

    def send(self, message: str) -> None:
        if not self.webhook_url:
            raise ValueError("SLACK_WEBHOOK_URL not configured -- set it in .env or pass explicitly")
        response = requests.post(self.webhook_url, json={"text": message}, timeout=10)
        response.raise_for_status()


def build_alert_message(
    table: str,
    owner: str,
    failed_checks: list[str],
    downstream_impacted: list[str],
) -> str:
    lines = [f":rotating_light: *Data quality failure* on `{table}` (owner: {owner})"]
    for check in failed_checks:
        lines.append(f"  • {check}")
    if downstream_impacted:
        lines.append(f"Downstream tables potentially affected: {', '.join(downstream_impacted)}")
    return "\n".join(lines)


def get_notifier(prefer_slack: bool = True) -> Notifier:
    if prefer_slack and os.environ.get("SLACK_WEBHOOK_URL"):
        return SlackNotifier()
    return ConsoleNotifier()
