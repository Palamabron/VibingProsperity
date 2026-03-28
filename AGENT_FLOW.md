# Agentic research loop (IMC Prosperity 4)

This document describes how **AI agents** (recommended: **Google Gemini** in *Pro* or equivalent reasoning mode when available) should collaborate with humans to iterate on `data_analytics.py` and `algorithm.py`, validate by **uploading** to the Prosperity platform (`scripts/submit_live.py`), and leave **English** paper trails under `reports/`.

## Roles

| Artifact | Responsibility |
|----------|----------------|
| `program.md` | Human-edited goals, guardrails, metrics. Agents must read this first. |
| `context/` | Competition documentation; agents use it for API semantics and limits. |
| `reports/runs/*.md` | **Shared memory**: metrics + agent-written insights between iterations. |
| `algorithm.py` | Primary implementation target for trading logic (official submission file). |
| `data_analytics.py` | Offline CSV analysis; extend when new samples land under `data/` (e.g. `data/roundN/`). |

## One iteration (checklist)

1. **Read** `program.md`, skim `reports/INDEX.md`, open **1–2 latest** files in `reports/runs/`.
2. **Analyse** (if CSVs changed or strategy needs stats): run `uv run data_analytics.py` and interpret spreads, mid volatility, trade counts.
3. **Edit** `algorithm.py` (and optionally `data_analytics.py`) with a **small, reversible** change set.
4. **Measure**: run `uv run python scripts/agent_cycle.py` — this captures analytics + **live platform evaluation** (upload + poll), writes **Parsed platform metrics**, saves optional logs under `reports/submissions_live/`, and creates a new report under `reports/runs/`.
5. **Optional (official ground truth):** save JSON with `activitiesLog` into `reports/official/` and run `uv run python scripts/analyze_official_log.py <file.json>`. See `reports/official/README.md`.
6. **Write** in that report (English): *Insights*, *Hypotheses for next iteration*, *Algorithm changes (summary)*.
7. **Compare** `total_profit` in report YAML to the previous run. Regressions should be noted explicitly in the report.

## Suggested model usage (Gemini)

- Use **Gemini Pro** (or the strongest available Gemini tier) for: synthesising CSV stats, proposing parameter sweeps, and explaining drawdowns or per-product behaviour.
- Paste **only** what is needed: relevant sections from the latest `reports/runs/*.md`, the current `algorithm.py` constants block, and the new platform summary from the report body.
- Do **not** rely on `PROSPERITY4BT_ROUND` / `PROSPERITY4BT_DAY` in submitted code (see `program.md`).

## Commands reference

```bash
uv sync
uv run python scripts/agent_cycle.py
uv run python scripts/agent_cycle.py --algorithm algorithm.py

# Upload + poll only (no analytics, no experiment report):
uv run python scripts/submit_live.py
uv run python scripts/submit_live.py path/to/algorithm.py

# Analyze a saved official submission JSON (manual export from browser):
uv run python scripts/analyze_official_log.py reports/official/submission.json -o reports/runs/foo_official.md
```

Manual fallback if you only want CSV stats:

```bash
uv run data_analytics.py
uv run python scripts/submit_live.py
```

## Success metric

Primary: **total profit** from the platform (graph / log). Secondary: per-product PnL when parsed from the zip log. Tertiary: **official** `activitiesLog` analysis when you save submission JSON locally (`scripts/analyze_official_log.py`).

## API keys (optional)

- **`autoresearch.py`** (overnight Gemini loop) **requires** **`GOOGLE_API_KEY`** in `.env`. Optional: **`GEMINI_MODEL`** (default `gemini-2.0-flash`; set a Pro model if your quota allows).
- **`scripts/agent_cycle.py`** / **`scripts/submit_live.py`** require **`PROSPERITY_ID_TOKEN`** (Bearer token from the game site). Use **`scripts/get_token.py`** to refresh. Put secrets only in **`.env`** (gitignored). Copy from `.env.example`.
