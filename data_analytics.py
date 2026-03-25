"""
Offline analysis of Prosperity CSV samples under data/ (prices_*, trades_*).
Does not import the trading algorithm; use insights to tune algorithm.py constants.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

DATA_DIR = Path(__file__).resolve().parent / "data"


def _read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, sep=";")


def analyze_prices(df: pd.DataFrame, source: str) -> dict[str, Any]:
    out: dict[str, Any] = {"source": source, "rows": len(df)}
    if "product" not in df.columns:
        return out

    if "bid_price_1" in df.columns and "ask_price_1" in df.columns:
        df = df.copy()
        df["_spread"] = df["ask_price_1"].astype(float) - df["bid_price_1"].astype(float)

    grouped = df.groupby("product", sort=True)
    per_product: dict[str, Any] = {}
    for product, g in grouped:
        block: dict[str, Any] = {"ticks": len(g)}
        if "mid_price" in g.columns:
            mp = g["mid_price"].astype(float)
            block["mid_price"] = {
                "mean": float(mp.mean()),
                "std": float(mp.std(ddof=0)),
                "min": float(mp.min()),
                "max": float(mp.max()),
            }
            ch = mp.diff().dropna()
            if len(ch) > 0:
                block["mid_price_delta"] = {
                    "mean_abs": float(ch.abs().mean()),
                    "std": float(ch.std(ddof=0)),
                }
        if "_spread" in g.columns:
            sp = g["_spread"].astype(float)
            block["spread"] = {
                "mean": float(sp.mean()),
                "std": float(sp.std(ddof=0)),
                "min": float(sp.min()),
                "max": float(sp.max()),
            }
        if "profit_and_loss" in g.columns:
            pnl = g["profit_and_loss"].astype(float)
            block["profit_and_loss"] = {
                "last": float(pnl.iloc[-1]),
                "min": float(pnl.min()),
                "max": float(pnl.max()),
            }
        per_product[str(product)] = block

    out["by_product"] = per_product
    return out


def analyze_trades(df: pd.DataFrame, source: str) -> dict[str, Any]:
    out: dict[str, Any] = {"source": source, "rows": len(df)}
    if "symbol" not in df.columns:
        return out

    df = df.copy()
    df["_qty"] = df["quantity"].astype(float) if "quantity" in df.columns else 0.0
    df["_px"] = df["price"].astype(float) if "price" in df.columns else float("nan")

    grouped = df.groupby("symbol", sort=True)
    per_symbol: dict[str, Any] = {}
    for sym, g in grouped:
        per_symbol[str(sym)] = {
            "trade_count": int(len(g)),
            "volume": float(g["_qty"].sum()),
            "price_mean": float(g["_px"].mean()),
            "price_std": float(g["_px"].std(ddof=0)) if len(g) > 1 else 0.0,
            "price_min": float(g["_px"].min()),
            "price_max": float(g["_px"].max()),
        }
    out["by_symbol"] = per_symbol
    return out


def load_all_csv(data_dir: Path = DATA_DIR) -> tuple[list[dict[str, Any]], list[str]]:
    """Load every *.csv under data_dir; return (list of analyses, list of issues)."""
    if not data_dir.is_dir():
        return [], [f"Data directory not found: {data_dir}"]

    analyses: list[dict[str, Any]] = []
    issues: list[str] = []

    for path in sorted(data_dir.glob("*.csv")):
        name = path.name
        try:
            df = _read_csv(path)
        except Exception as e:
            issues.append(f"{name}: failed to read ({e})")
            continue

        if name.startswith("prices_"):
            analyses.append(analyze_prices(df, name))
        elif name.startswith("trades_"):
            analyses.append(analyze_trades(df, name))
        else:
            issues.append(f"{name}: skipped (expected name prefix prices_ or trades_)")

    return analyses, issues


def _format_report(analyses: list[dict[str, Any]], issues: list[str]) -> str:
    lines: list[str] = ["=== Prosperity data/ CSV summary ===", ""]
    for msg in issues:
        lines.append(f"! {msg}")
    if issues:
        lines.append("")
    if not analyses:
        lines.append("No analyses produced.")
        return "\n".join(lines)

    for block in analyses:
        lines.append(f"## {block['source']}")
        if "by_product" in block:
            for prod, stats in block["by_product"].items():
                lines.append(f"  [{prod}] {stats}")
        elif "by_symbol" in block:
            for sym, stats in block["by_symbol"].items():
                lines.append(f"  [{sym}] {stats}")
        else:
            lines.append(f"  (rows={block.get('rows', '?')})")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    analyses, issues = load_all_csv()
    print(_format_report(analyses, issues), end="")


if __name__ == "__main__":
    main()
