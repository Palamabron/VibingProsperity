from __future__ import annotations

import json
import os
import re
import shutil
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import tyro
from dotenv import load_dotenv
from google import genai
from google.genai import types
from loguru import logger

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

sys.path.insert(0, str(ROOT / "scripts"))
from report_utils import format_front_matter_yaml, rebuild_experiment_index  # noqa: E402
from submit_live import submit_and_wait  # noqa: E402

ALGO_PATH = ROOT / "algorithm.py"
BACKUP_PATH = ROOT / "algorithm_best.py"
STATE_PATH = ROOT / "reports" / "autoresearch_live_state.json"
REPORTS_DIR = ROOT / "reports"
RUNS_DIR = REPORTS_DIR / "runs"
INDEX_PATH = REPORTS_DIR / "INDEX.md"

RUNS_DIR.mkdir(parents=True, exist_ok=True)

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "models/gemini-2.5-pro")
LOG_CHARS_FOR_GEMINI = 8000


def _load_state() -> dict[str, Any]:
    if STATE_PATH.exists():
        try:
            return cast(dict[str, Any], json.loads(STATE_PATH.read_text()))
        except Exception:
            pass
    return {"best_profit": None, "iteration": 0}


def _save_state(state: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2))


def _gemini_edit(algo_code: str, log_text: str | None, profit: int | None, iteration: int) -> str:
    client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY") or os.environ["GOOGLE_API_KEY"])

    log_snippet = ""
    if log_text:
        trimmed = log_text[:LOG_CHARS_FOR_GEMINI]
        if len(log_text) > LOG_CHARS_FOR_GEMINI:
            trimmed += f"\n... [log truncated, total {len(log_text)} chars]"
        log_snippet = f"\n\n## Live simulation log\n\n```\n{trimmed}\n```"

    profit_str = f"{profit:+,}" if profit is not None else "unknown"

    prompt = (
        "You are an expert algorithmic trader improving a market-making bot for IMC Prosperity 4.\n"
        f"\n## Current algorithm (iteration {iteration})\n"
        "```python\n"
        f"{algo_code}\n"
        "```\n"
        "\n## Live simulation result\n"
        f"Total PnL: {profit_str} SeaShells{log_snippet}\n"
        "\n## Task\n"
        "\nAnalyze the log carefully. Identify what is working and what is not.\n"
        "Then produce an improved version of the algorithm.\n"
        "\nRules:\n"
        "- Output ONLY the complete improved Python file, no explanation, no markdown fences\n"
        "- Keep the Trader class and run() method signature unchanged\n"
        "- Do not add external dependencies\n"
        "- Make targeted, specific improvements based on the log\n"
        "- If the log shows inventory buildup, fix position management\n"
        "- If spread is too wide/narrow, adjust quoting logic\n"
        "- If a product is losing money, reduce or eliminate its activity\n"
        "\nOutput the complete Python file now:"
    )

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.7,
            max_output_tokens=8192,
        ),
    )

    text: str | None = response.text
    if text is None:
        try:
            cands = response.candidates
            if not cands:
                raise RuntimeError(f"Gemini returned no text. Response: {response}")
            content = cands[0].content
            if content is None or not content.parts:
                raise RuntimeError(f"Gemini returned no text. Response: {response}")
            text = content.parts[0].text
        except RuntimeError:
            raise
        except Exception:
            raise RuntimeError(f"Gemini returned no text. Response: {response}") from None
    if text is None:
        raise RuntimeError(f"Gemini returned no text. Response: {response}")

    code = text.strip()
    code = re.sub(r"^```python\s*", "", code)
    code = re.sub(r"^```\s*", "", code)
    code = re.sub(r"\s*```$", "", code)
    return code.strip()


def _write_report(ts: str, result: dict, iteration: int, improved: bool) -> Path:
    profit = result.get("total_profit")
    sub_id = result.get("submission_id", "n/a")
    status = result.get("status", "unknown")
    per_prod = result.get("per_product", {})
    log_path = result.get("log_path")
    error = result.get("error")

    fm: dict[str, Any] = {
        "experiment_id": ts,
        "source": "live",
        "submission_id": str(sub_id),
        "status": str(status),
        "timestamp": ts,
        "round": None,
        "iteration": iteration,
        "improved": improved,
    }
    if profit is not None:
        fm["total_profit"] = int(profit)
    else:
        fm["total_profit"] = None

    lines = [
        format_front_matter_yaml(fm).rstrip(),
        "",
        f"# Live Experiment — iteration {iteration} — {ts}",
        "",
        f"**Status:** {status}  ",
        f"**Improved:** {'yes' if improved else 'no'}  ",
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

    path = RUNS_DIR / f"{ts}_experiment.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def run(iterations: int | None = None, dry_run: bool = False) -> None:
    state = _load_state()
    logger.info("{}", "=" * 60)
    logger.info(
        "AUTORESEARCH LIVE — starting at iteration {} | best_profit so far: {}",
        state["iteration"],
        state["best_profit"],
    )
    logger.info("{}", "=" * 60)

    i = 0
    while iterations is None or i < iterations:
        state["iteration"] += 1
        iteration = state["iteration"]
        ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")

        logger.info("{} Iteration {} — {}", "─" * 60, iteration, ts)

        if dry_run:
            logger.info("[autoresearch_live] dry-run: skipping submission")
            result = {
                "status": "success",
                "total_profit": state["best_profit"],
                "per_product": {},
                "log_text": None,
                "log_path": None,
                "submission_id": "dry-run",
                "timestamp": ts,
                "error": None,
            }
        else:
            result = submit_and_wait(ALGO_PATH)

        profit = result.get("total_profit")
        log_text = result.get("log_text")

        improved = False
        if result["status"] == "success" and profit is not None:
            if state["best_profit"] is None or profit > state["best_profit"]:
                improved = True
                state["best_profit"] = profit
                shutil.copy2(ALGO_PATH, BACKUP_PATH)
                logger.info(
                    "[autoresearch_live] NEW BEST: {:+,} — saved to algorithm_best.py",
                    profit,
                )
            else:
                best = state["best_profit"]
                logger.info(
                    "[autoresearch_live] profit {:+,} <= best {:+,} — reverting",
                    profit,
                    best,
                )
                if BACKUP_PATH.exists():
                    shutil.copy2(BACKUP_PATH, ALGO_PATH)
        elif result["status"] != "success":
            logger.warning(
                "[autoresearch_live] submission failed: {} — reverting",
                result.get("error"),
            )
            if BACKUP_PATH.exists():
                shutil.copy2(BACKUP_PATH, ALGO_PATH)

        report = _write_report(ts, result, iteration, improved)
        rebuild_experiment_index(runs_dir=RUNS_DIR, index_path=INDEX_PATH, reports_root=REPORTS_DIR)
        logger.info("[autoresearch_live] report → {}", report.relative_to(ROOT))

        _save_state(state)

        algo_code = ALGO_PATH.read_text(encoding="utf-8")
        logger.info("[autoresearch_live] asking Gemini to improve algorithm …")
        try:
            new_code = _gemini_edit(algo_code, log_text, profit, iteration)
            ALGO_PATH.write_text(new_code, encoding="utf-8")
            logger.info("[autoresearch_live] algorithm.py updated ({} chars)", len(new_code))
        except Exception as exc:
            logger.exception("[autoresearch_live] Gemini error: {}", exc)
            logger.info("[autoresearch_live] keeping current algorithm")

        i += 1

    logger.info("{}", "=" * 60)
    logger.info("DONE — best profit: {}", state["best_profit"])
    logger.info("{}", "=" * 60)


@dataclass
class AutoresearchLiveArgs:
    """Agentic live trading loop for IMC Prosperity 4."""

    iterations: int | None = None
    """Stop after this many iterations (default: run until interrupted)."""

    dry_run: bool = False
    """Skip live submission (mock result)."""

    reset_state: bool = False
    """Delete saved state before starting."""


if __name__ == "__main__":
    args = tyro.cli(AutoresearchLiveArgs)
    if args.reset_state:
        STATE_PATH.unlink(missing_ok=True)
        logger.info("State reset.")

    run(iterations=args.iterations, dry_run=args.dry_run)
