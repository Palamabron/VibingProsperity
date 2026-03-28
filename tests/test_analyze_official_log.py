"""Tests for scripts/analyze_official_log.py parsing helpers."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from analyze_official_log import (  # noqa: E402
    _final_pnl_by_key,
    _parse_activities,
    _per_day_totals,
    _product_totals,
)


def test_parse_and_final_pnl_latest_timestamp_wins() -> None:
    csv_text = "day;timestamp;product;profit_and_loss\n0;10;A;100\n0;20;A;250\n0;15;B;50\n"
    rows, names = _parse_activities(csv_text)
    assert "profit_and_loss" in "".join(names) or "profit_and_loss" in (names or [])
    finals, total = _final_pnl_by_key(rows)
    assert finals[("0", "A")] == 250.0
    assert finals[("0", "B")] == 50.0
    assert total == 300.0
    assert _per_day_totals(finals)["0"] == 300.0
    pt = _product_totals(finals)
    assert pt["A"] == 250.0 and pt["B"] == 50.0


def test_json_summary_roundtrip(tmp_path: Path) -> None:
    """Smoke: CLI writes JSON summary when requested."""
    payload = {
        "submissionId": "sub-1",
        "activitiesLog": ("day;timestamp;product;profit_and_loss\n0;1;X;10\n0;2;X;20\n"),
    }
    p = tmp_path / "log.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    out_md = tmp_path / "out.md"
    out_js = tmp_path / "out.json"
    from analyze_official_log import AnalyzeOfficialLogArgs, run_analyze

    code = run_analyze(AnalyzeOfficialLogArgs(json_path=p, out=out_md, json_summary=out_js))
    assert code == 0
    assert out_md.is_file()
    data = json.loads(out_js.read_text(encoding="utf-8"))
    assert data["submission_id"] == "sub-1"
    assert data["total_final_pnl_sum"] == 20.0
