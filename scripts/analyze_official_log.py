#!/usr/bin/env python3
"""
Parse official IMC Prosperity submission payload (JSON with activitiesLog CSV).

The game UI exposes activity logs (e.g. after a submission). Save the JSON from the
browser (DevTools → Network response, or copy-paste) to a file and run:

  uv run python scripts/analyze_official_log.py reports/official/my_submission.json

There is no supported public API for https://prosperity.imc.com/game — uploads and
downloads are manual; this script only analyzes data you already saved locally.

activitiesLog format: semicolon-separated CSV with header including profit_and_loss.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
from pathlib import Path
from typing import Any


def _load_payload(path: Path) -> dict[str, Any]:
    raw = path.read_text(encoding="utf-8")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("JSON root must be an object")
    return data


def _activities_csv_from_payload(data: dict[str, Any]) -> str:
    log = data.get("activitiesLog")
    if log is None:
        raise KeyError("Missing 'activitiesLog' key (expected submission API shape)")
    if not isinstance(log, str):
        raise TypeError("activitiesLog must be a string (embedded CSV)")
    return log


def _parse_activities(csv_text: str) -> list[dict[str, str]]:
    reader = csv.DictReader(io.StringIO(csv_text), delimiter=";")
    rows: list[dict[str, str]] = []
    for row in reader:
        rows.append({k.strip(): (v or "").strip() for k, v in row.items()})
    return rows


def _final_pnl_by_key(rows: list[dict[str, str]]) -> tuple[dict[tuple[str, str], float], float]:
    """Latest row per (day, product) by timestamp; return map and sum of those finals."""
    best: dict[tuple[str, str], tuple[int, float]] = {}
    for row in rows:
        day = row.get("day", "")
        ts_raw = row.get("timestamp", "")
        product = row.get("product", "")
        pnl_raw = row.get("profit_and_loss", "")
        if not product or not ts_raw:
            continue
        try:
            ts = int(ts_raw)
        except ValueError:
            continue
        try:
            pnl = float(pnl_raw) if pnl_raw else 0.0
        except ValueError:
            continue
        key = (day, product)
        prev = best.get(key)
        if prev is None or ts >= prev[0]:
            best[key] = (ts, pnl)
    finals: dict[tuple[str, str], float] = {k: v[1] for k, v in best.items()}
    total = sum(finals.values())
    return finals, total


def _markdown_report(
    submission_id: str | None,
    finals: dict[tuple[str, str], float],
    total: float,
    row_count: int,
) -> str:
    lines = [
        "# Official submission log analysis",
        "",
    ]
    if submission_id:
        lines.append(f"- **submissionId:** `{submission_id}`")
    lines.extend(
        [
            f"- **CSV rows parsed:** {row_count}",
            f"- **Sum of last profit_and_loss per (day, product):** {total:,.2f}",
            "",
            "## Final PnL by day and product",
            "",
            "| Day | Product | Final PnL |",
            "|-----|---------|----------:|",
        ]
    )
    for (day, product) in sorted(finals.keys()):
        lines.append(f"| {day} | {product} | {finals[(day, product)]:,.2f} |")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze saved Prosperity activitiesLog JSON.")
    parser.add_argument(
        "json_path",
        type=Path,
        help="Path to JSON file with submissionId and activitiesLog",
    )
    parser.add_argument(
        "-o",
        "--out",
        type=Path,
        default=None,
        help="Write markdown report to this path (UTF-8)",
    )
    args = parser.parse_args()

    if not args.json_path.is_file():
        print(f"File not found: {args.json_path}", file=sys.stderr)
        return 1

    try:
        data = _load_payload(args.json_path)
        csv_text = _activities_csv_from_payload(data)
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    rows = _parse_activities(csv_text)
    if not rows:
        print("No CSV rows parsed (empty activitiesLog?).", file=sys.stderr)
        return 1

    finals, total = _final_pnl_by_key(rows)
    sid = data.get("submissionId")
    sid_str = str(sid) if sid is not None else None

    report = _markdown_report(sid_str, finals, total, len(rows))
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(report, encoding="utf-8")
        print(f"Wrote {args.out}")
    else:
        print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
