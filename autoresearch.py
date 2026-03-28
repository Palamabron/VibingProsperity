"""
Overnight-style loop: Gemini proposes a full `algorithm.py`, live platform evaluation runs,
keep-if-better.

The metric is **total_profit** from `scripts/agent_cycle.py` (upload via `scripts/submit_live.py`).

Requires `GOOGLE_API_KEY` in `.env` (see `.env.example`).
Optional: `GEMINI_MODEL` (default: gemini-2.0-flash).

Usage:
  uv run autoresearch.py --iterations 5
  uv run autoresearch.py --dry-run    # no API; run one agent_cycle only
  uv run autoresearch.py --reset-state # drop saved best
"""

from __future__ import annotations

import ast
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import tyro
from dotenv import load_dotenv
from google import genai
from loguru import logger

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "scripts"))

from report_utils import latest_experiment_total_profit  # noqa: E402

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


def _run_agent_cycle() -> int:
    cmd = [
        "uv",
        "run",
        "python",
        "scripts/agent_cycle.py",
    ]
    timeout = _agent_cycle_script_timeout()
    try:
        r = subprocess.run(cmd, cwd=ROOT, timeout=timeout)
        return r.returncode
    except subprocess.TimeoutExpired:
        logger.error(
            "agent_cycle exceeded timeout ({}s); set AGENT_CYCLE_SCRIPT_TIMEOUT or increase it.",
            timeout,
        )
        return 124


def _agent_cycle_script_timeout() -> float | None:
    raw = os.environ.get("AGENT_CYCLE_SCRIPT_TIMEOUT", "7200").strip()
    if raw == "" or raw.lower() in ("none", "inf"):
        return None
    return float(raw)


def _latest_profit() -> int | None:
    if not RUNS.is_dir():
        return None
    profit, _ = latest_experiment_total_profit(RUNS)
    return profit


def _save_state(
    best: int | None,
    iteration: int,
) -> None:
    REPORTS.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(
        json.dumps(
            {
                "best_profit": best,
                "last_iteration": iteration,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _load_state() -> tuple[int | None, int]:
    if not STATE_PATH.is_file():
        return None, 0
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        return data.get("best_profit"), int(data.get("last_iteration", 0))
    except (OSError, json.JSONDecodeError, ValueError, TypeError):
        return None, 0


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
        "Improve total platform profit under the SAME evaluation as in the "
        "latest report. Output valid, runnable Python only: "
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


@dataclass
class AutoresearchArgs:
    """Autoresearch-style loop (Gemini + live platform evaluation)."""

    iterations: int = 10
    """Max attempts (default: 10)."""

    model: str | None = None
    """Gemini model id (default: env GEMINI_MODEL or gemini-2.0-flash)."""

    sleep: float = 2.0
    """Seconds between iterations (rate limits / API courtesy)."""

    dry_run: bool = False
    """Do not call Gemini; run one agent_cycle and exit."""

    no_baseline: bool = False
    """Skip initial agent_cycle used to measure baseline profit (not recommended)."""

    reset_state: bool = False
    """Delete reports/autoresearch_state.json before running (fresh best / baseline)."""


def main() -> int:
    load_dotenv(ROOT / ".env")
    args = tyro.cli(AutoresearchArgs)

    if args.reset_state and STATE_PATH.is_file():
        STATE_PATH.unlink()
        logger.info("Cleared {}", STATE_PATH.relative_to(ROOT))

    model = args.model or os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")

    if args.dry_run:
        code = _run_agent_cycle()
        logger.info("agent_cycle exit code: {}", code)
        logger.info("latest total_profit: {}", _latest_profit())
        return code

    algo_path = ROOT / "algorithm.py"
    if not algo_path.is_file():
        logger.error("algorithm.py not found")
        return 1

    if not BEST_COPY.is_file():
        shutil.copy2(algo_path, BEST_COPY)
        logger.info("Saved baseline copy to {}", BEST_COPY.name)

    best_profit, _ = _load_state()

    if best_profit is None and not args.no_baseline:
        logger.info("Establishing baseline profit from current algorithm.py …")
        _run_agent_cycle()
        best_profit = _latest_profit()
        logger.info("Baseline total_profit: {}", best_profit)
        shutil.copy2(algo_path, BEST_COPY)
        _save_state(best_profit, 0)

    for i in range(1, args.iterations + 1):
        logger.info("=== iteration {}/{} ===", i, args.iterations)
        try:
            current = algo_path.read_text(encoding="utf-8")
            new_code = _gemini_edit(current, model=model)
        except Exception:
            logger.exception("Gemini step failed")
            shutil.copy2(BEST_COPY, algo_path)
            _save_state(best_profit, i)
            time.sleep(args.sleep)
            continue

        algo_path.write_text(new_code, encoding="utf-8")

        code = _run_agent_cycle()
        if code != 0:
            logger.error("agent_cycle failed; restoring best algorithm")
            shutil.copy2(BEST_COPY, algo_path)
            _save_state(best_profit, i)
            time.sleep(args.sleep)
            continue

        profit = _latest_profit()
        logger.info("total_profit this run: {}", profit)

        if profit is None:
            logger.error("Could not parse profit; restoring best")
            shutil.copy2(BEST_COPY, algo_path)
        elif best_profit is None or profit > best_profit:
            best_profit = profit
            shutil.copy2(algo_path, BEST_COPY)
            logger.info("new best: {}", best_profit)
        else:
            logger.info("not better than best {}; discarding", best_profit)
            shutil.copy2(BEST_COPY, algo_path)

        _save_state(best_profit, i)
        time.sleep(args.sleep)

    logger.info("Done. Best profit: {}", best_profit)
    logger.info("Best-so-far code: {}", BEST_COPY)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
