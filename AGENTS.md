# Agents

- **Workflow:** [`AGENT_FLOW.md`](AGENT_FLOW.md) (English) — iteration checklist, Gemini usage, `reports/` folder.
- **Rules:** [`.cursor/rules/prosperity-agent-loop.mdc`](.cursor/rules/prosperity-agent-loop.mdc)
- **Goals / limits:** [`program.md`](program.md)
- **Record a run:** `uv run python scripts/agent_cycle.py` (analytics + `submit_live` + parsed PnL in the report; optional logs under `reports/submissions_live/`)
- **Official log (manual JSON export):** `uv run python scripts/analyze_official_log.py reports/official/<file>.json` — see `reports/official/README.md`
- **Overnight autoresearch-style loop:** `uv run autoresearch.py --iterations 10` (needs `GOOGLE_API_KEY` and a valid `PROSPERITY_ID_TOKEN` for each `agent_cycle`); see [`README.md`](README.md)
