"""
Offline analysis of Prosperity CSV samples under data/ (flat or ``data/roundN/*.csv``).
Does not import the trading algorithm; use insights to tune algorithm.py constants.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

DATA_DIR = Path(__file__).resolve().parent / "data"

# Mirror typical algorithm.py knobs for “what-if” rates (update if algorithm drifts).
REF_TAKER_THRESHOLD = 0.5
REF_EMERALDS_FAIR = 10000
REF_TOMATOES_EMA_ALPHA = 0.44


def _read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, sep=";")


def _micro_price_vectorized(g: pd.DataFrame) -> pd.Series:
    """Same construction as Trader._compute_micro_price (L1 only)."""
    bb = g["bid_price_1"].astype(float)
    ba = g["ask_price_1"].astype(float)
    bv = g["bid_volume_1"].astype(float)
    av = g["ask_volume_1"].astype(float).abs()
    den = bv + av
    out = (bb * av + ba * bv) / den
    return out.where(den > 0)


def _fair_value_series_for_taker_stats(
    product: str, micro: pd.Series, timestamps: pd.Series
) -> list[float]:
    """
    Row-aligned fair value proxy: fixed EMERALDS fair, EMA(micro) for TOMATOES in timestamp order.
    Returns list same length as micro (NaNs where micro is NaN / uninitialized).
    """
    if product == "EMERALDS":
        return [float(REF_EMERALDS_FAIR)] * len(micro)

    if product != "TOMATOES":
        return [float(m) if pd.notna(m) else float("nan") for m in micro]

    order = timestamps.to_numpy().argsort(kind="mergesort")
    micro_s = micro.iloc[order].reset_index(drop=True)
    fair_out = [0.0] * len(micro)
    ema: float | None = None
    for i in range(len(micro_s)):
        m = micro_s.iloc[i]
        if pd.isna(m):
            fair_out[order[i]] = float("nan")
            continue
        if ema is None:
            ema = float(m)
        else:
            a = REF_TOMATOES_EMA_ALPHA
            ema = a * float(m) + (1.0 - a) * ema
        fair_out[order[i]] = ema
    return fair_out


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
        if "timestamp" in g.columns:
            g = g.sort_values("timestamp", kind="mergesort")
        g = g.reset_index(drop=True)

        if "mid_price" in g.columns:
            mp = g["mid_price"].astype(float)
            block["mid_price"] = {
                "mean": float(mp.mean()),
                "std": float(mp.std(ddof=0)),
                "min": float(mp.min()),
                "max": float(mp.max()),
            }
            ch = mp.diff().dropna().reset_index(drop=True)
            if len(ch) > 0:
                block["mid_price_delta"] = {
                    "mean_abs": float(ch.abs().mean()),
                    "std": float(ch.std(ddof=0)),
                }
                # Lag-1 autocorr of tick-to-tick changes (negative → mean-reverting noise).
                # Use positional alignment; .corr on Series aligns by index labels otherwise.
                if len(ch) > 2 and float(ch.std(ddof=0) or 0) > 1e-9:
                    v = ch.to_numpy()
                    c0, c1 = v[:-1], v[1:]
                    block["mid_price_delta_autocorr_lag1"] = float(
                        pd.Series(c0).corr(pd.Series(c1))
                    )
                # Realized vol: std of simple returns (ignore zeros in denom).
                ret = mp.pct_change().dropna()
                if len(ret) > 1:
                    block["mid_simple_return"] = {
                        "std": float(ret.std(ddof=0)),
                        "mean_abs": float(ret.abs().mean()),
                    }

        if "_spread" in g.columns:
            sp = g["_spread"].astype(float)
            block["spread"] = {
                "mean": float(sp.mean()),
                "std": float(sp.std(ddof=0)),
                "min": float(sp.min()),
                "max": float(sp.max()),
            }
            if "mid_price" in g.columns:
                mp = g["mid_price"].astype(float)
                half_spread = sp / 2.0
                block["half_spread_over_mid_bps"] = float(
                    (half_spread / mp.replace(0, float("nan"))).mean() * 10_000.0
                )

        if all(
            c in g.columns for c in ("bid_price_1", "ask_price_1", "bid_volume_1", "ask_volume_1")
        ):
            micro = _micro_price_vectorized(g)
            block["micro_vs_mid"] = {}
            if "mid_price" in g.columns:
                mp = g["mid_price"].astype(float)
                diff = (micro - mp).abs()
                block["micro_vs_mid"] = {
                    "mean_abs": float(diff.mean(skipna=True)),
                    "max_abs": float(diff.max(skipna=True)),
                }
            ts = g["timestamp"] if "timestamp" in g.columns else pd.Series(range(len(g)))
            fair_l = _fair_value_series_for_taker_stats(str(product), micro, ts)
            # EMERALDS path already filled; TOMATOES filled; ensure list length
            fair = pd.Series(fair_l, index=g.index, dtype=float)
            ask1 = g["ask_price_1"].astype(float)
            bid1 = g["bid_price_1"].astype(float)
            valid = fair.notna()
            if valid.any():
                buy_take = (ask1 < fair - REF_TAKER_THRESHOLD) & valid
                sell_take = (bid1 > fair + REF_TAKER_THRESHOLD) & valid
                n = int(valid.sum())
                block["taker_opportunity_rate_vs_ref"] = {
                    "threshold": REF_TAKER_THRESHOLD,
                    "fair_proxy": "EMA(micro)"
                    if product == "TOMATOES"
                    else f"fixed_{REF_EMERALDS_FAIR}",
                    "pct_ticks_ask_below_fair_minus_thr": float(buy_take.sum() / n) if n else 0.0,
                    "pct_ticks_bid_above_fair_plus_thr": float(sell_take.sum() / n) if n else 0.0,
                }
            bv = g["bid_volume_1"].astype(float)
            av = g["ask_volume_1"].astype(float).abs()
            den_imb = bv + av
            imb = (bv - av) / den_imb.replace(0, float("nan"))
            block["l1_book_imbalance"] = {
                "mean": float(imb.mean(skipna=True)),
                "std": float(imb.std(ddof=0)) if imb.notna().sum() > 1 else 0.0,
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


def analyze_trades(
    df: pd.DataFrame, source: str, prices_df: pd.DataFrame | None = None
) -> dict[str, Any]:
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

    if (
        prices_df is not None
        and "timestamp" in df.columns
        and all(c in prices_df.columns for c in ("timestamp", "product", "mid_price"))
    ):
        p = prices_df[["timestamp", "product", "mid_price"]].copy()
        p = p.rename(columns={"product": "symbol"})
        merged = df.merge(p, on=["timestamp", "symbol"], how="left")
        merged["_mid"] = merged["mid_price"].astype(float)
        valid = merged["_mid"].notna() & merged["_px"].notna() & (merged["_mid"].abs() > 1e-9)
        if valid.any():
            slip_bps = (
                (merged.loc[valid, "_px"] - merged.loc[valid, "_mid"])
                / merged.loc[valid, "_mid"]
                * 10_000.0
            )
            out["trade_vs_mid_at_tick"] = {
                "matched_trades": int(valid.sum()),
                "unmatched_trades": int((~valid).sum()),
                "signed_diff_bps_mean": float(slip_bps.mean()),
                "abs_diff_bps_mean": float(slip_bps.abs().mean()),
                "abs_diff_bps_p90": float(slip_bps.abs().quantile(0.9)),
            }
            by_sym: dict[str, Any] = {}
            for sym, gg in merged[valid].groupby("symbol"):
                s = (gg["_px"] - gg["_mid"]) / gg["_mid"] * 10_000.0
                by_sym[str(sym)] = {
                    "n": int(len(gg)),
                    "signed_diff_bps_mean": float(s.mean()),
                    "abs_diff_bps_mean": float(s.abs().mean()),
                }
            out["trade_vs_mid_by_symbol_bps"] = by_sym

    return out


def _aggregate_price_insights(analyses: list[dict[str, Any]]) -> dict[str, Any]:
    """Roll up per-product stats across all price_* files for quick comparison."""
    from collections import defaultdict

    acc: dict[str, list[float]] = defaultdict(list)
    for block in analyses:
        if "by_product" not in block:
            continue
        for prod, stats in block["by_product"].items():
            if "spread" in stats:
                acc[f"{prod}_spread_mean"].append(stats["spread"]["mean"])
            if "mid_price_delta" in stats:
                acc[f"{prod}_mid_delta_mean_abs"].append(stats["mid_price_delta"]["mean_abs"])
            tor = stats.get("taker_opportunity_rate_vs_ref")
            if tor:
                acc[f"{prod}_taker_buy_rate"].append(tor["pct_ticks_ask_below_fair_minus_thr"])
                acc[f"{prod}_taker_sell_rate"].append(tor["pct_ticks_bid_above_fair_plus_thr"])

    summary: dict[str, Any] = {}
    for k, vals in acc.items():
        if vals:
            summary[k] = {"mean": float(sum(vals) / len(vals)), "n_files": len(vals)}
    return summary


def _algorithm_hints(analyses: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    rollup = _aggregate_price_insights(analyses)
    lines.append(
        "Reference knobs: "
        f"TAKER_THRESHOLD={REF_TAKER_THRESHOLD}, EMERALDS_FAIR={REF_EMERALDS_FAIR}, "
        f"TOMATOES_EMA_ALPHA={REF_TOMATOES_EMA_ALPHA}"
    )
    for key in sorted(rollup.keys()):
        r = rollup[key]
        lines.append(f"  {key}: mean={r['mean']:.6g} over {r['n_files']} price file(s)")
    lines.append("Interpretation:")
    lines.append(
        "  • taker_opportunity_rate: high buy/sell % → lowering TAKER_THRESHOLD may increase "
        "crosses; very low % → taker leg rarely fires; rely on maker or widen perception of edge."
    )
    lines.append(
        "  • mid_price_delta_autocorr_lag1: negative → choppy/mean-reverting microstructure; "
        "positive → short-term momentum in tick changes."
    )
    lines.append(
        "  • micro_vs_mid mean_abs: large vs TAKER_THRESHOLD → fair_value from micro differs "
        "from mid; algorithm uses micro for EMA input, not mid."
    )
    lines.append(
        "  • l1_book_imbalance mean: positive → more bid size at touch on average (pressure up); "
        "inventory skew in algorithm pushes quotes the opposite way when long/short."
    )
    lines.append(
        "  • trade_vs_mid: large |bps| → prints away from mid; maker/taker fills may differ "
        "from mid PnL marks."
    )
    return lines


def load_all_csv(data_dir: Path = DATA_DIR) -> tuple[list[dict[str, Any]], list[str]]:
    """Load every ``*.csv`` under data_dir (recursive); return analyses + issues."""
    if not data_dir.is_dir():
        return [], [f"Data directory not found: {data_dir}"]

    analyses: list[dict[str, Any]] = []
    issues: list[str] = []
    price_cache: dict[tuple[Path, str], pd.DataFrame] = {}

    paths = sorted(data_dir.rglob("*.csv"))

    for path in paths:
        name = path.name
        parent = path.parent
        label = str(path.relative_to(data_dir))
        try:
            df = _read_csv(path)
        except Exception as e:
            issues.append(f"{label}: failed to read ({e})")
            continue

        if name.startswith("prices_"):
            price_cache[(parent, name)] = df
            analyses.append(analyze_prices(df, label))
        elif name.startswith("trades_"):
            buddy = "prices_" + name.removeprefix("trades_")
            p_df = price_cache.get((parent, buddy))
            if p_df is None:
                issues.append(
                    f"{label}: no matching {buddy} in same folder for mid join "
                    "(trades-vs-mid stats skipped)"
                )
            analyses.append(analyze_trades(df, label, prices_df=p_df))
        else:
            issues.append(f"{label}: skipped (expected name prefix prices_ or trades_)")

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

    price_blocks = [b for b in analyses if "by_product" in b]
    if price_blocks:
        lines.append("## Algorithm-oriented hints (read with algorithm.py constants)")
        for hint in _algorithm_hints(price_blocks):
            lines.append(hint)
        lines.append("")

    for block in analyses:
        lines.append(f"## {block['source']}")
        if "by_product" in block:
            for prod, stats in block["by_product"].items():
                lines.append(f"  [{prod}] {stats}")
        elif "by_symbol" in block:
            for sym, stats in block["by_symbol"].items():
                lines.append(f"  [{sym}] {stats}")
            if "trade_vs_mid_at_tick" in block:
                lines.append(f"  [__vs_mid__] {block['trade_vs_mid_at_tick']}")
            if "trade_vs_mid_by_symbol_bps" in block:
                lines.append(f"  [__vs_mid_by_symbol__] {block['trade_vs_mid_by_symbol_bps']}")
        else:
            lines.append(f"  (rows={block.get('rows', '?')})")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    analyses, issues = load_all_csv()
    print(_format_report(analyses, issues), end="")


if __name__ == "__main__":
    main()
