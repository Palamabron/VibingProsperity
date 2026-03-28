"""
Fixed setup and sanity checks — same role as `prepare.py` in Karpathy autoresearch.

Do **not** edit this file for normal strategy research; change `algorithm.py` instead.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"


def main() -> None:
    print("VibingProsperity — prepare")
    print(f"  Project root: {ROOT}")
    if DATA.is_dir():
        csvs = sorted(DATA.rglob("*.csv"))
        print(f"  data/**/*.csv: {len(csvs)} file(s)")
    else:
        print(f"  warning: {DATA} missing")
    algo = ROOT / "algorithm.py"
    print(f"  algorithm.py: {'ok' if algo.is_file() else 'MISSING'}")
    print()
    print("Next:")
    print("  uv sync")
    print("  uv run data_analytics.py          # optional: inspect CSV stats")
    print("  uv run python scripts/agent_cycle.py   # analytics + platform eval + report")
    print("  uv run autoresearch.py --help     # optional: overnight Gemini loop")


if __name__ == "__main__":
    main()
