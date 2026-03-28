from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import tyro
from loguru import logger

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from report_utils import format_front_matter_yaml, rebuild_experiment_index  # noqa: E402
from submit_live import submit_and_wait  # noqa: E402

RUNS = ROOT / "reports" / "runs"
REPORTS = ROOT / "reports"
INDEX = REPORTS / "INDEX.md"

RUNS.mkdir(parents=True, exist_ok=True)


def _run_analytics() -> str:
    try:
        r = subprocess.run(
            ["uv", "run", "data_analytics.py"],
            capture_output=True,
            text=True,
            cwd=ROOT,
            timeout=120,
        )
        return r.stdout or "(no analytics output)"
    except Exception as exc:
        return f"(data_analytics skipped: {exc})"


def _write_report(ts: str, algo_path: Path, result: dict[str, Any]) -> Path:
    profit = result.get("total_profit")
    per_prod = result.get("per_product", {})
    sub_id = result.get("submission_id", "n/a")
    status = result.get("status", "unknown")
    error = result.get("error")
    log_path = result.get("log_path")
    analytics = _run_analytics()

    fm: dict[str, Any] = {
        "experiment_id": ts,
        "source": "live",
        "submission_id": str(sub_id),
        "status": str(status),
        "timestamp": ts,
        "round": None,
    }
    if profit is not None:
        fm["total_profit"] = int(profit)
    else:
        fm["total_profit"] = None

    lines = [
        format_front_matter_yaml(fm).rstrip(),
        "",
        f"# Live Experiment — {ts}",
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
        lines += (
            [
                "| Product | PnL |",
                "|---------|-----|",
            ]
            + [f"| {p} | {v:+,.0f} |" for p, v in sorted(per_prod.items())]
            + [""]
        )

    if error:
        lines += ["## Error", "", f"```\n{error}\n```", ""]

    if log_path:
        lines += [f"**Log:** `{log_path}`", ""]

    lines += ["## Data Analytics", "", "```", analytics.strip(), "```", ""]

    path = RUNS / f"{ts}_experiment.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def run_cycle(algo_path: Path | None = None) -> dict[str, Any]:
    if algo_path is None:
        algo_path = ROOT / "algorithm.py"

    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    logger.info("{}", "=" * 60)
    logger.info("AGENT CYCLE LIVE — {}", ts)
    logger.info("{}", "=" * 60)

    result = submit_and_wait(algo_path)
    report = _write_report(ts, algo_path, result)
    logger.info("[cycle] report → {}", report.relative_to(ROOT))

    rebuild_experiment_index(runs_dir=RUNS, index_path=INDEX, reports_root=REPORTS)

    json_path = RUNS / f"{ts}_live.json"
    json_path.write_text(json.dumps(result, indent=2), encoding="utf-8")

    result["report_path"] = str(report)
    return result


@dataclass
class AgentCycleLiveArgs:
    """One live submission cycle."""

    algo: Path | None = None
    """Trader file to submit (default: ./algorithm.py)."""


if __name__ == "__main__":
    args = tyro.cli(AgentCycleLiveArgs)
    r = run_cycle(args.algo)
    sys.exit(0 if r["status"] == "success" else 1)
