# Agents

- **Workflow:** [`AGENT_FLOW.md`](AGENT_FLOW.md) (English) — iteration checklist, Gemini usage, `reports/` folder.
- **Rules:** [`.cursor/rules/prosperity-agent-loop.mdc`](.cursor/rules/prosperity-agent-loop.mdc)
- **Goals / limits:** [`program.md`](program.md)
- **Record a run:** `uv run python scripts/agent_cycle.py` (also writes `reports/backtests/*.log` for [Prosperity Visualizer](https://prosperity.equirag.com/) + parsed PnL in the report)
- **Official log (manual JSON export):** `uv run python scripts/analyze_official_log.py reports/official/<file>.json` — see `reports/official/README.md`
- **Overnight autoresearch-style loop:** `uv run autoresearch.py --iterations 10` (needs `GOOGLE_API_KEY` in `.env`); see [`README.md`](README.md)
