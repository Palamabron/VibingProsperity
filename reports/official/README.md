# Official platform logs (manual)

IMC Prosperity does **not** publish a stable public API for [the game](https://prosperity.imc.com/game) to upload `algorithm.py` or download submission results from scripts.

**Workflow:**

1. Submit `algorithm.py` in the browser as usual.
2. When the submission finishes, save the JSON that contains `submissionId` and `activitiesLog` (e.g. from DevTools → Network → copy response body) into this folder, e.g. `submission_20260326.json`.
3. Analyze locally:

   ```bash
   uv run python scripts/analyze_official_log.py reports/official/submission_20260326.json -o reports/runs/20260326_official_submission.md
   ```

Compare that summary to **Parsed backtest metrics** in your latest `reports/runs/*_experiment.md`.

Optional: add `reports/official/*.json` to `.gitignore` if you do not want submission payloads in git.
