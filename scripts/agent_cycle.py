"""
Run data analytics + live platform evaluation (upload via scripts/submit_live.py), then write
an English report stub under reports/runs/ and refresh reports/INDEX.md.

Requires a valid Cognito token: set PROSPERITY_ID_TOKEN, or PROSPERITY_EMAIL + PROSPERITY_PASSWORD
for automatic refresh (see scripts/get_token.py, scripts/prosperity_token.py).

Usage:
  uv run python scripts/agent_cycle.py
  uv run python scripts/agent_cycle.py --algorithm algorithm.py

Timeouts default from env AGENT_CYCLE_TIMEOUT_* (see README); subprocesses may return
exit 124 on timeout.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import tyro
from loguru import logger

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from report_utils import (  # noqa: E402
    DayBlock,
    ParsedBacktest,
    parsed_backtest_from_live_result,
    previous_experiment_totals,
    rebuild_experiment_index,
)
from submit_live import submit_and_wait  # noqa: E402

REPORTS = ROOT / "reports"
RUNS = REPORTS / "runs"
INDEX_PATH = REPORTS / "INDEX.md"


def _aggregate_product_pnl(day_blocks: list[DayBlock]) -> dict[str, int]:
    agg: dict[str, int] = {}
    for b in day_blocks:
        for k, v in b.products.items():
            agg[k] = agg.get(k, 0) + v
    return agg


def _extract_reference_knobs_line(analytics_text: str) -> str | None:
    for line in analytics_text.splitlines():
        if "Reference knobs:" in line and line.strip().startswith("Reference knobs:"):
            return line.strip()
    return None


def _parse_taker_means(analytics_text: str) -> dict[str, tuple[float, float]]:
    """symbol -> (mean_buy_rate, mean_sell_rate) from 'SYMBOL_taker_*_rate: mean=...' lines."""
    out: dict[str, tuple[float, float]] = {}
    buy_m = re.findall(
        r"^\s+([A-Z0-9_]+)_taker_buy_rate:\s*mean=([\d.]+)",
        analytics_text,
        re.MULTILINE,
    )
    sell_m = re.findall(
        r"^\s+([A-Z0-9_]+)_taker_sell_rate:\s*mean=([\d.]+)",
        analytics_text,
        re.MULTILINE,
    )
    buy_d = {k: float(v) for k, v in buy_m}
    sell_d = {k: float(v) for k, v in sell_m}
    keys = set(buy_d) | set(sell_d)
    for k in keys:
        out[k] = (buy_d.get(k, 0.0), sell_d.get(k, 0.0))
    return out


def _auto_insight_bullets(
    parsed_bt: ParsedBacktest,
    total_profit: int | None,
    code_da: int,
    out_da: str,
) -> list[str]:
    bullets: list[str] = []
    if total_profit is not None:
        bullets.append(f"Platform run **total_profit** (graph / log): **{total_profit:,}**.")
    prev_p, prev_name = previous_experiment_totals(RUNS)
    if prev_p is not None and total_profit is not None and prev_name:
        delta = total_profit - prev_p
        sign = "+" if delta >= 0 else ""
        bullets.append(
            f"Previous report `{prev_name}` had total_profit **{prev_p:,}** → "
            f"Δ **{sign}{delta:,}** vs that file."
        )
    if parsed_bt.day_blocks:
        parts = [f"round {b.round_n} day {b.day}: **{b.total:,}**" for b in parsed_bt.day_blocks]
        bullets.append("Synthetic day row from per-product PnL: " + "; ".join(parts) + ".")
    agg = _aggregate_product_pnl(parsed_bt.day_blocks)
    if agg:
        ranked = sorted(agg.items(), key=lambda kv: kv[1], reverse=True)
        detail = ", ".join(f"**{k}** {v:,}" for k, v in ranked)
        top, top_v = ranked[0]
        bullets.append(
            f"PnL by product (from zip log when available): {detail}; "
            f"largest contributor: **{top}** ({top_v:,})."
        )
    knobs = _extract_reference_knobs_line(out_da)
    if knobs:
        bullets.append(f"Data analytics {knobs}")
    if code_da != 0:
        bullets.append(
            f"`data_analytics.py` exited with code **{code_da}**; interpret raw block with care."
        )
    if not bullets:
        bullets.append("(No metrics extracted; check raw sections above.)")
    return bullets


def _auto_hypothesis_bullets(out_da: str) -> list[str]:
    bullets: list[str] = []
    takers = _parse_taker_means(out_da)
    for sym, (buy_r, sell_r) in sorted(takers.items()):
        if buy_r < 1e-6 and sell_r < 1e-6:
            bullets.append(
                f"**{sym}** taker opportunity rates vs ref fair are ~0 — "
                "taker leg may rarely fire; test a lower `TAKER_THRESHOLD` or lean on "
                "maker/quoting unless fills are already good."
            )
        elif buy_r + sell_r < 0.002:
            bullets.append(
                f"**{sym}** shows very low combined taker opportunity rate — small threshold "
                "tweaks may materially change crosses."
            )
    if not bullets:
        bullets.append(
            "Use per-day PnL and spreads in the raw analytics block to pick one symbol or "
            "parameter to adjust next."
        )
    bullets.append(
        "After edits, re-run `uv run python scripts/agent_cycle.py` for another "
        "uploaded evaluation on the same platform."
    )
    return bullets


def _auto_algorithm_changes_markdown(max_diff_chars: int = 12_000) -> str:
    lines: list[str] = []
    try:
        st = subprocess.run(
            ["git", "diff", "--stat", "HEAD", "--", "algorithm.py"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        df = subprocess.run(
            ["git", "diff", "--no-color", "HEAD", "--", "algorithm.py"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return "- (Could not run `git diff`; summarize `algorithm.py` changes manually.)"

    stat_out = (st.stdout or "").strip()
    diff_out = (df.stdout or "").strip()

    if not diff_out:
        lines.append(
            "- No **uncommitted** changes in `algorithm.py` vs `HEAD`. "
            "If you already committed, describe what changed since the last report in a bullet "
            "below."
        )
        gh = _git_short_hash()
        if gh:
            lines.append(f"- Current `HEAD`: `{gh}`.")
        return "\n".join(lines)

    if stat_out:
        lines.append("- `git diff --stat HEAD -- algorithm.py`:")
        lines.append("")
        lines.append("```text")
        lines.append(stat_out)
        lines.append("```")
        lines.append("")
    lines.append("- Patch (truncated if very large):")
    lines.append("")
    body = diff_out
    if len(body) > max_diff_chars:
        body = (
            body[:max_diff_chars]
            + "\n... (truncated; see `git diff HEAD -- algorithm.py` locally)\n"
        )
    lines.append("```diff")
    lines.append(body.rstrip())
    lines.append("```")
    return "\n".join(lines)


def _format_parsed_backtest_markdown(pb: ParsedBacktest) -> str:
    lines = [
        "## Parsed platform metrics *(auto)*",
        "",
    ]
    if pb.day_blocks:
        lines.append("| Round | Day | Products (PnL) | Day total |")
        lines.append("|------:|----:|-----------------|----------:|")
        for b in pb.day_blocks:
            prod = ", ".join(f"{k} {v:,}" for k, v in sorted(b.products.items()))
            lines.append(f"| {b.round_n} | {b.day} | {prod} | {b.total:,} |")
        lines.append("")
    if pb.profit_summary_days:
        lines.append("**Profit summary (merged run):**")
        for r, d, t in pb.profit_summary_days:
            lines.append(f"- Round {r} day {d}: **{t:,}**")
        lines.append("")
    if pb.merged_total is not None:
        lines.append(f"**Merged total profit:** **{pb.merged_total:,}**")
        lines.append("")
    return "\n".join(lines)


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


def _run_uv_script(script: str, *, timeout: float | None) -> tuple[int, str]:
    try:
        r = subprocess.run(
            ["uv", "run", script],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        out = (r.stdout or "") + (r.stderr or "")
        return r.returncode, out
    except subprocess.TimeoutExpired as exc:
        msg = f"(timeout after {timeout}s)\n{exc}"
        return 124, msg


def _env_timeout(name: str, default: str) -> float | None:
    raw = os.environ.get(name, default).strip()
    if raw == "" or raw.lower() in ("none", "inf"):
        return None
    return float(raw)


def _report_filename_ts() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _format_submit_raw(result: dict[str, Any]) -> str:
    slim = {k: v for k, v in result.items() if k != "log_text"}
    chunks: list[str] = [json.dumps(slim, indent=2)]
    lt = result.get("log_text")
    if isinstance(lt, str) and lt.strip():
        chunks.append("\n--- log_text (truncated) ---\n")
        chunks.append(lt[:12_000] + ("…" if len(lt) > 12_000 else ""))
    return "\n".join(chunks)


@dataclass
class AgentCycleArgs:
    """Data analytics + live upload + English report stub."""

    algorithm: Path | None = None
    """Trader file to upload (default: ./algorithm.py)."""

    timeout_data_analytics: float | None = None
    """Seconds for data_analytics (env AGENT_CYCLE_TIMEOUT_DATA_ANALYTICS or 300; 0 = no limit)."""


def main() -> int:
    args = tyro.cli(AgentCycleArgs)

    def _resolve_timeout(cli: float | None, env_name: str, default: str) -> float | None:
        if cli is not None:
            return None if cli <= 0 else cli
        return _env_timeout(env_name, default)

    to_da = _resolve_timeout(
        args.timeout_data_analytics,
        "AGENT_CYCLE_TIMEOUT_DATA_ANALYTICS",
        "300",
    )

    algo_path = (args.algorithm or (ROOT / "algorithm.py")).resolve()
    if not algo_path.is_file():
        logger.error("Algorithm file not found: {}", algo_path)
        return 2

    REPORTS.mkdir(parents=True, exist_ok=True)
    RUNS.mkdir(parents=True, exist_ok=True)

    ts = _report_filename_ts()
    stamp_human = datetime.now().strftime("%Y-%m-%d %H:%M")
    report_path = RUNS / f"{ts}_experiment.md"

    code_da, out_da = _run_uv_script("data_analytics.py", timeout=to_da)

    result = submit_and_wait(algo_path)
    parsed_bt = parsed_backtest_from_live_result(result)
    total_profit = result.get("total_profit")
    if isinstance(total_profit, float):
        total_profit = int(round(total_profit))
    elif total_profit is not None:
        total_profit = int(total_profit)

    parsed_md = _format_parsed_backtest_markdown(parsed_bt)
    insight_bullets = _auto_insight_bullets(parsed_bt, total_profit, code_da, out_da)
    hypothesis_bullets = _auto_hypothesis_bullets(out_da)
    algo_changes_md = _auto_algorithm_changes_markdown()
    git_h = _git_short_hash()

    ok_submit = result.get("status") == "success"
    code_submit = 0 if ok_submit else 1

    front = [
        "---",
        f'experiment_id: "{ts}"',
        "source: live",
        "round: null",
        f'submission_id: "{result.get("submission_id") or ""}"',
        f'status: "{result.get("status") or ""}"',
    ]
    if total_profit is not None:
        front.append(f"total_profit: {total_profit}")
    lp = result.get("log_path")
    if isinstance(lp, str) and lp:
        front.append(f'submission_log: "{lp}"')
    front.append("---")
    front.append("")

    body = [
        f"# Experiment report — {stamp_human} (live platform)",
        "",
        "## Metadata",
        "",
        f"- **Algorithm file:** `{algo_path.relative_to(ROOT)}`",
        f"- **Submission ID:** `{result.get('submission_id')}`",
        f"- **Status:** {result.get('status')}",
        f"- **data_analytics exit code:** {code_da}",
        f"- **platform submit (agent_cycle):** exit **{code_submit}** (0 = success)",
    ]
    if git_h:
        body.append(f"- **Git:** `{git_h}`")
    if isinstance(lp, str) and lp:
        body.append(f"- **Downloaded log:** `{lp}`")
    body.extend(
        [
            "",
            "## Official platform *(human)*",
            "",
            (
                "Export JSON with `activitiesLog` from the site if you need a full audit trail; "
                "`uv run python scripts/analyze_official_log.py <file.json>`. "
                "See `reports/official/README.md`."
            ),
            "",
            parsed_md,
            "",
            "## Raw: data analytics",
            "",
            "```text",
            out_da.rstrip() or "(no output)",
            "```",
            "",
            "## Raw: submit_live result",
            "",
            "```text",
            _format_submit_raw(result).rstrip() or "(no output)",
            "```",
            "",
            "## Insights *(auto + agent; English)*",
            "",
            "> *Filled automatically from metrics below; edit for narrative.*",
            "",
            *[f"- {b}" for b in insight_bullets],
            "",
            "## Hypotheses for next iteration *(auto + agent; English)*",
            "",
            "> *Heuristic starters from analytics; replace with your testable ideas.*",
            "",
            *[f"- {b}" for b in hypothesis_bullets],
            "",
            "## Algorithm changes summary *(auto + agent; English)*",
            "",
            "> *Uncommitted `git diff` vs `HEAD` for `algorithm.py` when present.*",
            "",
            algo_changes_md,
            "",
        ]
    )

    report_path.write_text("\n".join(front + body), encoding="utf-8")
    rebuild_experiment_index(runs_dir=RUNS, index_path=INDEX_PATH, reports_root=REPORTS)

    logger.info("Wrote {}", report_path.relative_to(ROOT))
    logger.info("Updated {}", INDEX_PATH.relative_to(ROOT))
    if code_da != 0 or not ok_submit:
        logger.warning("data_analytics or platform run did not fully succeed; see report.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
