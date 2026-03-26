"""
Overnight-style loop: Gemini proposes a full `algorithm.py`, backtest runs, keep-if-better.

Like autoresearch `train.py` iterations, but the metric is **backtest total profit** (not val_bpb).

Requires `GOOGLE_API_KEY` in `.env` (see `.env.example`).
Optional: `GEMINI_MODEL` (default: gemini-2.0-flash).

Usage:
  uv run autoresearch.py --iterations 5 --round 0
  uv run autoresearch.py --dry-run    # no API; run one agent_cycle only
  uv run autoresearch.py --reset-state # drop saved best (after changing --match-trades, etc.)
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from google import genai

ROOT = Path(__file__).resolve().parent
REPORTS = ROOT / "reports"
RUNS = REPORTS / "runs"
STATE_PATH = REPORTS / "autoresearch_state.json"
BEST_COPY = ROOT / "algorithm_best.py"

SYSTEM = """You edit an IMC Prosperity 4 Python trading algorithm.
You MUST output exactly ONE markdown fenced block:
```python
...full file contents...
```
Rules:
- The file must define `class Trader` with `run(self, state)` returning
  `(orders_dict, conversions: int, trader_data: str)`.
- Include `bid(self)` returning int.
- Use `from datamodel import Order, TradingState` and `jsonpickle` if you persist state.
- Do not require environment variables PROSPERITY4BT_ROUND or PROSPERITY4BT_DAY to exist.
- Keep changes minimal but purposeful: tune constants, spreads, inventory skew, or fair value logic.
"""


def _load_prompt_files() -> tuple[str, str]:
    prog_path = ROOT / "program.md"
    flow_path = ROOT / "AGENT_FLOW.md"
    program = prog_path.read_text(encoding="utf-8") if prog_path.exists() else ""
    flow = flow_path.read_text(encoding="utf-8") if flow_path.exists() else ""
    return program, flow


def _latest_report_excerpt(max_chars: int = 8000) -> str:
    if not RUNS.is_dir():
        return ""
    files = sorted(RUNS.glob("*_experiment.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        return ""
    text = files[0].read_text(encoding="utf-8")
    return text[:max_chars] if len(text) > max_chars else text


def _extract_python(text: str) -> str | None:
    m = re.search(r"```(?:python)?\s*\n(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if not m:
        return None
    return m.group(1).strip()


def _validate_python(code: str) -> bool:
    try:
        ast.parse(code)
    except SyntaxError:
        return False
    if "class Trader" not in code:
        return False
    if "def run" not in code:
        return False
    return True


def _run_agent_cycle(
    round_n: int,
    *,
    match_trades: str,
    no_auto_data: bool = False,
    original_timestamps: bool = False,
) -> int:
    cmd = [
        "uv",
        "run",
        "python",
        "scripts/agent_cycle.py",
        "--round",
        str(round_n),
        "--match-trades",
        match_trades,
    ]
    if no_auto_data:
        cmd.append("--no-auto-data")
    if original_timestamps:
        cmd.append("--original-timestamps")
    return subprocess.call(cmd, cwd=ROOT)


def _latest_profit() -> int | None:
    if not RUNS.is_dir():
        return None
    files = sorted(RUNS.glob("*_experiment.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        return None
    raw = files[0].read_text(encoding="utf-8")
    m = re.search(r"^total_profit:\s*(\d+)\s*$", raw, re.MULTILINE)
    return int(m.group(1)) if m else None


def _save_state(
    best: int | None,
    iteration: int,
    *,
    match_trades: str,
) -> None:
    REPORTS.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(
        json.dumps(
            {
                "best_profit": best,
                "last_iteration": iteration,
                "match_trades": match_trades,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _load_state() -> tuple[int | None, int, str | None]:
    if not STATE_PATH.is_file():
        return None, 0, None
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        mt = data.get("match_trades")
        mt_s = str(mt) if mt is not None else None
        return data.get("best_profit"), int(data.get("last_iteration", 0)), mt_s
    except (OSError, json.JSONDecodeError, ValueError, TypeError):
        return None, 0, None


def _gemini_edit(algorithm_src: str, model: str) -> str:
    key = os.environ.get("GOOGLE_API_KEY")
    if not key:
        raise RuntimeError("GOOGLE_API_KEY missing in environment")

    program, flow = _load_prompt_files()
    report_ex = _latest_report_excerpt()
    user = (
        "## program.md (context)\n"
        f"{program[:12000]}\n\n"
        "## AGENT_FLOW.md (excerpt)\n"
        f"{flow[:6000]}\n\n"
        "## Latest experiment report (excerpt)\n"
        f"{report_ex}\n\n"
        "## Current algorithm.py\n"
        f"```python\n{algorithm_src}\n```\n\n"
        "Improve total backtest profit under the SAME backtest settings as in the "
        "latest report (match_trades, data). Output valid, runnable Python only: "
        "the full new algorithm.py in one ```python``` block. No typos or "
        "undefined names—run() must not raise."
    )

    client = genai.Client(api_key=key)
    response = client.models.generate_content(model=model, contents=SYSTEM + "\n\n" + user)
    text = getattr(response, "text", None) or ""
    if not text.strip():
        raise RuntimeError("Empty model response")
    code = _extract_python(text)
    if not code:
        raise RuntimeError("No ```python``` block in model response")
    if not _validate_python(code):
        raise RuntimeError("Invalid Python or missing Trader class")
    return code


def main() -> int:
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description="Autoresearch-style loop (Gemini + backtest).")
    parser.add_argument("--iterations", type=int, default=10, help="Max attempts (default: 10)")
    parser.add_argument("--round", type=int, default=0, help="Backtest round (default: 0)")
    parser.add_argument(
        "--model",
        default=None,
        help="Gemini model id (default: env GEMINI_MODEL or gemini-2.0-flash)",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=2.0,
        help="Seconds between iterations (rate limits / API courtesy)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not call Gemini; run one agent_cycle and exit",
    )
    parser.add_argument(
        "--no-baseline",
        action="store_true",
        help="Skip initial agent_cycle used to measure baseline profit (not recommended)",
    )
    parser.add_argument(
        "--match-trades",
        choices=("all", "worse", "none"),
        default="worse",
        help="Forward to agent_cycle / prosperity4btx (default: worse; must match stored best).",
    )
    parser.add_argument(
        "--no-auto-data",
        action="store_true",
        help="Forward --no-auto-data to agent_cycle.",
    )
    parser.add_argument(
        "--original-timestamps",
        action="store_true",
        help="Forward --original-timestamps to agent_cycle (may break .log on 0.0.2).",
    )
    parser.add_argument(
        "--reset-state",
        action="store_true",
        help="Delete reports/autoresearch_state.json before running (fresh best / baseline).",
    )
    args = parser.parse_args()

    if args.reset_state and STATE_PATH.is_file():
        STATE_PATH.unlink()
        print(f"Cleared {STATE_PATH.relative_to(ROOT)}")

    model = args.model or os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")

    if args.dry_run:
        code = _run_agent_cycle(
            args.round,
            match_trades=args.match_trades,
            no_auto_data=args.no_auto_data,
            original_timestamps=args.original_timestamps,
        )
        print(f"agent_cycle exit code: {code}")
        print(f"latest total_profit: {_latest_profit()}")
        return code

    algo_path = ROOT / "algorithm.py"
    if not algo_path.is_file():
        print("algorithm.py not found", file=sys.stderr)
        return 1

    if not BEST_COPY.is_file():
        shutil.copy2(algo_path, BEST_COPY)
        print(f"Saved baseline copy to {BEST_COPY.name}")

    best_profit, _, stored_mt = _load_state()
    if stored_mt is not None and stored_mt != args.match_trades:
        print(
            f"Ignoring stored best: state match_trades={stored_mt!r} "
            f"≠ this run {args.match_trades!r} (incomparable scores).",
            file=sys.stderr,
        )
        best_profit = None
    elif (
        stored_mt is None
        and STATE_PATH.is_file()
        and best_profit is not None
    ):
        print(
            "Ignoring stored best: autoresearch_state.json predates match_trades "
            "(scores may mix modes). Use --reset-state after changing backtest defaults.",
            file=sys.stderr,
        )
        best_profit = None

    cycle_kw = dict(
        match_trades=args.match_trades,
        no_auto_data=args.no_auto_data,
        original_timestamps=args.original_timestamps,
    )

    if best_profit is None and not args.no_baseline:
        print("Establishing baseline profit from current algorithm.py ...")
        _run_agent_cycle(args.round, **cycle_kw)
        best_profit = _latest_profit()
        print(f"Baseline total_profit: {best_profit}")
        shutil.copy2(algo_path, BEST_COPY)
        _save_state(best_profit, 0, match_trades=args.match_trades)

    for i in range(1, args.iterations + 1):
        print(f"\n=== iteration {i}/{args.iterations} ===")
        try:
            current = algo_path.read_text(encoding="utf-8")
            new_code = _gemini_edit(current, model=model)
        except Exception as e:
            print(f"Gemini step failed: {e}", file=sys.stderr)
            shutil.copy2(BEST_COPY, algo_path)
            _save_state(best_profit, i, match_trades=args.match_trades)
            time.sleep(args.sleep)
            continue

        algo_path.write_text(new_code, encoding="utf-8")

        code = _run_agent_cycle(args.round, **cycle_kw)
        if code != 0:
            print("agent_cycle failed; restoring best algorithm", file=sys.stderr)
            shutil.copy2(BEST_COPY, algo_path)
            _save_state(best_profit, i, match_trades=args.match_trades)
            time.sleep(args.sleep)
            continue

        profit = _latest_profit()
        print(f"total_profit this run: {profit}")

        if profit is None:
            print("Could not parse profit; restoring best", file=sys.stderr)
            shutil.copy2(BEST_COPY, algo_path)
        elif best_profit is None or profit > best_profit:
            best_profit = profit
            shutil.copy2(algo_path, BEST_COPY)
            print(f"new best: {best_profit}")
        else:
            print(f"not better than best {best_profit}; discarding")
            shutil.copy2(BEST_COPY, algo_path)

        _save_state(best_profit, i, match_trades=args.match_trades)
        time.sleep(args.sleep)

    print("\nDone. Best profit:", best_profit)
    print(f"Best-so-far code: {BEST_COPY}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
