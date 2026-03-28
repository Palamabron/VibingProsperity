# VibingProsperity

IMC Prosperity 4 trading algorithm with offline CSV analysis and **platform-side evaluation** by uploading `algorithm.py` via [`scripts/submit_live.py`](scripts/submit_live.py) (requires `PROSPERITY_ID_TOKEN` in `.env`; use [`scripts/get_token.py`](scripts/get_token.py) to refresh the token).

This repo mirrors the **small surface area** of [Karpathy autoresearch](https://github.com/karpathy/autoresearch): fixed prep, one editable “training” file, `program.md`, and an optional **overnight loop** that proposes code with **Gemini** and keeps changes only if **total profit** from the live evaluation improves.

## How it works

| autoresearch | VibingProsperity |
|--------------|------------------|
| `prepare.py` — data prep & utilities, **do not edit** for normal research | [`prepare.py`](prepare.py) — sanity check; **do not edit** for strategy work |
| `train.py` — agent edits model & training | [`algorithm.py`](algorithm.py) — **`Trader` for submission** (same role as `train.py`) |
| `program.md` — human sets agent instructions | [`program.md`](program.md) |
| Fixed time budget, metric `val_bpb` | **Total profit** from the platform run; compare runs in [`reports/`](reports/) |
| Manual: `uv run train.py` | Manual: `uv run python scripts/agent_cycle.py` |
| Overnight: many train runs | [`autoresearch.py`](autoresearch.py): Gemini proposes full `algorithm.py` → upload/evaluate → **keep if better** |

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)
- For **`scripts/agent_cycle.py`** / **`scripts/submit_live.py`**: `PROSPERITY_ID_TOKEN` in `.env` (see [`.env.example`](.env.example))
- For **autoresearch.py**: a [Google AI API key](https://aistudio.google.com/apikey) in `.env` as `GOOGLE_API_KEY`
- Optional: for `scripts/get_token.py --auto`, install Playwright in the project (`uv add playwright && uv run playwright install chromium`). Prefer storing `PROSPERITY_EMAIL` / `PROSPERITY_PASSWORD` in `.env` rather than passing secrets on the command line (passwords end up in shell history).

### `agent_cycle` subprocess timeouts

`scripts/agent_cycle.py` limits how long `data_analytics.py` may run (default: 300s). Override with `--timeout-data-analytics` (seconds; `0` = no limit) or `AGENT_CYCLE_TIMEOUT_DATA_ANALYTICS` (empty or `none` = no limit). The overnight loop wraps each `agent_cycle` run with `AGENT_CYCLE_SCRIPT_TIMEOUT` (default 7200s; empty/`none` = no limit). See [`.env.example`](.env.example).

## Quick start

```bash
uv sync
uv run prepare.py              # optional sanity check (like autoresearch prepare)
uv run data_analytics.py       # summarize CSVs under data/ (e.g. data/round0/)
uv run python scripts/agent_cycle.py   # analytics + live upload + English report under reports/runs/
```

`agent_cycle` runs `scripts/submit_live.py` (same HTTP flow as a manual upload) and adds **Parsed platform metrics** and a raw **submit_live result** block to the report. Optional logs are saved under `reports/submissions_live/` when the API returns a zip.

After an official session, you can still save submission JSON to `reports/official/` and run:

```bash
uv run python scripts/analyze_official_log.py reports/official/your.json -o reports/runs/your_official.md
```

(See `reports/official/README.md`.)

Evaluate only (upload + poll + optional log download):

```bash
uv run python scripts/submit_live.py
uv run python scripts/submit_live.py path/to/algorithm.py
```

## Running the overnight loop (like autoresearch)

Set `GOOGLE_API_KEY` in `.env` (copy from [`.env.example`](.env.example)). Optional: `GEMINI_MODEL` (e.g. a **Pro**-class id if your quota allows).

```bash
uv run autoresearch.py --iterations 10
uv run autoresearch_orchestrator.py --iterations 15 --plan-every 5
```

- Measures **baseline** profit from current `algorithm.py`, then each iteration asks Gemini for a **full new** `algorithm.py`, runs `scripts/agent_cycle.py`, and **keeps** the change only if **total profit** increases.
- Best-so-far code is copied to **`algorithm_best.py`**; state is in **`reports/autoresearch_state.json`**.
- No API / smoke test: `uv run autoresearch.py --dry-run` (runs one `agent_cycle` only).

For a **human- or Cursor-driven** loop without Gemini, use `program.md` + `reports/` + `uv run python scripts/agent_cycle.py` after each edit (see [`AGENT_FLOW.md`](AGENT_FLOW.md)).

## Design choices

- **Single submission file:** ship **`algorithm.py`** to IMC; `datamodel.py` is a local type shim for development only.
- **One number to optimize:** **total profit** from the platform graph / log when available.
- **Keep / discard:** `autoresearch.py` restores `algorithm.py` from `algorithm_best.py` when a candidate is worse or invalid (same spirit as autoresearch keeping the best checkpoint).
- **No `PROSPERITY4BT_*` in submission code** — do not tie the trader to backtest-only environment variables.

## Project structure

```
prepare.py           — fixed setup / sanity (do not edit for strategy research)
algorithm.py         — Trader implementation (agent edits this; same role as autoresearch train.py)
algorithm_best.py    — created by autoresearch.py when a new best is found
autoresearch.py      — optional Gemini loop: propose → agent_cycle → keep if better
program.md           — human-edited instructions for agents
data_analytics.py    — offline CSV analysis (data/)
datamodel.py         — local type shim for development (official contest provides datamodel)
scripts/agent_cycle.py — analytics + submit_live + reports/runs/* + INDEX.md
scripts/submit_live.py — upload algorithm.py and poll for results
scripts/get_token.py — refresh PROSPERITY_ID_TOKEN
scripts/analyze_official_log.py — parse saved official submission JSON (`activitiesLog`)
reports/             — English experiment reports + autoresearch state + submissions_live/ + official/
context/             — competition docs
AGENT_FLOW.md        — agentic workflow details
```

## See also

- [`program.md`](program.md) — metrics, guardrails, submission rules
- [`AGENT_FLOW.md`](AGENT_FLOW.md) — reports, API keys, Gemini notes
- [`AGENTS.md`](AGENTS.md) — quick links for coding agents
- [GeyzsoN/prosperity_rust_backtester](https://github.com/GeyzsoN/prosperity_rust_backtester) — optional community Rust backtester (separate toolchain; not used by this repo)
