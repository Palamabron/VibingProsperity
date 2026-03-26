"""
Run prosperity4btx on algorithm.py with project-friendly defaults.

Usage:
  uv run backtest.py
  uv run backtest.py --round 0 --merge-pnl
  uv run backtest.py --days 1-0 1-1 --out backtests/run.log

If ./data/round0 exists with prices_*.csv (IMC / prosperity4bt layout), --data ./data is set
automatically (use --no-auto-data for the PyPI package’s bundled copy only).
Default --match-trades is ``worse`` (stricter vs historical tape; ``all`` is lenient replay).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT_ALGO = ROOT / "algorithm.py"
_REPO_DATA = ROOT / "data"


def _auto_data_dir() -> Path | None:
    """Return ./data if it matches prosperity4btx layout (``round0/``, …).

    See packaged ``prosperity4bt/resources``.
    """
    if not _REPO_DATA.is_dir():
        return None
    r0 = _REPO_DATA / "round0"
    if r0.is_dir() and any(r0.glob("prices_*.csv")):
        return _REPO_DATA
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Backtest algorithm.py with prosperity4btx.")
    parser.add_argument(
        "--algorithm",
        type=Path,
        default=DEFAULT_ALGO,
        help="Path to trader file (default: ./algorithm.py)",
    )
    parser.add_argument(
        "--round",
        type=int,
        default=0,
        metavar="N",
        help="Round to backtest (passed as prosperity4btx day spec, e.g. 0)",
    )
    parser.add_argument(
        "--days",
        nargs="*",
        default=None,
        help="Optional day specs (e.g. 0-0 0-1). If omitted, uses --round as a single spec.",
    )
    parser.add_argument("--merge-pnl", action="store_true", help="Merge PnL across days.")
    parser.add_argument("--out", type=Path, default=None, help="Output log path.")
    parser.add_argument(
        "--data",
        type=Path,
        default=None,
        help=(
            "Parent dir with round0/, round1/, … (prosperity4bt layout). "
            "Default: ./data if ./data/round0 has prices_*.csv."
        ),
    )
    parser.add_argument(
        "--no-auto-data",
        action="store_true",
        help="Do not pass --data even if ./data exists (use prosperity4btx bundled paths).",
    )
    parser.add_argument(
        "--print",
        dest="print_trader",
        action="store_true",
        help="Print trader stdout.",
    )
    parser.add_argument("--no-out", action="store_true", help="Do not write output log file.")
    parser.add_argument(
        "--match-trades",
        choices=("all", "worse", "none"),
        default="worse",
        help=(
            "Historical tape vs resting-order matching (default: worse — stricter; "
            "'all' is more lenient replay)."
        ),
    )
    parser.add_argument(
        "--original-timestamps",
        action="store_true",
        help="Preserve per-day timestamps in --out log (recommended for merged multi-day logs).",
    )
    parser.add_argument(
        "--no-progress",
        action="store_true",
        help="Hide tqdm progress bars (forwarded to prosperity4btx).",
    )
    args = parser.parse_args()

    algo = args.algorithm.resolve()
    if not algo.is_file():
        print(f"Algorithm file not found: {algo}", file=sys.stderr)
        return 1

    if args.days:
        day_specs = args.days
    else:
        day_specs = [str(args.round)]

    cmd: list[str] = [
        "prosperity4btx",
        str(algo),
        *day_specs,
        f"--match-trades={args.match_trades}",
    ]
    if args.merge_pnl:
        cmd.append("--merge-pnl")
    if args.out is not None:
        cmd.extend(["--out", str(args.out.resolve())])
    if args.no_out:
        cmd.append("--no-out")
    data_path: Path | None = None
    if args.data is not None:
        data_path = args.data.resolve()
    elif not args.no_auto_data:
        auto = _auto_data_dir()
        if auto is not None:
            data_path = auto.resolve()
    if data_path is not None:
        cmd.extend(["--data", str(data_path)])
    if args.original_timestamps:
        cmd.append("--original-timestamps")
    if args.print_trader:
        cmd.append("--print")
    if args.no_progress:
        cmd.append("--no-progress")

    try:
        return subprocess.call(cmd, cwd=ROOT)
    except FileNotFoundError:
        print(
            "prosperity4btx not found. Install deps: uv sync",
            file=sys.stderr,
        )
        return 127


if __name__ == "__main__":
    raise SystemExit(main())
