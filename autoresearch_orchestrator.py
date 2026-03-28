"""
Two-tier Gemini loop: a capable model (Pro) plans every N platform-evaluation iterations; a fast
model (Flash) proposes code each step; after each wave of N iterations, Pro receives a detailed
summary of profits and can steer the next wave (written under reports/).

Requires GOOGLE_API_KEY in .env. Optional: GEMINI_MODEL_PRO, GEMINI_MODEL_FLASH.
Each iteration runs `scripts/agent_cycle.py` (live upload); there is no local `--round` or
`--match-trades` CLI (those flags are not supported).

Usage:
  uv run autoresearch_orchestrator.py --reset-state --iterations 15 --plan-every 5 --no-baseline
  uv run autoresearch_orchestrator.py --dry-run
"""

from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import dataclass
from typing import Any

import tyro
from dotenv import load_dotenv
from google import genai
from loguru import logger

import autoresearch as ar

ROOT = ar.ROOT
REPORTS = ROOT / "reports"
ORCH_STATE_PATH = REPORTS / "autoresearch_orchestrator_state.json"
ORCH_REVIEWS_PATH = REPORTS / "orchestrator_pro_wave_reviews.md"
BEST_COPY = ar.BEST_COPY

PLAN_SYSTEM = """You plan experiments for an IMC Prosperity 4 market-making Python algorithm.
Output ONLY a markdown numbered list of 3–7 concrete, testable ideas for the next wave of
platform evaluation iterations. One short sentence per item. No Python code, no preamble."""

REVIEW_SYSTEM = """You review a completed wave of algorithm experiments (JSON summaries).
Write under 400 words: what likely worked, what failed, and 3 clear priorities for the next
wave. Be specific to the numbers given."""


def _gemini_text(system: str, user: str, model: str) -> str:
    key = os.environ.get("GOOGLE_API_KEY")
    if not key:
        raise RuntimeError("GOOGLE_API_KEY missing in environment")
    client = genai.Client(api_key=key)
    response = client.models.generate_content(model=model, contents=system + "\n\n" + user)
    text = getattr(response, "text", None) or ""
    if not text.strip():
        raise RuntimeError("Empty model response")
    return text.strip()


def _pro_plan(model: str, algorithm_src: str) -> str:
    program, flow = ar._load_prompt_files()
    report_ex = ar._latest_report_excerpt()
    user = (
        "## program.md (excerpt)\n"
        f"{program[:10_000]}\n\n"
        "## AGENT_FLOW.md (excerpt)\n"
        f"{flow[:4000]}\n\n"
        "## Latest experiment report (excerpt)\n"
        f"{report_ex[:6000]}\n\n"
        "## Current algorithm.py\n"
        f"```python\n{algorithm_src}\n```\n\n"
        "Produce the numbered plan now."
    )
    return _gemini_text(PLAN_SYSTEM, user, model)


def _flash_edit_with_plan(
    model: str,
    algorithm_src: str,
    plan: str,
    wave_step: int,
    wave_len: int,
) -> str:
    program, flow = ar._load_prompt_files()
    report_ex = ar._latest_report_excerpt()
    user = (
        "## program.md (context)\n"
        f"{program[:12_000]}\n\n"
        "## AGENT_FLOW.md (excerpt)\n"
        f"{flow[:6000]}\n\n"
        "## Wave research plan (from Pro)\n"
        f"{plan}\n\n"
        "## Iteration focus\n"
        f"This is step {wave_step} of {wave_len} in the current wave. "
        "Implement the change that best matches this step: map the step index to the "
        "corresponding numbered item in the plan (wrap logically if there are fewer items). "
        "Stay consistent with earlier steps in the same wave when needed.\n\n"
        "## Latest experiment report (excerpt)\n"
        f"{report_ex}\n\n"
        "## Current algorithm.py\n"
        f"```python\n{algorithm_src}\n```\n\n"
        "Improve total platform profit under the SAME evaluation settings as in the latest report. "
        "Output valid, runnable Python only: the full new algorithm.py in one ```python``` block. "
        "No typos or undefined names—run() must not raise."
    )
    text = _gemini_text(ar.SYSTEM, user, model)
    code = ar._extract_python(text)
    if not code:
        raise RuntimeError("No ```python``` block in model response")
    if not ar._validate_python(code):
        raise RuntimeError("Invalid Python or missing Trader class")
    return code


def _pro_wave_review(model: str, wave_rows: list[dict[str, Any]]) -> str:
    user = "## Wave results (JSON)\n\n```json\n" + json.dumps(wave_rows, indent=2) + "\n```"
    return _gemini_text(REVIEW_SYSTEM, user, model)


def _save_orch_state(
    best: int | None,
    iteration: int,
    *,
    wave_plan: str,
) -> None:
    REPORTS.mkdir(parents=True, exist_ok=True)
    ORCH_STATE_PATH.write_text(
        json.dumps(
            {
                "best_profit": best,
                "last_iteration": iteration,
                "current_plan_excerpt": wave_plan[:2000],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _append_review_markdown(text: str, *, wave_index: int, iteration_end: int) -> None:
    REPORTS.mkdir(parents=True, exist_ok=True)
    header = f"\n\n---\n\n## Wave ending at iteration {iteration_end} (wave #{wave_index})\n\n"
    if ORCH_REVIEWS_PATH.is_file():
        ORCH_REVIEWS_PATH.write_text(
            ORCH_REVIEWS_PATH.read_text(encoding="utf-8") + header + text + "\n",
            encoding="utf-8",
        )
    else:
        ORCH_REVIEWS_PATH.write_text(
            "# Orchestrator: Pro reviews after each wave\n\n" + header + text + "\n",
            encoding="utf-8",
        )
    logger.info("Appended Pro wave review to {}", ORCH_REVIEWS_PATH.relative_to(ROOT))


@dataclass
class OrchestratorArgs:
    """Pro/Flash orchestrated autoresearch (plan every N iterations, Pro reviews each wave)."""

    iterations: int = 15
    """Total Gemini + platform evaluation iterations."""

    plan_every: int = 5
    """Start a new Pro research plan every this many iterations (wave length)."""

    model_pro: str | None = None
    """Gemini model for planning and wave review (default: GEMINI_MODEL_PRO or gemini-2.5-pro)."""

    model_flash: str | None = None
    """Gemini model for code edits (default: GEMINI_MODEL_FLASH or gemini-2.0-flash)."""

    sleep: float = 2.0
    """Pause between iterations (seconds)."""

    dry_run: bool = False
    """Run one agent_cycle only; no Gemini."""

    no_baseline: bool = False
    """Skip baseline agent_cycle (not recommended)."""

    reset_state: bool = False
    """Delete orchestrator state file before run."""


def main() -> int:
    load_dotenv(ROOT / ".env")
    args = tyro.cli(OrchestratorArgs)
    if args.plan_every < 1:
        logger.error("--plan-every must be >= 1")
        return 2

    model_pro = args.model_pro or os.environ.get("GEMINI_MODEL_PRO", "gemini-2.5-pro")
    model_flash = args.model_flash or os.environ.get("GEMINI_MODEL_FLASH", "gemini-2.0-flash")

    if args.reset_state and ORCH_STATE_PATH.is_file():
        ORCH_STATE_PATH.unlink()
        logger.info("Removed {}", ORCH_STATE_PATH.relative_to(ROOT))

    if args.dry_run:
        code = ar._run_agent_cycle()
        logger.info("agent_cycle exit code: {}", code)
        logger.info("latest total_profit: {}", ar._latest_profit())
        return code

    algo_path = ROOT / "algorithm.py"
    if not algo_path.is_file():
        logger.error("algorithm.py not found")
        return 1

    if not BEST_COPY.is_file():
        shutil.copy2(algo_path, BEST_COPY)
        logger.info("Saved baseline copy to {}", BEST_COPY.name)

    best_profit, _ = ar._load_state()

    if best_profit is None and not args.no_baseline:
        logger.info("Establishing baseline profit from current algorithm.py …")
        ar._run_agent_cycle()
        best_profit = ar._latest_profit()
        logger.info("Baseline total_profit: {}", best_profit)
        shutil.copy2(algo_path, BEST_COPY)
        ar._save_state(best_profit, 0)

    current_plan = ""
    wave_buffer: list[dict[str, Any]] = []
    wave_index = 0

    for i in range(1, args.iterations + 1):
        logger.info("=== iteration {}/{} ===", i, args.iterations)

        wave_step = (i - 1) % args.plan_every + 1
        if wave_step == 1:
            wave_index += 1
            wave_buffer = []
            try:
                current_plan = _pro_plan(model_pro, algo_path.read_text(encoding="utf-8"))
                logger.info("Pro plan (wave {}):\n{}", wave_index, current_plan)
            except Exception as e:
                logger.exception("Pro planning failed: {}", e)
                shutil.copy2(BEST_COPY, algo_path)
                ar._save_state(best_profit, i)
                _save_orch_state(best_profit, i, wave_plan="")
                time.sleep(args.sleep)
                continue

        try:
            current = algo_path.read_text(encoding="utf-8")
            new_code = _flash_edit_with_plan(
                model_flash,
                current,
                current_plan,
                wave_step,
                args.plan_every,
            )
        except Exception as e:
            logger.exception("Flash edit failed: {}", e)
            shutil.copy2(BEST_COPY, algo_path)
            ar._save_state(best_profit, i)
            _save_orch_state(best_profit, i, wave_plan=current_plan)
            time.sleep(args.sleep)
            continue

        algo_path.write_text(new_code, encoding="utf-8")

        code = ar._run_agent_cycle()
        if code != 0:
            logger.error("agent_cycle failed; restoring best algorithm")
            shutil.copy2(BEST_COPY, algo_path)
            ar._save_state(best_profit, i)
            _save_orch_state(best_profit, i, wave_plan=current_plan)
            time.sleep(args.sleep)
            continue

        profit = ar._latest_profit()
        logger.info("total_profit this run: {}", profit)

        wave_buffer.append(
            {
                "iteration": i,
                "wave_step": wave_step,
                "wave_index": wave_index,
                "total_profit": profit,
            }
        )

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

        ar._save_state(best_profit, i)
        _save_orch_state(best_profit, i, wave_plan=current_plan)

        if wave_step == args.plan_every and wave_buffer:
            try:
                review = _pro_wave_review(model_pro, wave_buffer)
                _append_review_markdown(review, wave_index=wave_index, iteration_end=i)
            except Exception as e:
                logger.exception("Pro wave review failed: {}", e)

        time.sleep(args.sleep)

    logger.info("Done. Best profit: {}", best_profit)
    logger.info("Best-so-far code: {}", BEST_COPY)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
