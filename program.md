# Prosperity 4 — instructions for the coding agent

This repo follows a small **autoresearch-style** loop: analyze sample data, edit the trader, evaluate on the **platform** (upload), compare results. Human-maintained context for the competition lives under `context/`.

## Files and roles

| File | Who edits | Purpose |
|------|-----------|---------|
| `data_analytics.py` | Agent or human | Offline stats from CSVs under `data/` (including `data/round0/*.csv`). Use insights to tune `algorithm.py`. |
| `algorithm.py` | Agent | **The only file intended for official submission.** Implements `Trader` with `run()` (and `bid()` if a round requires it). |
| `datamodel.py` | Human (rarely) | **Local shim** with `Order`, `OrderDepth`, `TradingState` so `algorithm.py` imports resolve offline. The official Prosperity environment injects its own `datamodel`; **do not rely on this file being present on the server.** |
| `program.md` | Human | This file: goals, metrics, guardrails for agents. |
| `AGENT_FLOW.md` | Human | **Agentic loop** (English): how agents read/write `reports/`, recommended **Gemini Pro**, commands. |
| `reports/` | Agents + human | **English** experiment reports (`runs/*.md`) + auto-built `INDEX.md`; shared memory between iterations. |
| `scripts/agent_cycle.py` | Human (rarely) | Runs `data_analytics` + `scripts/submit_live.py`, writes a new `reports/runs/*_experiment.md` and refreshes `reports/INDEX.md`. |
| `prepare.py` | Human (rarely) | **Fixed** sanity check — same role as autoresearch `prepare.py`; do not edit for normal strategy research. |
| `autoresearch.py` | Human (rarely) | **Optional overnight loop**: Gemini proposes a full `algorithm.py`, `agent_cycle` runs, keep if **total profit** improves; writes `algorithm_best.py` and `reports/autoresearch_state.json`. Requires `GOOGLE_API_KEY` in `.env`. |

## Agentic flow (multi-iteration)

1. Read `AGENT_FLOW.md` and the latest files in `reports/runs/` (see `reports/INDEX.md`).
2. Edit `algorithm.py` / `data_analytics.py` as needed.
3. Run `uv run python scripts/agent_cycle.py` to record metrics and create a report stub **in English** (fill *Insights* / *Hypotheses* / *Algorithm changes*). Each run uploads via `submit_live` and embeds **Parsed platform metrics** and raw API result text in the report.
4. Compare `total_profit` in the new report’s YAML front matter to the previous run. **Caveat:** if the platform’s simulation round or scenario changes, profit can move even when `algorithm.py` is unchanged—treat large swings as possibly environmental, not only strategy regressions.
5. **Optional:** after submitting on [prosperity.imc.com/game](https://prosperity.imc.com/game), save the JSON with `activitiesLog` to `reports/official/` and run `uv run python scripts/analyze_official_log.py <file.json>`. See `reports/official/README.md`.

For external LLM sessions, prefer **Google Gemini** in **Pro** (or the strongest reasoning tier available) when synthesising CSV + platform results and proposing the next change set.

**Fully automated loop (closest to autoresearch overnight):** `uv run autoresearch.py --iterations 10` with `GOOGLE_API_KEY` set. See `README.md` and `AGENT_FLOW.md`. Use `--dry-run` to test without calling the API.

## Success metric

After changing the strategy, run `agent_cycle` and compare **total profit** from the platform (graph endpoint and/or downloaded log). Prefer consistent improvement when comparing consecutive iterations.

Commands:

```bash
uv run python scripts/agent_cycle.py
uv run python scripts/submit_live.py
```

## Guardrails

1. **Submission code** in `algorithm.py` must not **require** environment variables `PROSPERITY4BT_ROUND` or `PROSPERITY4BT_DAY`.

2. Keep `traderData` serialization under the platform size limit (see `context/Writing an Algorithm in Python.md`).

3. `data_analytics.py` is for analysis only; it must not become a hard runtime dependency of `algorithm.py` unless the competition explicitly allows extra shipped files (default: submit **only** `algorithm.py`).

## Suggested iteration prompt

Read `program.md`, run `uv run data_analytics.py` if CSV samples changed, propose changes to `algorithm.py`, then run `uv run python scripts/agent_cycle.py` and summarize profit vs. the previous run.
