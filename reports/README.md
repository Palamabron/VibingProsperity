# Experiment reports (English)

This folder stores **structured experiment logs** for multi-agent and human-in-the-loop workflows. Each run should produce measurable outputs (data analytics + backtest) and **written conclusions** so the next iteration can read prior work without re-deriving context.

## Layout

| Path | Purpose |
|------|---------|
| `runs/` | Timestamped markdown files: raw tool output + sections for agent-written insights. |
| `autoresearch_state.json` | Written by `autoresearch.py`: best profit + last iteration (optional). |
| `INDEX.md` | **Regenerated** by `uv run python scripts/agent_cycle.py` — lists `runs/*.md` newest first with `total_profit` from YAML front matter. |
| `TEMPLATE.md` | Copy this if you create a report by hand instead of using `scripts/agent_cycle.py`. |

## Language

- **Reports are written in English** (insights, hypotheses, next steps) so any model (e.g. Gemini Pro, other agents) and teammates can consume them consistently.

## How agents should use this

1. **Before** changing `algorithm.py`, read the latest entries in `INDEX.md` and open the most recent `runs/*.md` files to see what was tried and what failed or improved.
2. **After** editing the trader, run `uv run scripts/agent_cycle.py` (or follow `AGENT_FLOW.md`) to append a new report with fresh metrics.
3. **Fill in** the sections *Insights*, *Hypotheses for next iteration*, and *Algorithm changes (summary)* in the new report (or in chat, then paste into the file).
4. Treat **total profit** from the backtest block as the primary score; compare to the previous run’s total on the same round/days.

## Do not commit secrets

Logs may contain paths; avoid pasting API keys or personal tokens into reports.
