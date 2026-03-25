# Agents

- **Workflow:** [`AGENT_FLOW.md`](AGENT_FLOW.md) (English) — iteration checklist, Gemini usage, `reports/` folder.
- **Rules:** [`.cursor/rules/prosperity-agent-loop.mdc`](.cursor/rules/prosperity-agent-loop.mdc)
- **Goals / limits:** [`program.md`](program.md)
- **Record a run:** `uv run python scripts/agent_cycle.py`
- **Overnight autoresearch-style loop:** `uv run autoresearch.py --iterations 10` (needs `GOOGLE_API_KEY` in `.env`); see [`README.md`](README.md)
