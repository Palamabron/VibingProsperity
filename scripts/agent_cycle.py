"""
Run data analytics + backtest, then write an English report stub under reports/runs/
and refresh reports/INDEX.md. Intended for agent-in-the-loop (e.g. Gemini Pro) workflows.

Usage:
  uv run python scripts/agent_cycle.py
  uv run python scripts/agent_cycle.py --round 0
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORTS = ROOT / "reports"
RUNS = REPORTS / "runs"
INDEX_PATH = REPORTS / "INDEX.md"


def _git_short_hash() -> str | None:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if r.returncode == 0:
            return r.stdout.strip()
    except OSError:
        pass
    return None


def _run_uv_script(script: str) -> tuple[int, str]:
    r = subprocess.run(
        ["uv", "run", script],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    out = (r.stdout or "") + (r.stderr or "")
    return r.returncode, out


def _run_backtest(round_n: int) -> tuple[int, str]:
    cmd = [
        "uv",
        "run",
        "backtest.py",
        "--round",
        str(round_n),
        "--merge-pnl",
        "--no-progress",
        "--no-out",
    ]
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    out = (r.stdout or "") + (r.stderr or "")
    return r.returncode, out


def _parse_total_profit(text: str) -> int | None:
    last = None
    for m in re.finditer(r"Total profit:\s*([\d,]+)", text):
        last = m.group(1)
    if last is None:
        return None
    return int(last.replace(",", ""))


def _report_filename_ts() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _rebuild_index() -> None:
    RUNS.mkdir(parents=True, exist_ok=True)
    files = sorted(RUNS.glob("*_experiment.md"), reverse=True)
    lines: list[str] = [
        "# Experiment index",
        "",
        "Newest first (from YAML front matter in each run file).",
        "",
    ]
    for path in files[:40]:
        raw = path.read_text(encoding="utf-8")
        m_tp = re.search(r"^total_profit:\s*(\d+)\s*$", raw, re.MULTILINE)
        m_r = re.search(r"^round:\s*(\d+)\s*$", raw, re.MULTILINE)
        rel = path.relative_to(REPORTS).as_posix()
        tp = m_tp.group(1) if m_tp else "n/a"
        rn = m_r.group(1) if m_r else "?"
        lines.append(
            f"- [`{path.name}`]({rel}) — round **{rn}**, total profit **{tp}** (merged PnL)"
        )
    lines.append("")
    INDEX_PATH.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Data analytics + backtest + English report stub.")
    parser.add_argument("--round", type=int, default=0, help="Backtest round (default: 0)")
    args = parser.parse_args()

    REPORTS.mkdir(parents=True, exist_ok=True)
    RUNS.mkdir(parents=True, exist_ok=True)

    ts = _report_filename_ts()
    stamp_human = datetime.now().strftime("%Y-%m-%d %H:%M")
    report_path = RUNS / f"{ts}_experiment.md"

    code_da, out_da = _run_uv_script("data_analytics.py")
    code_bt, out_bt = _run_backtest(args.round)

    total_profit = _parse_total_profit(out_bt)
    git_h = _git_short_hash()

    front = [
        "---",
        f'experiment_id: "{ts}"',
        f"round: {args.round}",
        "merged_pnl: true",
    ]
    if total_profit is not None:
        front.append(f"total_profit: {total_profit}")
    front.append("---")
    front.append("")

    body = [
        f"# Experiment report — {stamp_human} (local)",
        "",
        "## Metadata",
        "",
        f"- **Round:** {args.round} (merged PnL across days in that round)",
        f"- **data_analytics exit code:** {code_da}",
        f"- **backtest exit code:** {code_bt}",
    ]
    if git_h:
        body.append(f"- **Git:** `{git_h}`")
    body.extend(
        [
            "",
            "## Raw: data analytics",
            "",
            "```text",
            out_da.rstrip() or "(no output)",
            "```",
            "",
            "## Raw: backtest",
            "",
            "```text",
            out_bt.rstrip() or "(no output)",
            "```",
            "",
            "## Insights *(agent / human — fill in English)*",
            "",
            "- ",
            "",
            "## Hypotheses for next iteration *(English)*",
            "",
            "- ",
            "",
            "## Algorithm changes summary *(English)*",
            "",
            "- ",
            "",
        ]
    )

    report_path.write_text("\n".join(front + body), encoding="utf-8")
    _rebuild_index()

    print(f"Wrote {report_path.relative_to(ROOT)}")
    print(f"Updated {INDEX_PATH.relative_to(ROOT)}")
    if code_da != 0 or code_bt != 0:
        msg = "Warning: a subprocess returned non-zero; check raw sections in the report."
        print(msg, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
