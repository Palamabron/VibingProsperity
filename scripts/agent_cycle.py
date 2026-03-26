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
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORTS = ROOT / "reports"
RUNS = REPORTS / "runs"
INDEX_PATH = REPORTS / "INDEX.md"


@dataclass
class _DayBlock:
    round_n: int
    day: int
    products: dict[str, int]
    total: int


@dataclass
class _ParsedBacktest:
    merged_total: int | None
    profit_summary_days: list[tuple[int, int, int]]
    day_blocks: list[_DayBlock] = field(default_factory=list)


_BT_DAY_HEADER = re.compile(
    r"^Backtesting .+ on round (\d+) day (-?\d+)\s*$",
    re.MULTILINE,
)
_BT_PRODUCT_LINE = re.compile(r"^([A-Z0-9_]+):\s*([\d,]+)\s*$", re.MULTILINE)
_BT_TOTAL_PROFIT = re.compile(r"^Total profit:\s*([\d,]+)\s*$", re.MULTILINE)
_BT_SUMMARY_DAY = re.compile(r"^Round (\d+) day (-?\d+):\s*([\d,]+)\s*$", re.MULTILINE)


def _parse_prosperity4btx_text(text: str) -> _ParsedBacktest:
    day_blocks: list[_DayBlock] = []
    for m in _BT_DAY_HEADER.finditer(text):
        start = m.end()
        next_m = _BT_DAY_HEADER.search(text, start)
        end = next_m.start() if next_m else len(text)
        chunk = text[start:end]
        r, d = int(m.group(1)), int(m.group(2))
        products: dict[str, int] = {}
        for pm in _BT_PRODUCT_LINE.finditer(chunk):
            name = pm.group(1)
            if name == "Total":
                continue
            products[name] = int(pm.group(2).replace(",", ""))
        tm = _BT_TOTAL_PROFIT.search(chunk)
        total = int(tm.group(1).replace(",", "")) if tm else 0
        day_blocks.append(_DayBlock(round_n=r, day=d, products=products, total=total))

    profit_summary_days: list[tuple[int, int, int]] = []
    if "Profit summary:" in text:
        tail = text.split("Profit summary:", 1)[1]
        for sm in _BT_SUMMARY_DAY.finditer(tail):
            profit_summary_days.append(
                (int(sm.group(1)), int(sm.group(2)), int(sm.group(3).replace(",", "")))
            )

    merged_total: int | None = None
    for m in _BT_TOTAL_PROFIT.finditer(text):
        merged_total = int(m.group(1).replace(",", ""))

    return _ParsedBacktest(
        merged_total=merged_total,
        profit_summary_days=profit_summary_days,
        day_blocks=day_blocks,
    )


def _aggregate_product_pnl(day_blocks: list[_DayBlock]) -> dict[str, int]:
    agg: dict[str, int] = {}
    for b in day_blocks:
        for k, v in b.products.items():
            agg[k] = agg.get(k, 0) + v
    return agg


def _previous_experiment_totals() -> tuple[int | None, str | None]:
    """Newest existing report (before the one we are about to write)."""
    files = sorted(RUNS.glob("*_experiment.md"), reverse=True)
    if not files:
        return None, None
    raw = files[0].read_text(encoding="utf-8")
    m = re.search(r"^total_profit:\s*(\d+)\s*$", raw, re.MULTILINE)
    profit = int(m.group(1)) if m else None
    return profit, files[0].name


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
    parsed_bt: _ParsedBacktest,
    total_profit: int | None,
    code_da: int,
    out_da: str,
) -> list[str]:
    bullets: list[str] = []
    if total_profit is not None:
        bullets.append(f"Merged backtest **total_profit** for this run: **{total_profit:,}**.")
    prev_p, prev_name = _previous_experiment_totals()
    if prev_p is not None and total_profit is not None and prev_name:
        delta = total_profit - prev_p
        sign = "+" if delta >= 0 else ""
        bullets.append(
            f"Previous report `{prev_name}` had total_profit **{prev_p:,}** → Δ **{sign}{delta:,}** vs that file."
        )
    if parsed_bt.day_blocks:
        parts = [f"round {b.round_n} day {b.day}: **{b.total:,}**" for b in parsed_bt.day_blocks]
        bullets.append("Per-day totals: " + "; ".join(parts) + ".")
    agg = _aggregate_product_pnl(parsed_bt.day_blocks)
    if agg:
        ranked = sorted(agg.items(), key=lambda kv: kv[1], reverse=True)
        detail = ", ".join(f"**{k}** {v:,}" for k, v in ranked)
        top, top_v = ranked[0]
        bullets.append(
            f"PnL by product (sum over days in this run): {detail}; largest contributor: **{top}** ({top_v:,})."
        )
    knobs = _extract_reference_knobs_line(out_da)
    if knobs:
        bullets.append(f"Data analytics {knobs}")
    if code_da != 0:
        bullets.append(f"`data_analytics.py` exited with code **{code_da}**; interpret raw block with care.")
    if not bullets:
        bullets.append("(No metrics extracted; check raw sections above.)")
    return bullets


def _auto_hypothesis_bullets(out_da: str) -> list[str]:
    bullets: list[str] = []
    takers = _parse_taker_means(out_da)
    for sym, (buy_r, sell_r) in sorted(takers.items()):
        if buy_r < 1e-6 and sell_r < 1e-6:
            bullets.append(
                f"**{sym}** taker opportunity rates vs ref fair are ~0 — taker leg may rarely fire; "
                "test a lower `TAKER_THRESHOLD` or lean on maker/quoting unless fills are already good."
            )
        elif buy_r + sell_r < 0.002:
            bullets.append(
                f"**{sym}** shows very low combined taker opportunity rate — small threshold tweaks may materially change crosses."
            )
    if not bullets:
        bullets.append(
            "Use per-day PnL and spreads in the raw analytics block to pick one symbol or parameter to adjust next."
        )
    bullets.append(
        "After edits, re-run `uv run python scripts/agent_cycle.py` on the **same** round / `match_trades` / data layout for a fair comparison."
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
            "If you already committed, describe what changed since the last report in a bullet below."
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
        body = body[:max_diff_chars] + "\n... (truncated; see `git diff HEAD -- algorithm.py` locally)\n"
    lines.append("```diff")
    lines.append(body.rstrip())
    lines.append("```")
    return "\n".join(lines)


def _format_parsed_backtest_markdown(pb: _ParsedBacktest) -> str:
    lines = [
        "## Parsed backtest metrics *(auto)*",
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


def _describe_backtest_data(data_arg: Path | None, no_auto: bool) -> str:
    if data_arg is not None:
        p = data_arg.resolve()
        try:
            return str(p.relative_to(ROOT))
        except ValueError:
            return str(p)
    if no_auto:
        return "packaged default (prosperity4btx)"
    data_root = ROOT / "data"
    r0 = data_root / "round0"
    if r0.is_dir() and any(r0.glob("prices_*.csv")):
        return f"{data_root.relative_to(ROOT)} (auto, prosperity4btx layout)"
    return "packaged default (prosperity4btx)"


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


def _run_backtest(
    round_n: int,
    *,
    out_log: Path | None,
    match_trades: str,
    data: Path | None,
    no_auto_data: bool,
    original_timestamps: bool,
) -> tuple[int, str]:
    cmd = [
        "uv",
        "run",
        "backtest.py",
        "--round",
        str(round_n),
        "--merge-pnl",
        "--no-progress",
        "--match-trades",
        match_trades,
    ]
    if original_timestamps:
        cmd.append("--original-timestamps")
    if data is not None:
        cmd.extend(["--data", str(data.resolve())])
    if no_auto_data:
        cmd.append("--no-auto-data")
    if out_log is not None:
        out_log.parent.mkdir(parents=True, exist_ok=True)
        cmd.extend(["--out", str(out_log.resolve())])
    else:
        cmd.append("--no-out")
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
    parser.add_argument(
        "--match-trades",
        choices=("all", "worse", "none"),
        default="worse",
        help=(
            "Forwarded to prosperity4btx (default: worse — stricter; 'all' = lenient replay)."
        ),
    )
    parser.add_argument(
        "--data",
        type=Path,
        default=None,
        help="Optional --data dir for backtest (else ./data auto if present).",
    )
    parser.add_argument(
        "--no-auto-data",
        action="store_true",
        help="Forward --no-auto-data to backtest.py (ignore ./data).",
    )
    parser.add_argument(
        "--original-timestamps",
        action="store_true",
        help=(
            "Pass --original-timestamps to prosperity4btx. "
            "Opt-in: merge-pnl + --out crashes on prosperity4btx 0.0.2."
        ),
    )
    parser.add_argument(
        "--no-backtest-log",
        action="store_true",
        help="Do not pass --out to prosperity4btx (skip visualizer .log artifact).",
    )
    args = parser.parse_args()

    REPORTS.mkdir(parents=True, exist_ok=True)
    RUNS.mkdir(parents=True, exist_ok=True)

    ts = _report_filename_ts()
    stamp_human = datetime.now().strftime("%Y-%m-%d %H:%M")
    report_path = RUNS / f"{ts}_experiment.md"

    backtests_dir = REPORTS / "backtests"
    bt_log: Path | None = None
    if not args.no_backtest_log:
        bt_log = backtests_dir / f"{ts}_round{args.round}.log"

    code_da, out_da = _run_uv_script("data_analytics.py")
    code_bt, out_bt = _run_backtest(
        args.round,
        out_log=bt_log,
        match_trades=args.match_trades,
        data=args.data,
        no_auto_data=args.no_auto_data,
        original_timestamps=args.original_timestamps,
    )

    total_profit = _parse_total_profit(out_bt)
    parsed_bt = _parse_prosperity4btx_text(out_bt)
    parsed_md = _format_parsed_backtest_markdown(parsed_bt)
    insight_bullets = _auto_insight_bullets(parsed_bt, total_profit, code_da, out_da)
    hypothesis_bullets = _auto_hypothesis_bullets(out_da)
    algo_changes_md = _auto_algorithm_changes_markdown()
    git_h = _git_short_hash()
    use_orig_ts = args.original_timestamps
    data_desc = _describe_backtest_data(args.data, args.no_auto_data)

    front = [
        "---",
        f'experiment_id: "{ts}"',
        f"round: {args.round}",
        "merged_pnl: true",
        f'match_trades: "{args.match_trades}"',
        f"original_timestamps: {str(use_orig_ts).lower()}",
        f'backtest_data: "{data_desc}"',
    ]
    if total_profit is not None:
        front.append(f"total_profit: {total_profit}")
    if bt_log is not None:
        front.append(f'backtest_visualizer_log: "{bt_log.relative_to(ROOT).as_posix()}"')
    front.append("---")
    front.append("")

    body = [
        f"# Experiment report — {stamp_human} (local)",
        "",
        "## Metadata",
        "",
        f"- **Round:** {args.round} (merged PnL across days in that round)",
        f"- **match_trades:** `{args.match_trades}` (prosperity4btx)",
        f"- **backtest data:** `{data_desc}`",
        f"- **original_timestamps (log):** {use_orig_ts}",
        f"- **data_analytics exit code:** {code_da}",
        f"- **backtest exit code:** {code_bt}",
    ]
    if git_h:
        body.append(f"- **Git:** `{git_h}`")
    if bt_log is not None:
        body.append(
            f"- **Visualizer log:** `{bt_log.relative_to(ROOT)}` → "
            "[Prosperity Visualizer](https://prosperity.equirag.com/)"
        )
    body.extend(
        [
            "",
            "## Official platform *(human)*",
            "",
            (
                "After you submit on [the game site](https://prosperity.imc.com/game), "
                "save the JSON with `activitiesLog` under `reports/official/`, then run "
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
            "## Raw: backtest",
            "",
            "```text",
            out_bt.rstrip() or "(no output)",
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
