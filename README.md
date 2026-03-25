# VibingProsperity

IMC Prosperity 4 trading algorithm with offline CSV analysis and local backtests via [prosperity4btx](https://github.com/Xeeshan85/imc-prosperity-4-backtester) (`prosperity4btx` on PyPI).

This repo mirrors the **small surface area** of [Karpathy autoresearch](https://github.com/karpathy/autoresearch): fixed prep, one editable “training” file, `program.md`, and an optional **overnight loop** that proposes code with **Gemini** and keeps changes only if backtest profit improves.

## How it works

| autoresearch | VibingProsperity |
|--------------|------------------|
| `prepare.py` — data prep & utilities, **do not edit** for normal research | [`prepare.py`](prepare.py) — sanity check; **do not edit** for strategy work |
| `train.py` — agent edits model & training | [`algorithm.py`](algorithm.py) — **`Trader` for submission** (same role as `train.py`) |
| `program.md` — human sets agent instructions | [`program.md`](program.md) |
| Fixed time budget, metric `val_bpb` | Backtest **total profit** (same round/days); compare runs in [`reports/`](reports/) |
| Manual: `uv run train.py` | Manual: `uv run python scripts/agent_cycle.py` |
| Overnight: many train runs | [`autoresearch.py`](autoresearch.py): Gemini proposes full `algorithm.py` → backtest → **keep if better** |

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)
- For **autoresearch.py**: a [Google AI API key](https://aistudio.google.com/apikey) in `.env` as `GOOGLE_API_KEY`

## Quick start

```bash
uv sync
uv run prepare.py              # optional sanity check (like autoresearch prepare)
uv run data_analytics.py       # summarize data/*.csv
uv run python scripts/agent_cycle.py   # one backtest + English report under reports/runs/
```

Backtest only:

```bash
uv run backtest.py --round 0 --merge-pnl --no-progress
uv run prosperity4btx algorithm.py 0 --no-progress
```

## Running the overnight loop (like autoresearch)

Set `GOOGLE_API_KEY` in `.env` (copy from [`.env.example`](.env.example)). Optional: `GEMINI_MODEL` (e.g. a **Pro**-class id if your quota allows).

```bash
uv run autoresearch.py --iterations 10 --round 0
```

- Measures **baseline** profit from current `algorithm.py`, then each iteration asks Gemini for a **full new** `algorithm.py`, runs `scripts/agent_cycle.py`, and **keeps** the change only if **total profit** increases.
- Best-so-far code is copied to **`algorithm_best.py`**; state is in **`reports/autoresearch_state.json`**.
- No API / smoke test: `uv run autoresearch.py --dry-run` (runs one `agent_cycle` only).

For a **human- or Cursor-driven** loop without Gemini, use `program.md` + `reports/` + `uv run python scripts/agent_cycle.py` after each edit (see [`AGENT_FLOW.md`](AGENT_FLOW.md)).

## Design choices

- **Single submission file:** ship **`algorithm.py`** to IMC; `datamodel.py` is local for backtests only.
- **One number to optimize:** backtest **total profit** for a chosen `--round` (and compare across iterations).
- **Keep / discard:** `autoresearch.py` restores `algorithm.py` from `algorithm_best.py` when a candidate is worse or invalid (same spirit as autoresearch keeping the best checkpoint).
- **No `PROSPERITY4BT_*` in submission code** — those env vars exist only in the community backtester.

## Project structure

```
prepare.py           — fixed setup / sanity (do not edit for strategy research)
algorithm.py         — Trader implementation (agent edits this; same role as autoresearch train.py)
algorithm_best.py    — created by autoresearch.py when a new best is found
autoresearch.py      — optional Gemini loop: propose → backtest → keep if better
program.md           — human-edited instructions for agents
data_analytics.py    — offline CSV analysis (data/)
backtest.py          — wrapper for prosperity4btx
datamodel.py         — local shim for backtests only (official contest provides datamodel)
scripts/agent_cycle.py — analytics + backtest + reports/runs/* + INDEX.md
reports/             — English experiment reports + autoresearch state
context/             — competition docs
AGENT_FLOW.md        — agentic workflow details
```

## See also

- [`program.md`](program.md) — metrics, guardrails, submission rules
- [`AGENT_FLOW.md`](AGENT_FLOW.md) — reports, API keys, Gemini notes
- [`AGENTS.md`](AGENTS.md) — quick links for coding agents
