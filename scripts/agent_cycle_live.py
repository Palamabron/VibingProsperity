from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from submit_live import submit_and_wait  # noqa: E402

RUNS  = ROOT / "reports" / "runs"
INDEX = ROOT / "reports" / "INDEX.md"

RUNS.mkdir(parents=True, exist_ok=True)


def _run_analytics() -> str:
    try:
        r = subprocess.run(
            ["uv", "run", "data_analytics.py"],
            capture_output=True, text=True, cwd=ROOT, timeout=120,
        )
        return r.stdout or "(no analytics output)"
    except Exception as exc:
        return f"(data_analytics skipped: {exc})"


def _write_report(ts: str, algo_path: Path, result: dict) -> Path:
    profit    = result.get("total_profit")
    per_prod  = result.get("per_product", {})
    sub_id    = result.get("submission_id", "n/a")
    status    = result.get("status", "unknown")
    error     = result.get("error")
    log_path  = result.get("log_path")
    analytics = _run_analytics()

    header = (
        f"total_profit: {profit}\n"
        f"submission_id: {sub_id}\n"
        f"status: {status}\n"
        f"timestamp: {ts}\n"
    )

    lines = [
        f"# Live Experiment — {ts}",
        "",
        "```",
        header.strip(),
        "```",
        "",
        f"**Algorithm:** `{algo_path.name}`  ",
        f"**Submission ID:** `{sub_id}`  ",
        f"**Status:** {status}  ",
        "",
        "## PnL",
        "",
    ]

    if profit is not None:
        lines.append(f"**Total: {profit:+,} SeaShells**")
        lines.append("")

    if per_prod:
        lines += [
            "| Product | PnL |",
            "|---------|-----|",
        ] + [f"| {p} | {v:+,.0f} |" for p, v in sorted(per_prod.items())] + [""]

    if error:
        lines += ["## Error", "", f"```\n{error}\n```", ""]

    if log_path:
        lines += [f"**Log:** `{log_path}`", ""]

    lines += ["## Data Analytics", "", "```", analytics.strip(), "```", ""]

    path = RUNS / f"{ts}_experiment.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _update_index(report: Path, profit: int | None, ts: str) -> None:
    profit_str = f"{profit:+,}" if profit is not None else "N/A"
    entry = f"| [{ts}]({report.relative_to(ROOT)}) | {profit_str} | live |\n"
    if INDEX.exists():
        existing = INDEX.read_text(encoding="utf-8")
    else:
        existing = (
            "# Experiment Index\n\n"
            "| Run | Profit (SeaShells) | Source |\n"
            "|-----|--------------------|--------|\n"
        )
    lines  = existing.splitlines(keepends=True)
    insert = next((i for i, l in enumerate(lines) if l.startswith("|-----")), len(lines)) + 1
    lines.insert(insert, entry)
    INDEX.write_text("".join(lines), encoding="utf-8")


def run_cycle(algo_path: Path | None = None) -> dict:
    if algo_path is None:
        algo_path = ROOT / "algorithm.py"

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    print(f"\n{'='*60}")
    print(f"  AGENT CYCLE LIVE  —  {ts}")
    print(f"{'='*60}\n")

    result = submit_and_wait(algo_path)
    report = _write_report(ts, algo_path, result)
    print(f"[cycle] report → {report.relative_to(ROOT)}")

    _update_index(report, result.get("total_profit"), ts)

    json_path = RUNS / f"{ts}_live.json"
    json_path.write_text(json.dumps(result, indent=2), encoding="utf-8")

    result["report_path"] = str(report)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="One live submission cycle")
    parser.add_argument("--algo", type=Path, default=None)
    args = parser.parse_args()
    r = run_cycle(args.algo)
    sys.exit(0 if r["status"] == "success" else 1)
