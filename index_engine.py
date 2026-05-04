"""
index_engine.py — New Age Tech Index: tiered weight calculator, performance
engine, and metrics computation.

Methodology (v2.0)
──────────────────
Tier        Market Cap Range    Tier Allocation    Intra-Tier
Large       > ₹50,000 Cr        50 %               Equal weight
Mid         ₹10,000–50,000 Cr   35 %               Equal weight
Small       ₹1,000–10,000 Cr    15 %               Equal weight

Per-stock weight = tier_allocation / count_of_companies_in_that_tier
Empty-tier allocation is redistributed proportionally across active tiers.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd

from config import (
    BASE_INDEX_VALUE, MIN_ADTV_CRORES, MIN_MARKET_CAP_CR,
    TIER_CONFIG, TIER_ORDER,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Tier Assignment
# ─────────────────────────────────────────────────────────────────────────────

def assign_tier(market_cap_cr: float) -> Optional[str]:
    for tier_name in TIER_ORDER:
        cfg = TIER_CONFIG[tier_name]
        if cfg["min_mc_cr"] <= market_cap_cr < cfg["max_mc_cr"]:
            return tier_name
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Weight Calculation
# ─────────────────────────────────────────────────────────────────────────────

def calculate_weights(data: dict[str, dict]) -> pd.DataFrame:
    """
    Build the constituent weight table from fetched market data.

    Parameters
    ----------
    data : dict  {ticker -> {"company", "price", "volume", "shares", "pe", "free_float_factor"}}

    Returns
    -------
    pd.DataFrame with columns:
        company, ticker, price, shares, free_float, full_mc_cr,
        free_float_mc, adtv_cr, pe, tier, tier_allocation, weight_final,
        daily_return_pct
    """
    rows: list[dict] = []
    excluded: list[tuple[str, str]] = []

    for ticker, d in data.items():
        company    = d["company"]
        price_s    = d["price"]
        volume_s   = d["volume"]
        shares     = d["shares"]
        free_float = d.get("free_float_factor", 1.0)
        pe         = d.get("pe")

        if price_s.empty:
            excluded.append((company, "no price data"))
            continue

        price        = float(price_s.iloc[-1])
        full_mc_cr   = (price * shares) / 1e7
        ff_mc_cr     = full_mc_cr * free_float

        # ADTV
        try:
            aligned = pd.concat([price_s, volume_s], axis=1).dropna()
            aligned.columns = ["price", "volume"]
            adtv_cr = float((aligned["price"] * aligned["volume"]).mean() / 1e7)
        except Exception:
            adtv_cr = float("nan")

        # Daily return
        try:
            daily_ret_pct = float(price_s.pct_change().iloc[-1] * 100)
        except Exception:
            daily_ret_pct = 0.0

        # ── Filters ──
        if full_mc_cr < MIN_MARKET_CAP_CR:
            excluded.append((company, f"market cap ₹{full_mc_cr:,.0f} Cr < minimum"))
            continue

        if pd.notna(adtv_cr) and adtv_cr < MIN_ADTV_CRORES:
            excluded.append((company, f"ADTV ₹{adtv_cr:.2f} Cr < ₹{MIN_ADTV_CRORES} Cr"))
            continue

        tier = assign_tier(full_mc_cr)
        if tier is None:
            excluded.append((company, "no matching tier"))
            continue

        rows.append({
            "company":       company,
            "ticker":        ticker,
            "price":         round(price, 2),
            "shares":        shares,
            "free_float":    free_float,
            "full_mc_cr":    round(full_mc_cr, 2),
            "free_float_mc": round(ff_mc_cr, 2),
            "adtv_cr":       round(adtv_cr, 2) if pd.notna(adtv_cr) else None,
            "pe":            round(pe, 2) if pe and pd.notna(pe) else None,
            "tier":          tier,
            "daily_return_pct": round(daily_ret_pct, 2),
        })

    if not rows:
        raise ValueError("No valid constituents survived screening filters.")

    df = pd.DataFrame(rows)

    # ── Tier allocation with empty-tier redistribution ──
    tier_counts   = df["tier"].value_counts().to_dict()
    active_tiers  = [t for t in TIER_ORDER if tier_counts.get(t, 0) > 0]
    empty_alloc   = sum(TIER_CONFIG[t]["allocation"] for t in TIER_ORDER if t not in active_tiers)

    active_alloc: dict[str, float] = {t: TIER_CONFIG[t]["allocation"] for t in active_tiers}
    if empty_alloc > 0:
        base = sum(active_alloc.values())
        for t in active_tiers:
            active_alloc[t] += empty_alloc * (active_alloc[t] / base)

    per_stock_wt = {t: active_alloc[t] / tier_counts[t] for t in active_tiers}
    df["tier_allocation"] = df["tier"].map(active_alloc)
    df["weight_final"]    = df["tier"].map(per_stock_wt)

    # ── Weighted-average P/E ──
    pe_valid = df.dropna(subset=["pe"])
    if not pe_valid.empty:
        df.attrs["weighted_pe"] = round(
            (pe_valid["pe"] * pe_valid["weight_final"]).sum() / pe_valid["weight_final"].sum(), 2
        )
    else:
        df.attrs["weighted_pe"] = None

    # ── Sort: tier order then market cap desc ──
    tier_rank = {t: i for i, t in enumerate(TIER_ORDER)}
    df["_tr"] = df["tier"].map(tier_rank)
    df = df.sort_values(["_tr", "full_mc_cr"], ascending=[True, False]).drop(columns=["_tr"]).reset_index(drop=True)

    if excluded:
        logger.debug("Excluded %d constituents: %s", len(excluded), excluded[:5])

    logger.info("Weight table: %d constituents across %d tiers", len(df), len(active_tiers))
    return df


# ─────────────────────────────────────────────────────────────────────────────
# Index Level Calculation
# ─────────────────────────────────────────────────────────────────────────────

def calculate_performance(
    data: dict[str, dict],
    weights_df: pd.DataFrame,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    """
    Simulate index level over time using static weights.

    Returns
    -------
    pd.DataFrame with columns: date, index_level, daily_return
    """
    weights_dict = weights_df.set_index("ticker")["weight_final"].to_dict()

    sample_ticker = weights_df.iloc[0]["ticker"]
    dates = data[sample_ticker]["price"].loc[start_date:end_date].index

    index_value = BASE_INDEX_VALUE
    records: list[dict] = []
    prev_date = None

    for date in dates:
        port_ret   = 0.0
        valid_wt   = 0.0
        if prev_date is not None:
            for ticker, wt in weights_dict.items():
                if ticker in data:
                    ps = data[ticker]["price"]
                    if date in ps.index and prev_date in ps.index:
                        stock_ret  = float(ps[date] / ps[prev_date]) - 1
                        port_ret  += wt * stock_ret
                        valid_wt  += wt
            if valid_wt > 0:
                port_ret /= valid_wt
            index_value *= (1 + port_ret)

        records.append({"date": date, "index_level": index_value, "daily_return": port_ret})
        prev_date = date

    return pd.DataFrame(records)


def calculate_tier_performance(
    data: dict[str, dict],
    weights_df: pd.DataFrame,
    start_date: str,
    end_date: str,
) -> dict[str, pd.DataFrame]:
    """Compute equal-weighted sub-index for each tier."""
    sample_ticker = weights_df.iloc[0]["ticker"]
    dates = data[sample_ticker]["price"].loc[start_date:end_date].index

    result: dict[str, pd.DataFrame] = {}
    for tier in TIER_ORDER:
        tickers = weights_df.loc[weights_df["tier"] == tier, "ticker"].tolist()
        if not tickers:
            continue
        level = BASE_INDEX_VALUE
        prev_date = None
        rows: list[dict] = []
        for date in dates:
            ret = 0.0
            n   = 0
            if prev_date is not None:
                for tk in tickers:
                    if tk in data:
                        ps = data[tk]["price"]
                        if date in ps.index and prev_date in ps.index:
                            ret += float(ps[date] / ps[prev_date]) - 1
                            n   += 1
                if n > 0:
                    ret /= n
                level *= (1 + ret)
            rows.append({"date": date, "level": level})
            prev_date = date
        result[tier] = pd.DataFrame(rows)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Metrics
# ─────────────────────────────────────────────────────────────────────────────

def calculate_metrics(
    performance_df: pd.DataFrame,
    weights_df: pd.DataFrame,
    nifty_returns: Optional[pd.Series] = None,
) -> dict:
    """
    Compute industry-standard index health metrics.

    Includes beta against NIFTY 50 when nifty_returns is supplied.
    """
    returns = performance_df["daily_return"].replace(0, np.nan).dropna()

    total_return     = float((1 + returns).prod() - 1)
    n_years          = len(returns) / 252
    ann_return       = float((1 + total_return) ** (1 / n_years) - 1) if n_years > 0 else 0.0
    ann_vol          = float(returns.std() * np.sqrt(252))

    sharpe = (ann_return - 0.068) / ann_vol if ann_vol > 0 else 0.0  # 6.8% RFR ≈ 1-yr T-bill

    cumulative = (1 + returns).cumprod()
    drawdown   = (cumulative - cumulative.cummax()) / cumulative.cummax()
    max_dd     = float(drawdown.min())

    downside   = returns[returns < 0]
    down_dev   = float(downside.std() * np.sqrt(252)) if len(downside) > 0 else 0.0
    sortino    = (ann_return - 0.068) / down_dev if down_dev > 0 else 0.0

    win_rate   = float((returns > 0).mean())

    # Beta vs NIFTY 50
    beta = None
    if nifty_returns is not None and len(nifty_returns) > 30:
        aligned = pd.concat([returns, nifty_returns.rename("nifty")], axis=1).dropna()
        cov     = aligned.cov().iloc[0, 1]
        var_m   = aligned["nifty"].var()
        beta    = round(cov / var_m, 3) if var_m > 0 else None

    # Weighted P/E
    pe_val = weights_df.attrs.get("weighted_pe")

    # Combined Mcap
    total_mcap = float(weights_df["full_mc_cr"].sum()) if "full_mc_cr" in weights_df.columns else 0.0

    # Gainers / Losers
    sorted_df = weights_df.sort_values("daily_return_pct", ascending=False)
    top5      = sorted_df.head(5)[["company", "ticker", "daily_return_pct"]].to_dict("records")
    bot5      = sorted_df.tail(5)[["company", "ticker", "daily_return_pct"]].to_dict("records")

    return {
        "Total Return":        f"{total_return:.2%}",
        "Annualized Return":   f"{ann_return:.2%}",
        "Annualized Vol (σ)":  f"{ann_vol:.2%}",
        "Sharpe Ratio":        f"{sharpe:.2f}",
        "Sortino Ratio":       f"{sortino:.2f}",
        "Max Drawdown":        f"{max_dd:.2%}",
        "Win Rate":            f"{win_rate:.2%}",
        "Trading Days":        len(returns),
        "Combined Mcap (₹ Cr)":f"₹{total_mcap:,.0f}",
        "Beta (vs NIFTY 50)":  beta,
        "Weighted P/E":        pe_val,
        "Top 5 Gainers":       top5,
        "Top 5 Losers":        bot5,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Constituent Table (for dashboard)
# ─────────────────────────────────────────────────────────────────────────────

def build_constituent_table(
    weights_df: pd.DataFrame,
    live_quotes: Optional[dict[str, float]] = None,
) -> pd.DataFrame:
    """
    Build the dashboard constituent performance table.

    live_quotes : optional dict {ticker -> latest LTP} for real-time CMP override.
    """
    df = weights_df.copy()

    if live_quotes:
        df["cmp"] = df["ticker"].map(live_quotes).fillna(df["price"])
    else:
        df["cmp"] = df["price"]

    # Recompute live daily % change if live quotes differ from EOD
    df["live_daily_pct"] = df.apply(
        lambda r: round((r["cmp"] / r["price"] - 1) * 100, 2)
        if live_quotes and r["ticker"] in live_quotes else r["daily_return_pct"],
        axis=1,
    )

    display = df[[
        "company", "ticker", "tier", "cmp", "live_daily_pct",
        "full_mc_cr", "weight_final", "pe"
    ]].copy()

    display.columns = [
        "Company", "Ticker", "Tier", "CMP (₹)",
        "Daily Chg %", "Market Cap (₹ Cr)", "Index Weight %", "P/E"
    ]
    display["Index Weight %"] = (display["Index Weight %"] * 100).round(2)
    display["CMP (₹)"]       = display["CMP (₹)"].round(2)
    display["Market Cap (₹ Cr)"] = display["Market Cap (₹ Cr)"].apply(lambda x: f"₹{x:,.0f}")

    return display.reset_index(drop=True)
