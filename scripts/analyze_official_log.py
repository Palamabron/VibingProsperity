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

import csv
import io
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import tyro
from loguru import logger
from tyro.conf import Positional


@dataclass
class AnalyzeOfficialLogArgs:
    """Analyze saved Prosperity activitiesLog JSON."""

    json_path: Positional[Path]
    """Path to JSON file with submissionId and activitiesLog."""

    out: Path | None = None
    """Write markdown report to this path (UTF-8). If omitted, print to stdout."""

    json_summary: Path | None = None
    """Optional path to write a machine-readable JSON summary of metrics."""


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


def _parse_activities(csv_text: str) -> tuple[list[dict[str, str]], list[str]]:
    reader = csv.DictReader(io.StringIO(csv_text), delimiter=";")
    fieldnames = list(reader.fieldnames or [])
    rows: list[dict[str, str]] = []
    for row in reader:
        rows.append({k.strip(): (v or "").strip() for k, v in row.items() if k})
    return rows, fieldnames


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


def _per_day_totals(finals: dict[tuple[str, str], float]) -> dict[str, float]:
    by_day: dict[str, float] = defaultdict(float)
    for (day, _), pnl in finals.items():
        by_day[day] += pnl
    return dict(sorted(by_day.items(), key=lambda x: x[0]))


def _product_totals(finals: dict[tuple[str, str], float]) -> dict[str, float]:
    by_prod: dict[str, float] = defaultdict(float)
    for (_, product), pnl in finals.items():
        by_prod[product] += pnl
    return dict(by_prod)


def _timestamp_bounds(rows: list[dict[str, str]]) -> tuple[int | None, int | None]:
    ts_vals: list[int] = []
    for row in rows:
        raw = row.get("timestamp", "")
        if not raw:
            continue
        try:
            ts_vals.append(int(raw))
        except ValueError:
            continue
    if not ts_vals:
        return None, None
    return min(ts_vals), max(ts_vals)


def _activity_counts(rows: list[dict[str, str]]) -> Counter[str]:
    """Count rows by `activity` or `type` column if present."""
    c: Counter[str] = Counter()
    for row in rows:
        act = row.get("activity") or row.get("type") or row.get("action")
        if act:
            c[act] += 1
    return c


def _markdown_report(
    submission_id: str | None,
    finals: dict[tuple[str, str], float],
    total: float,
    row_count: int,
    fieldnames: list[str],
    per_day: dict[str, float],
    per_product: dict[str, float],
    ts_min: int | None,
    ts_max: int | None,
    activities: Counter[str],
) -> str:
    lines = [
        "# Official submission log analysis",
        "",
        "## Summary",
        "",
    ]
    if submission_id:
        lines.append(f"- **submissionId:** `{submission_id}`")
    lines.extend(
        [
            f"- **CSV rows parsed:** {row_count}",
            f"- **Distinct (day, product) keys:** {len(finals)}",
            f"- **Sum of last profit_and_loss per (day, product):** {total:,.2f}",
        ]
    )
    if ts_min is not None and ts_max is not None:
        span = ts_max - ts_min
        lines.append(f"- **Timestamp range (raw ints):** {ts_min} … {ts_max} (span {span})")
    cols = ", ".join(fieldnames) if fieldnames else "(none)"
    lines.extend(["", f"- **CSV columns seen:** {cols}", ""])

    if per_day:
        lines.extend(
            [
                "## Per-day totals (from final PnL per key)",
                "",
                "| Day | Total PnL |",
                "|-----|------------:|",
            ]
        )
        for day, pnl in per_day.items():
            lines.append(f"| {day} | {pnl:,.2f} |")
        lines.append("")

    if per_product:
        ranked = sorted(per_product.items(), key=lambda x: x[1], reverse=True)
        lines.extend(
            [
                "## Per-product totals (sum of final PnL across days)",
                "",
                "| Product | Total PnL | Rank |",
                "|---------|----------:|-----:|",
            ]
        )
        for rank, (prod, pnl) in enumerate(ranked, start=1):
            lines.append(f"| {prod} | {pnl:,.2f} | {rank} |")
        lines.append("")
        best_p, best_v = ranked[0]
        worst_p, worst_v = ranked[-1]
        lines.extend(
            [
                "### Highlights",
                "",
                f"- **Largest contributor:** {best_p} ({best_v:,.2f})",
                f"- **Smallest contributor:** {worst_p} ({worst_v:,.2f})",
                "",
            ]
        )

    if activities:
        lines.extend(
            [
                "## Row counts by activity (if column present)",
                "",
                "| Activity | Rows |",
                "|----------|-----:|",
            ]
        )
        for act, n in activities.most_common():
            lines.append(f"| {act} | {n} |")
        lines.append("")

    lines.extend(
        [
            "## Final PnL by day and product",
            "",
            "| Day | Product | Final PnL |",
            "|-----|---------|----------:|",
        ]
    )
    for day, product in sorted(finals.keys()):
        lines.append(f"| {day} | {product} | {finals[(day, product)]:,.2f} |")
    lines.append("")
    return "\n".join(lines)


def _json_summary_dict(
    submission_id: str | None,
    finals: dict[tuple[str, str], float],
    total: float,
    row_count: int,
    fieldnames: list[str],
    per_day: dict[str, float],
    per_product: dict[str, float],
    ts_min: int | None,
    ts_max: int | None,
    activities: Counter[str],
) -> dict[str, Any]:
    best_prod = max(per_product.items(), key=lambda x: x[1]) if per_product else None
    worst_prod = min(per_product.items(), key=lambda x: x[1]) if per_product else None
    return {
        "submission_id": submission_id,
        "row_count": row_count,
        "distinct_day_product_keys": len(finals),
        "total_final_pnl_sum": total,
        "timestamp_min": ts_min,
        "timestamp_max": ts_max,
        "csv_columns": fieldnames,
        "per_day_totals": per_day,
        "per_product_totals": per_product,
        "best_product": {"name": best_prod[0], "pnl": best_prod[1]} if best_prod else None,
        "worst_product": {"name": worst_prod[0], "pnl": worst_prod[1]} if worst_prod else None,
        "activity_row_counts": dict(activities) if activities else {},
        "final_pnl_by_day_product": {
            f"{d}|{p}": v for (d, p), v in sorted(finals.items(), key=lambda x: (x[0][0], x[0][1]))
        },
    }


def run_analyze(args: AnalyzeOfficialLogArgs) -> int:
    if not args.json_path.is_file():
        logger.error("File not found: {}", args.json_path)
        return 1

    try:
        data = _load_payload(args.json_path)
        csv_text = _activities_csv_from_payload(data)
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
        logger.error("{}", e)
        return 1

    rows, fieldnames = _parse_activities(csv_text)
    if not rows:
        logger.error("No CSV rows parsed (empty activitiesLog?).")
        return 1

    finals, total = _final_pnl_by_key(rows)
    sid = data.get("submissionId")
    sid_str = str(sid) if sid is not None else None

    per_day = _per_day_totals(finals)
    per_product = _product_totals(finals)
    ts_min, ts_max = _timestamp_bounds(rows)
    activities = _activity_counts(rows)

    report = _markdown_report(
        sid_str,
        finals,
        total,
        len(rows),
        fieldnames,
        per_day,
        per_product,
        ts_min,
        ts_max,
        activities,
    )

    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(report, encoding="utf-8")
        logger.info("Wrote {}", args.out)
    else:
        print(report)

    if args.json_summary is not None:
        summary = _json_summary_dict(
            sid_str,
            finals,
            total,
            len(rows),
            fieldnames,
            per_day,
            per_product,
            ts_min,
            ts_max,
            activities,
        )
        args.json_summary.parent.mkdir(parents=True, exist_ok=True)
        args.json_summary.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        logger.info("Wrote JSON summary {}", args.json_summary)

    return 0


def main() -> int:
    args = tyro.cli(AnalyzeOfficialLogArgs)
    return run_analyze(args)


if __name__ == "__main__":
    raise SystemExit(main())
