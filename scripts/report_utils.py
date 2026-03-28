"""
Shared helpers for experiment reports under reports/runs/ and reports/INDEX.md.

Used by agent_cycle.py, agent_cycle_live.py, and autoresearch.py.

`parse_backtest_console_text` parses legacy local backtester-style text; live runs use
`parsed_backtest_from_live_result`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_BT_DAY_HEADER = re.compile(
    r"^Backtesting .+ on round (\d+) day (-?\d+)\s*$",
    re.MULTILINE,
)
_BT_PRODUCT_LINE = re.compile(r"^([A-Z0-9_]+):\s*([\d,]+)\s*$", re.MULTILINE)
_BT_TOTAL_PROFIT = re.compile(r"^Total profit:\s*([\d,]+)\s*$", re.MULTILINE)
_BT_SUMMARY_DAY = re.compile(r"^Round (\d+) day (-?\d+):\s*([\d,]+)\s*$", re.MULTILINE)


@dataclass
class DayBlock:
    round_n: int
    day: int
    products: dict[str, int]
    total: int


@dataclass
class ParsedBacktest:
    merged_total: int | None
    profit_summary_days: list[tuple[int, int, int]]
    day_blocks: list[DayBlock] = field(default_factory=list)


def parse_backtest_console_text(text: str) -> ParsedBacktest:
    day_blocks: list[DayBlock] = []
    for m in _BT_DAY_HEADER.finditer(text):
        start = m.end()
        next_m = _BT_DAY_HEADER.search(text, start)
        end = next_m.start() if next_m else len(text)
        chunk = text[start:end]
        r, d = int(m.group(1)), int(m.group(2))
        products: dict[str, int] = {}
        for pm in _BT_PRODUCT_LINE.finditer(chunk):
            name = pm.group(1)
            if name == "Total":
                continue
            products[name] = int(pm.group(2).replace(",", ""))
        tm = _BT_TOTAL_PROFIT.search(chunk)
        total = int(tm.group(1).replace(",", "")) if tm else 0
        day_blocks.append(DayBlock(round_n=r, day=d, products=products, total=total))

    profit_summary_days: list[tuple[int, int, int]] = []
    if "Profit summary:" in text:
        tail = text.split("Profit summary:", 1)[1]
        for sm in _BT_SUMMARY_DAY.finditer(tail):
            profit_summary_days.append(
                (int(sm.group(1)), int(sm.group(2)), int(sm.group(3).replace(",", "")))
            )

    merged_total: int | None = None
    for m in _BT_TOTAL_PROFIT.finditer(text):
        merged_total = int(m.group(1).replace(",", ""))

    return ParsedBacktest(
        merged_total=merged_total,
        profit_summary_days=profit_summary_days,
        day_blocks=day_blocks,
    )


def parsed_backtest_from_live_result(result: dict[str, Any]) -> ParsedBacktest:
    """Build ParsedBacktest from `submit_live.submit_and_wait` result for reports."""
    tp = result.get("total_profit")
    merged: int | None = int(tp) if tp is not None else None
    raw_pp = result.get("per_product") or {}
    products_int: dict[str, int] = {str(k): int(round(float(v))) for k, v in raw_pp.items()}
    day_blocks: list[DayBlock] = []
    if products_int:
        total = merged if merged is not None else sum(products_int.values())
        day_blocks.append(DayBlock(round_n=0, day=0, products=products_int, total=total))
    return ParsedBacktest(
        merged_total=merged,
        profit_summary_days=[],
        day_blocks=day_blocks,
    )


def parse_total_profit_from_backtest_output(text: str) -> int | None:
    last: str | None = None
    for m in re.finditer(r"Total profit:\s*([\d,]+)", text):
        last = m.group(1)
    if last is None:
        return None
    return int(last.replace(",", ""))


def parse_simple_front_matter(raw: str) -> dict[str, Any]:
    """Parse a leading `---` ... `---` block (subset of YAML: key: value per line)."""
    s = raw.lstrip()
    if not s.startswith("---"):
        return {}
    rest = s[3:].lstrip("\n")
    end_sep = rest.find("\n---")
    if end_sep == -1:
        return {}
    block = rest[:end_sep]
    out: dict[str, Any] = {}
    for line in block.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, tail = line.partition(":")
        key = key.strip()
        val = tail.strip()
        if val == "" or val.lower() == "null":
            out[key] = None
        elif val in ("true", "false"):
            out[key] = val == "true"
        elif re.fullmatch(r"-?\d+", val):
            out[key] = int(val)
        elif (val.startswith('"') and val.endswith('"')) or (
            val.startswith("'") and val.endswith("'")
        ):
            out[key] = val[1:-1]
        else:
            out[key] = val
    return out


def experiment_reports_sorted(
    runs_dir: Path,
    *,
    pattern: str = "*_experiment.md",
) -> list[Path]:
    files = [p for p in runs_dir.glob(pattern) if p.is_file()]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files


def parse_total_profit_from_report(raw: str) -> int | None:
    """Prefer YAML front matter; fall back to legacy regex for older reports."""
    fm = parse_simple_front_matter(raw)
    if "total_profit" in fm and fm["total_profit"] is not None:
        v = fm["total_profit"]
        return int(v) if isinstance(v, int) else None
    m = re.search(r"^total_profit:\s*(\d+)\s*$", raw, re.MULTILINE)
    return int(m.group(1)) if m else None


def latest_experiment_total_profit(runs_dir: Path) -> tuple[int | None, str | None]:
    """Newest report file by mtime: (total_profit, filename)."""
    files = experiment_reports_sorted(runs_dir)
    if not files:
        return None, None
    path = files[0]
    raw = path.read_text(encoding="utf-8")
    return parse_total_profit_from_report(raw), path.name


def previous_experiment_totals(runs_dir: Path) -> tuple[int | None, str | None]:
    """Same as latest: 'previous' to the next report is the current newest on disk before write."""
    return latest_experiment_total_profit(runs_dir)


def rebuild_experiment_index(
    *,
    runs_dir: Path,
    index_path: Path,
    reports_root: Path,
    max_entries: int = 40,
) -> None:
    """Single writer for reports/INDEX.md: bullets from all *_experiment.md files."""
    runs_dir.mkdir(parents=True, exist_ok=True)
    files = experiment_reports_sorted(runs_dir)
    lines: list[str] = [
        "# Experiment index",
        "",
        "Newest first (from YAML front matter in each run file).",
        "",
    ]
    for path in files[:max_entries]:
        raw = path.read_text(encoding="utf-8")
        fm = parse_simple_front_matter(raw)
        tp = fm.get("total_profit")
        if tp is None:
            m = re.search(r"^total_profit:\s*(\d+)\s*$", raw, re.MULTILINE)
            tp_s = m.group(1) if m else "n/a"
        else:
            tp_s = str(tp)
        rn = fm.get("round")
        rn_s = str(rn) if rn is not None else "?"
        src = fm.get("source", "local")
        if not isinstance(src, str):
            src = str(src)
        rel = path.relative_to(reports_root).as_posix()
        lines.append(
            f"- [`{path.name}`]({rel}) — **{src}**, round **{rn_s}**, total profit **{tp_s}**"
        )
    lines.append("")
    index_path.write_text("\n".join(lines), encoding="utf-8")


def format_front_matter_yaml(data: dict[str, Any]) -> str:
    """Serialize a small flat dict to a YAML front matter block (no nested structures)."""
    lines = ["---"]
    for k, v in data.items():
        if v is None:
            lines.append(f"{k}: null")
        elif isinstance(v, bool):
            lines.append(f"{k}: {str(v).lower()}")
        elif isinstance(v, int):
            lines.append(f"{k}: {v}")
        else:
            esc = str(v).replace("\\", "\\\\").replace('"', '\\"')
            lines.append(f'{k}: "{esc}"')
    lines.append("---")
    return "\n".join(lines) + "\n"
