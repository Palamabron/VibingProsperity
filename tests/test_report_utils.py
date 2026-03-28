"""Tests for scripts/report_utils.py (legacy console output + experiment index helpers)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from report_utils import (  # noqa: E402
    format_front_matter_yaml,
    parse_backtest_console_text,
    parse_simple_front_matter,
    parse_total_profit_from_backtest_output,
    rebuild_experiment_index,
)


def test_parse_total_profit_from_backtest_output_last_wins() -> None:
    text = """Some header
Total profit: 1,000
Round 0 day 0: 100
Total profit: 2,500
"""
    assert parse_total_profit_from_backtest_output(text) == 2500


def test_parse_backtest_console_text_merged_and_day() -> None:
    text = """
Backtesting algo on round 0 day 0
EMERALDS: 100
TOMATOES: 50
Total profit: 150

Profit summary:
Round 0 day 0: 150

Total profit: 150
"""
    pb = parse_backtest_console_text(text)
    assert pb.merged_total == 150
    assert len(pb.day_blocks) == 1
    assert pb.day_blocks[0].round_n == 0
    assert pb.day_blocks[0].day == 0
    assert pb.day_blocks[0].products.get("EMERALDS") == 100
    assert pb.profit_summary_days == [(0, 0, 150)]


def test_parse_simple_front_matter_basic() -> None:
    raw = """---
experiment_id: "abc"
source: local
round: 0
total_profit: 12345
---
# Body
"""
    fm = parse_simple_front_matter(raw)
    assert fm["experiment_id"] == "abc"
    assert fm["source"] == "local"
    assert fm["round"] == 0
    assert fm["total_profit"] == 12345


def test_parse_simple_front_matter_negative_profit() -> None:
    raw = """---
source: live
total_profit: -42
---
"""
    fm = parse_simple_front_matter(raw)
    assert fm["total_profit"] == -42


def test_format_front_matter_yaml_round_trip_keys() -> None:
    block = format_front_matter_yaml(
        {
            "experiment_id": "x",
            "source": "live",
            "round": None,
            "total_profit": None,
        }
    )
    fm = parse_simple_front_matter(block + "\nbody")
    assert fm["round"] is None
    assert fm["total_profit"] is None


def test_rebuild_experiment_index_orders_by_mtime(tmp_path: Path) -> None:
    reports = tmp_path / "reports"
    runs = reports / "runs"
    runs.mkdir(parents=True)
    (runs / "older_experiment.md").write_text(
        """---
experiment_id: "o"
source: local
round: 0
total_profit: 1
---
""",
        encoding="utf-8",
    )
    newer = runs / "newer_experiment.md"
    newer.write_text(
        """---
experiment_id: "n"
source: live
round: null
total_profit: 99
---
""",
        encoding="utf-8",
    )
    import os
    import time

    base = time.time()
    os.utime(runs / "older_experiment.md", (base, base))
    os.utime(newer, (base + 100.0, base + 100.0))

    idx = reports / "INDEX.md"
    rebuild_experiment_index(runs_dir=runs, index_path=idx, reports_root=reports)
    text = idx.read_text(encoding="utf-8")
    assert "newer_experiment.md" in text
    assert text.index("newer_experiment") < text.index("older_experiment")
