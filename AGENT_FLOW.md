# Agentic research loop (IMC Prosperity 4)

This document describes how **AI agents** (recommended: **Google Gemini** in *Pro* or equivalent reasoning mode when available) should collaborate with humans to iterate on `data_analytics.py` and `algorithm.py`, validate with the [community backtester](https://github.com/Xeeshan85/imc-prosperity-4-backtester), and leave **English** paper trails under `reports/`.

## Roles

| Artifact | Responsibility |
|----------|------------------|
| `program.md` | Human-edited goals, guardrails, metrics. Agents must read this first. |
| `context/` | Competition documentation; agents use it for API semantics and limits. |
| `reports/runs/*.md` | **Shared memory**: metrics + agent-written insights between iterations. |
| `algorithm.py` | Primary implementation target for trading logic (official submission file). |
| `data_analytics.py` | Offline CSV analysis; extend when new `data/*.csv` patterns appear. |

## One iteration (checklist)

1. **Read** `program.md`, skim `reports/INDEX.md`, open **1–2 latest** files in `reports/runs/`.
2. **Analyse** (if CSVs changed or strategy needs stats): run `uv run data_analytics.py` and interpret spreads, mid volatility, trade counts.
3. **Edit** `algorithm.py` (and optionally `data_analytics.py`) with a **small, reversible** change set.
4. **Measure**: run `uv run scripts/agent_cycle.py` — this captures analytics + backtest and creates a new report stub under `reports/runs/`.
5. **Write** in that report (English): *Insights*, *Hypotheses for next iteration*, *Algorithm changes (summary)*.
6. **Compare** total profit to the previous run on the **same** round/day configuration. Regressions should be noted explicitly in the report.

## Suggested model usage (Gemini)

- Use **Gemini Pro** (or the strongest available Gemini tier) for: synthesising CSV stats, proposing parameter sweeps, and explaining drawdowns or per-product behaviour.
- Paste **only** what is needed: relevant sections from the latest `reports/runs/*.md`, the current `algorithm.py` constants block, and the new backtest summary from the report body.
- Do **not** rely on `PROSPERITY4BT_ROUND` / `PROSPERITY4BT_DAY` in submitted code (see `program.md`).

## Commands reference

```bash
uv sync
uv run scripts/agent_cycle.py              # analytics + backtest + new report under reports/runs/
uv run scripts/agent_cycle.py --round 0    # explicit round (passed to backtest)
```

Manual fallback if the script is unavailable:

```bash
uv run data_analytics.py
uv run backtest.py --merge-pnl --no-progress
```

## Success metric

Primary: **total profit** from the backtest summary for the chosen round/days. Secondary: stability across days and sensible per-product PnL (see raw backtest block in each report).

## API keys (optional)

- **`autoresearch.py`** (overnight Gemini loop) **requires** **`GOOGLE_API_KEY`** in `.env`. Optional: **`GEMINI_MODEL`** (default `gemini-2.0-flash`; set a Pro model if your quota allows).
- Put secrets only in **`.env`** (gitignored). Copy from `.env.example`.
- See [Google AI Studio](https://aistudio.google.com/apikey) for API keys.
- For **Cursor**’s built-in AI, configure keys in **Cursor Settings**, not in tracked files.

## Overnight loop (`autoresearch.py`)

Same spirit as autoresearch: repeated experiments with a **keep-if-better** rule on the metric (here: **total profit**).

```bash
uv run autoresearch.py --iterations 10 --round 0
uv run autoresearch.py --dry-run   # no Gemini; one agent_cycle only
```

Artifacts: **`algorithm_best.py`** (best candidate), **`reports/autoresearch_state.json`** (best profit + iteration).
