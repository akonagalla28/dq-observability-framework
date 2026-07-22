"""
Entrypoint: runs all configured checks against all monitored tables, persists
results, and fires alerts for any failures.

Run: python run_checks.py
"""

from core.engine import run_all


def main() -> None:
    summaries = run_all()
    print()
    total_failed = sum(1 for s in summaries if not s.passed)
    print(f"Ran checks on {len(summaries)} table(s), {total_failed} with failures.")
    for s in summaries:
        status = "PASS" if s.passed else "FAIL"
        print(f"  [{status}] {s.table} ({s.total_checks} checks)")
        for f in s.failed_checks:
            print(f"      - {f}")


if __name__ == "__main__":
    main()
