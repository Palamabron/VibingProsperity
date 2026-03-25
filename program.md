# Prosperity 4 — instructions for the coding agent

This repo follows a small **autoresearch-style** loop: analyze sample data, edit the trader, backtest, compare results. Human-maintained context for the competition lives under `context/`.

## Files and roles

| File | Who edits | Purpose |
|------|-----------|---------|
| `data_analytics.py` | Agent or human | Offline stats from `data/*.csv` (spreads, mid price movement, trade counts). Use insights to tune constants and logic in `algorithm.py`. |
| `algorithm.py` | Agent | **The only file intended for official submission.** Implements `Trader` with `run()` (and `bid()` if a round requires it). |
| `datamodel.py` | Human (rarely) | **Local shim** re-exporting types from `prosperity4bt` so backtests can import `datamodel`. The official Prosperity environment injects its own `datamodel`; **do not rely on this file being present on the server.** |
| `backtest.py` | Human (rarely) | Wrapper around the `prosperity4btx` CLI for consistent defaults. |
| `program.md` | Human | This file: goals, metrics, guardrails for agents. |
| `AGENT_FLOW.md` | Human | **Agentic loop** (English): how agents read/write `reports/`, recommended **Gemini Pro**, commands. |
| `reports/` | Agents + human | **English** experiment reports (`runs/*.md`) + auto-built `INDEX.md`; shared memory between iterations. |
| `scripts/agent_cycle.py` | Human (rarely) | Runs `data_analytics` + `backtest`, writes a new `reports/runs/*_experiment.md` and refreshes `reports/INDEX.md`. |
| `prepare.py` | Human (rarely) | **Fixed** sanity check — same role as autoresearch `prepare.py`; do not edit for normal strategy research. |
| `autoresearch.py` | Human (rarely) | **Optional overnight loop**: Gemini proposes a full `algorithm.py`, backtest runs, keep if **total profit** improves; writes `algorithm_best.py` and `reports/autoresearch_state.json`. Requires `GOOGLE_API_KEY` in `.env`. |

## Agentic flow (multi-iteration)

1. Read `AGENT_FLOW.md` and the latest files in `reports/runs/` (see `reports/INDEX.md`).
2. Edit `algorithm.py` / `data_analytics.py` as needed.
3. Run `uv run python scripts/agent_cycle.py` to record metrics and create a report stub **in English** (fill *Insights* / *Hypotheses* / *Algorithm changes*).
4. Compare `total_profit` in the new report’s YAML front matter to the previous run (same `--round`).

For external LLM sessions, prefer **Google Gemini** in **Pro** (or the strongest reasoning tier available) when synthesising CSV + backtest results and proposing the next change set.

**Fully automated loop (closest to autoresearch overnight):** `uv run autoresearch.py --iterations 10 --round 0` with `GOOGLE_API_KEY` set. See `README.md` and `AGENT_FLOW.md`. Use `--dry-run` to test without calling the API.

## Success metric

After changing the strategy, run a backtest and compare **total profit** (and per-product breakdown) printed at the end of the run. Prefer consistent improvement across days when multiple days exist; use `--merge-pnl` when comparing merged PnL across days.

Commands:

```bash
uv run backtest.py --round 0 --no-progress
uv run prosperity4btx algorithm.py 0 --merge-pnl --no-progress
```

Logs can be saved with `--out path/to.log` (see `prosperity4btx --help`).

## Guardrails

1. **Submission code** in `algorithm.py` must not **require** environment variables `PROSPERITY4BT_ROUND` or `PROSPERITY4BT_DAY`. Those are set only by the community backtester, not by the official Prosperity submission environment.

2. Keep `traderData` serialization under the platform size limit (see `context/Writing an Algorithm in Python.md`).

3. `data_analytics.py` is for analysis only; it must not become a hard runtime dependency of `algorithm.py` unless the competition explicitly allows extra shipped files (default: submit **only** `algorithm.py`).

## Suggested iteration prompt

Read `program.md`, run `uv run data_analytics.py` if CSV samples changed, propose changes to `algorithm.py`, then run `uv run backtest.py` and summarize profit vs. the previous run.
