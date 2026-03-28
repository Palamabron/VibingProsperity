from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

sys.path.insert(0, str(ROOT / "scripts"))
from submit_live import submit_and_wait  # noqa: E402

ALGO_PATH   = ROOT / "algorithm.py"
BACKUP_PATH = ROOT / "algorithm_best.py"
STATE_PATH  = ROOT / "reports" / "autoresearch_live_state.json"
RUNS_DIR    = ROOT / "reports" / "runs"
INDEX_PATH  = ROOT / "reports" / "INDEX.md"

RUNS_DIR.mkdir(parents=True, exist_ok=True)

GEMINI_MODEL         = os.getenv("GEMINI_MODEL", "models/gemini-2.5-pro")
LOG_CHARS_FOR_GEMINI = 8000


def _load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text())
        except Exception:
            pass
    return {"best_profit": None, "iteration": 0}


def _save_state(state: dict) -> None:
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

    prompt = f"""You are an expert algorithmic trader improving a market-making bot for IMC Prosperity 4.

## Current algorithm (iteration {iteration})

```python
{algo_code}
```

## Live simulation result
Total PnL: {profit_str} SeaShells{log_snippet}

## Task

Analyze the log carefully. Identify what is working and what is not.
Then produce an improved version of the algorithm.

Rules:
- Output ONLY the complete improved Python file, no explanation, no markdown fences
- Keep the Trader class and run() method signature unchanged
- Do not add external dependencies
- Make targeted, specific improvements based on the log
- If the log shows inventory buildup, fix position management
- If spread is too wide/narrow, adjust quoting logic
- If a product is losing money, reduce or eliminate its activity

Output the complete Python file now:"""

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.7,
            max_output_tokens=8192,
        ),
    )

    text = response.text
    if text is None:
        try:
            text = response.candidates[0].content.parts[0].text
        except Exception:
            raise RuntimeError(f"Gemini returned no text. Response: {response}")

    code = text.strip()
    code = re.sub(r"^```python\s*", "", code)
    code = re.sub(r"^```\s*", "", code)
    code = re.sub(r"\s*```$", "", code)
    return code.strip()


def _write_report(ts: str, result: dict, iteration: int, improved: bool) -> Path:
    profit   = result.get("total_profit")
    sub_id   = result.get("submission_id", "n/a")
    status   = result.get("status", "unknown")
    per_prod = result.get("per_product", {})
    log_path = result.get("log_path")
    error    = result.get("error")

    header = (
        f"total_profit: {profit}\n"
        f"submission_id: {sub_id}\n"
        f"status: {status}\n"
        f"iteration: {iteration}\n"
        f"improved: {improved}\n"
        f"timestamp: {ts}\n"
    )

    lines = [
        f"# Live Experiment — iteration {iteration} — {ts}",
        "",
        "```",
        header.strip(),
        "```",
        "",
        f"**Status:** {status}  ",
        f"**Improved:** {'✅ YES' if improved else '❌ no'}  ",
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

    path = RUNS_DIR / f"{ts}_experiment.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def _update_index(report: Path, profit: int | None, ts: str, iteration: int, improved: bool) -> None:
    profit_str   = f"{profit:+,}" if profit is not None else "N/A"
    improved_str = "✅" if improved else "—"
    entry        = f"| [{ts}]({report.relative_to(ROOT)}) | {profit_str} | {iteration} | {improved_str} | live |\n"
    if INDEX_PATH.exists():
        existing = INDEX_PATH.read_text(encoding="utf-8")
    else:
        existing = (
            "# Experiment Index\n\n"
            "| Run | Profit (SeaShells) | Iteration | Improved | Source |\n"
            "|-----|-------------------|-----------|----------|--------|\n"
        )
    lines  = existing.splitlines(keepends=True)
    insert = next((i for i, l in enumerate(lines) if l.startswith("|---")), len(lines)) + 1
    lines.insert(insert, entry)
    INDEX_PATH.write_text("".join(lines), encoding="utf-8")


def run(iterations: int | None = None, dry_run: bool = False) -> None:
    state = _load_state()
    print(f"\n{'='*60}")
    print(f"  AUTORESEARCH LIVE — starting at iteration {state['iteration']}")
    print(f"  best_profit so far: {state['best_profit']}")
    print(f"{'='*60}\n")

    i = 0
    while iterations is None or i < iterations:
        state["iteration"] += 1
        iteration = state["iteration"]
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

        print(f"\n{'─'*60}")
        print(f"  Iteration {iteration}  —  {ts}")
        print(f"{'─'*60}")

        if dry_run:
            print("[autoresearch_live] dry-run: skipping submission")
            result = {
                "status": "success", "total_profit": state["best_profit"],
                "per_product": {}, "log_text": None, "log_path": None,
                "submission_id": "dry-run", "timestamp": ts, "error": None,
            }
        else:
            result = submit_and_wait(ALGO_PATH)

        profit   = result.get("total_profit")
        log_text = result.get("log_text")

        improved = False
        if result["status"] == "success" and profit is not None:
            if state["best_profit"] is None or profit > state["best_profit"]:
                improved = True
                state["best_profit"] = profit
                shutil.copy2(ALGO_PATH, BACKUP_PATH)
                print(f"[autoresearch_live] ✅ NEW BEST: {profit:+,} → saved to algorithm_best.py")
            else:
                print(f"[autoresearch_live] profit {profit:+,} ≤ best {state['best_profit']:+,} — reverting")
                if BACKUP_PATH.exists():
                    shutil.copy2(BACKUP_PATH, ALGO_PATH)
        elif result["status"] != "success":
            print(f"[autoresearch_live] submission failed: {result.get('error')} — reverting")
            if BACKUP_PATH.exists():
                shutil.copy2(BACKUP_PATH, ALGO_PATH)

        report = _write_report(ts, result, iteration, improved)
        _update_index(report, profit, ts, iteration, improved)
        print(f"[autoresearch_live] report → {report.relative_to(ROOT)}")

        _save_state(state)

        algo_code = ALGO_PATH.read_text(encoding="utf-8")
        print("[autoresearch_live] asking Gemini to improve algorithm …")
        try:
            new_code = _gemini_edit(algo_code, log_text, profit, iteration)
            ALGO_PATH.write_text(new_code, encoding="utf-8")
            print(f"[autoresearch_live] algorithm.py updated ({len(new_code)} chars)")
        except Exception as exc:
            print(f"[autoresearch_live] Gemini error: {exc}", file=sys.stderr)
            print("[autoresearch_live] keeping current algorithm")

        i += 1

    print(f"\n{'='*60}")
    print(f"  DONE — best profit: {state['best_profit']}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Agentic live trading loop for IMC Prosperity 4")
    parser.add_argument("--iterations",  type=int, default=None)
    parser.add_argument("--dry-run",     action="store_true")
    parser.add_argument("--reset-state", action="store_true")
    args = parser.parse_args()

    if args.reset_state:
        STATE_PATH.unlink(missing_ok=True)
        print("State reset.")

    run(iterations=args.iterations, dry_run=args.dry_run)
