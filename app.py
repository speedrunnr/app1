"""
app.py — New Age Tech Index · Production Dashboard
Run with:  streamlit run app.py

Features
────────
• Interactive Plotly line chart (Index @ 1,000 base  OR  % change vs NIFTY 50)
• Constituent performance table (CMP, daily %, tier, weight)
• Index health metrics (P/E, mcap, vol, Sharpe, drawdown)
• Top 5 Gainers / Losers
• Auto-refresh during NSE/BSE market hours (configurable interval)
• Hourly CSV backup + EOD export
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import yfinance as yf
from plotly.subplots import make_subplots
from streamlit_autorefresh import st_autorefresh   # pip install streamlit-autorefresh

import csv_logger
import index_engine
from config import (
    BASE_INDEX_VALUE, IST, NIFTY_TICKER, REFRESH_INTERVAL_MARKET_HOURS_SEC,
    REFRESH_INTERVAL_OFF_HOURS_SEC, TIER_COLORS, TIER_ORDER,
)
from data_pipeline import DataProvider, is_market_open, market_status_label

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Page Config
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="New Age Tech Index",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    /* ---------- Color palette ---------- */
    :root {
        --nati-blue:   #2E86AB;
        --nati-amber:  #F18F01;
        --nati-green:  #06A77D;
    }

    /* ---------- Header banner ---------- */
    .nati-header {
        background: linear-gradient(135deg, #1A1A2E 0%, #16213E 60%, #0F3460 100%);
        padding: 1.5rem 2rem;
        border-radius: 12px;
        margin-bottom: 1.5rem;
        color: white;
    }
    .nati-header h1 { margin: 0; font-size: 1.8rem; font-weight: 700; }
    .nati-header p  { margin: 0.25rem 0 0; opacity: 0.75; font-size: 0.9rem; }

    /* ---------- Metric cards ---------- */
    .metric-card {
        background-color: var(--secondary-background-color);
        border-radius: 10px;
        padding: 1rem 1.2rem;
        border-left: 4px solid var(--nati-blue);
        margin-bottom: 1rem;
    }
    .metric-card .label { font-size: 0.75rem; color: #888; text-transform: uppercase; font-weight: 600; }
    .metric-card .value { font-size: 1.5rem; font-weight: 700; color: var(--text-color); }
    .metric-card .delta { font-size: 0.8rem; margin-top: 2px; }
    .delta-pos  { color: #06A77D; }
    .delta-neg  { color: #E63946; }
    .delta-neut { color: #888; }

    /* ---------- Status badge ---------- */
    .status-badge {
        display: inline-block;
        padding: 0.25rem 0.75rem;
        border-radius: 20px;
        font-size: 0.8rem;
        font-weight: 600;
    }
    .status-open   { background: #d4edda; color: #155724; }
    .status-closed { background: #f8d7da; color: #721c24; }

    /* ---------- Section headers ---------- */
    .section-title {
        font-size: 1rem;
        font-weight: 700;
        color: var(--text-color);
        border-bottom: 2px solid var(--nati-blue);
        padding-bottom: 0.3rem;
        margin-bottom: 1rem;
    }

    /* ---------- Tier badges in table ---------- */
    .tier-Large { background:#2E86AB22; color:#2E86AB; border-radius:4px; padding:2px 6px; font-size:0.75rem; font-weight:600; }
    .tier-Mid   { background:#F18F0122; color:#c17000; border-radius:4px; padding:2px 6px; font-size:0.75rem; font-weight:600; }
    .tier-Small { background:#06A77D22; color:#048059; border-radius:4px; padding:2px 6px; font-size:0.75rem; font-weight:600; }

    /* Hide Streamlit default elements */
    #MainMenu { visibility: hidden; }
    footer    { visibility: hidden; }
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# Auto-Refresh (market-hours aware)
# ─────────────────────────────────────────────────────────────────────────────
_refresh_interval = (
    REFRESH_INTERVAL_MARKET_HOURS_SEC * 1000 if is_market_open()
    else REFRESH_INTERVAL_OFF_HOURS_SEC * 1000
)
st_autorefresh(interval=_refresh_interval, key="nati_autorefresh")


# ─────────────────────────────────────────────────────────────────────────────
# Session-state Caching
# ─────────────────────────────────────────────────────────────────────────────
def _init_state():
    defaults = {
        "provider":         None,
        "market_data":      None,
        "weights_df":       None,
        "performance_df":   None,
        "tier_perf":        None,
        "nifty_df":         None,
        "metrics":          None,
        "live_quotes":      None,
        "last_full_fetch":  None,
        "last_live_fetch":  None,
        "fetch_error":      None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

_init_state()


# ─────────────────────────────────────────────────────────────────────────────
# Data Loading
# ─────────────────────────────────────────────────────────────────────────────

@st.cache_resource(show_spinner=False)
def get_provider() -> DataProvider:
    return DataProvider()


def _needs_full_refresh() -> bool:
    if st.session_state.last_full_fetch is None:
        return True
    elapsed = (datetime.now(IST) - st.session_state.last_full_fetch).total_seconds()
    # Refresh history once per session start, then each time market opens
    return elapsed > 3600


def load_all_data(lookback_days: int = 365):
    provider = get_provider()
    end      = datetime.now(IST)
    start    = end - timedelta(days=lookback_days)

    with st.spinner("Fetching market data…"):
        try:
            market_data = provider.fetch_history(
                start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")
            )
            weights_df     = index_engine.calculate_weights(market_data)
            performance_df = index_engine.calculate_performance(
                market_data, weights_df,
                start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"),
            )
            tier_perf      = index_engine.calculate_tier_performance(
                market_data, weights_df,
                start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"),
            )

            # NIFTY 50 for comparison
            nifty_raw = yf.download(NIFTY_TICKER, start=start.strftime("%Y-%m-%d"),
                                    end=end.strftime("%Y-%m-%d"), progress=False)
            if isinstance(nifty_raw.columns, pd.MultiIndex):
                nifty_raw.columns = nifty_raw.columns.get_level_values(0)
            nifty_close = nifty_raw["Close"].dropna()

            nifty_ret_series = nifty_close.pct_change().dropna()
            nifty_ret_series.index = nifty_ret_series.index.tz_localize(None)

            metrics = index_engine.calculate_metrics(performance_df, weights_df, nifty_ret_series)

            st.session_state.update({
                "provider":        provider,
                "market_data":     market_data,
                "weights_df":      weights_df,
                "performance_df":  performance_df,
                "tier_perf":       tier_perf,
                "nifty_df":        pd.DataFrame({"date": nifty_close.index, "close": nifty_close.values}),
                "metrics":         metrics,
                "last_full_fetch": datetime.now(IST),
                "fetch_error":     None,
            })

            csv_logger.save_constituent_snapshot(weights_df)

        except Exception as exc:
            st.session_state["fetch_error"] = str(exc)
            logger.exception("Data load failed")


def refresh_live_quotes():
    provider = get_provider()
    try:
        quotes = provider.fetch_current_quotes()
        st.session_state["live_quotes"]     = quotes
        st.session_state["last_live_fetch"] = datetime.now(IST)
    except Exception as exc:
        logger.warning("Live quote refresh failed: %s", exc)


# ─────────────────────────────────────────────────────────────────────────────
# Chart Builders
# ─────────────────────────────────────────────────────────────────────────────

def _build_index_chart(
    performance_df: pd.DataFrame,
    nifty_df: pd.DataFrame,
    tier_perf: dict,
    view_mode: str,
    show_tier_subindex: bool,
) -> go.Figure:
    """Build the main interactive line chart."""

    dates      = pd.to_datetime(performance_df["date"])
    idx_levels = performance_df["index_level"].values

    # ── Normalise NIFTY to same date range ──
    nifty_dates  = pd.to_datetime(nifty_df["date"])
    nifty_prices = nifty_df["close"].values

    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        row_heights=[0.7, 0.3],
        vertical_spacing=0.04,
        subplot_titles=["", "Daily Return (%)"],
    )

    if view_mode == "Index Level (Base 1,000)":
        # ── Top panel: NATI absolute level ──
        fig.add_trace(go.Scatter(
            x=dates, y=idx_levels,
            name="NATI", line=dict(color="#2E86AB", width=2.5),
            hovertemplate="<b>NATI</b><br>%{x|%d %b %Y}<br>Level: %{y:,.2f}<extra></extra>",
        ), row=1, col=1)

        # NIFTY scaled to 1000 base on same y-axis for alignment
        nifty_aligned = pd.Series(nifty_prices, index=nifty_dates)
        nifty_aligned = nifty_aligned.reindex(dates, method="ffill").values
        nifty_scaled  = nifty_aligned / nifty_aligned[~np.isnan(nifty_aligned)][0] * BASE_INDEX_VALUE
        fig.add_trace(go.Scatter(
            x=dates, y=nifty_scaled,
            name="NIFTY 50 (scaled)", line=dict(color="rgba(150,150,150,0.8)", width=1.5, dash="dot"),
            hovertemplate="<b>NIFTY 50 (scaled)</b><br>%{x|%d %b %Y}<br>Level: %{y:,.2f}<extra></extra>",
        ), row=1, col=1)

        yaxis_title = "Index Level"

    else:  # % change view
        # Compute cumulative % change from day 1
        pct_change = (idx_levels / idx_levels[0] - 1) * 100

        nifty_series = pd.Series(nifty_prices, index=nifty_dates)
        nifty_series = nifty_series.reindex(dates, method="ffill").values
        with np.errstate(invalid="ignore", divide="ignore"):
            nifty_pct = (nifty_series / nifty_series[~np.isnan(nifty_series)][0] - 1) * 100

        fig.add_trace(go.Scatter(
            x=dates, y=pct_change,
            name="NATI", line=dict(color="#2E86AB", width=2.5),
            hovertemplate="<b>NATI</b><br>%{x|%d %b %Y}<br>Return: %{y:+.2f}%<extra></extra>",
        ), row=1, col=1)

        fig.add_trace(go.Scatter(
            x=dates, y=nifty_pct,
            name="NIFTY 50", line=dict(color="rgba(150,150,150,0.8)", width=1.5, dash="dot"),
            hovertemplate="<b>NIFTY 50</b><br>%{x|%d %b %Y}<br>Return: %{y:+.2f}%<extra></extra>",
        ), row=1, col=1)

        fig.add_hline(y=0, line_color="rgba(128,128,128,0.3)", line_dash="solid", row=1, col=1)
        yaxis_title = "Cumulative Return (%)"

    # ── Optional Tier sub-indices ──
    if show_tier_subindex and tier_perf:
        for tier, tdf in tier_perf.items():
            t_dates  = pd.to_datetime(tdf["date"])
            t_levels = tdf["level"].values
            if view_mode == "% Change vs NIFTY 50":
                t_values = (t_levels / t_levels[0] - 1) * 100
            else:
                t_values = t_levels
            fig.add_trace(go.Scatter(
                x=t_dates, y=t_values,
                name=f"{tier} Sub-Index",
                line=dict(color=TIER_COLORS[tier], width=1.2, dash="longdash"),
                opacity=0.6,
                hovertemplate=f"<b>{tier}</b><br>%{{x|%d %b %Y}}<br>%{{y:,.2f}}<extra></extra>",
            ), row=1, col=1)

    # ── Bottom panel: daily returns bar ──
    daily_pct = performance_df["daily_return"].values * 100
    bar_colors = ["#06A77D" if r >= 0 else "#E63946" for r in daily_pct]
    fig.add_trace(go.Bar(
        x=dates, y=daily_pct,
        name="Daily Return",
        marker_color=bar_colors,
        hovertemplate="%{x|%d %b %Y}<br>Daily: %{y:+.2f}%<extra></extra>",
        showlegend=False,
    ), row=2, col=1)

    # ── Layout ──
    fig.update_layout(
        height=520,
        font=dict(family="Inter, sans-serif", size=12),
        legend=dict(
            orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1,
            borderwidth=0,
        ),
        hovermode="x unified",
        margin=dict(l=10, r=10, t=30, b=10),
    )
    fig.update_yaxes(title_text=yaxis_title,          row=1, col=1, showgrid=True, gridcolor="rgba(128,128,128,0.2)")
    fig.update_yaxes(title_text="Daily Ret %", showgrid=False, row=2, col=1)
    fig.update_xaxes(showgrid=False, row=2, col=1)
    fig.update_xaxes(
        rangeselector=dict(
            buttons=[
                dict(count=1,  label="1M",  step="month", stepmode="backward"),
                dict(count=3,  label="3M",  step="month", stepmode="backward"),
                dict(count=6,  label="6M",  step="month", stepmode="backward"),
                dict(count=1,  label="YTD", step="year",  stepmode="todate"),
                dict(count=1,  label="1Y",  step="year",  stepmode="backward"),
                dict(step="all", label="All"),
            ],
        ),
        row=1, col=1,
    )
    return fig


def _build_drawdown_chart(performance_df: pd.DataFrame) -> go.Figure:
    returns    = performance_df["daily_return"]
    cumulative = (1 + returns).cumprod()
    drawdown   = (cumulative - cumulative.cummax()) / cumulative.cummax() * 100
    dates      = pd.to_datetime(performance_df["date"])

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=dates, y=drawdown.values,
        fill="tozeroy", fillcolor="rgba(230,57,70,0.15)",
        line=dict(color="#E63946", width=1.5),
        name="Drawdown",
        hovertemplate="%{x|%d %b %Y}<br>DD: %{y:.2f}%<extra></extra>",
    ))
    fig.update_layout(
        height=200,
        margin=dict(l=10, r=10, t=10, b=10),
        showlegend=False,
        hovermode="x unified",
        yaxis=dict(title="Drawdown (%)", showgrid=True, gridcolor="rgba(128,128,128,0.2)"),
        xaxis=dict(showgrid=False),
    )
    return fig


def _build_rolling_vol_chart(performance_df: pd.DataFrame) -> go.Figure:
    returns    = performance_df["daily_return"]
    rolling_v  = returns.rolling(30).std() * np.sqrt(252) * 100
    dates      = pd.to_datetime(performance_df["date"])

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=dates, y=rolling_v.values,
        line=dict(color="#F18F01", width=1.8),
        fill="tozeroy", fillcolor="rgba(241,143,1,0.12)",
        name="30D Rolling Vol",
        hovertemplate="%{x|%d %b %Y}<br>Vol: %{y:.2f}%<extra></extra>",
    ))
    fig.update_layout(
        height=200,
        margin=dict(l=10, r=10, t=10, b=10),
        showlegend=False,
        hovermode="x unified",
        yaxis=dict(title="Ann. Vol (%)", showgrid=True, gridcolor="rgba(128,128,128,0.2)"),
        xaxis=dict(showgrid=False),
    )
    return fig


# ─────────────────────────────────────────────────────────────────────────────
# Metric Card Helper
# ─────────────────────────────────────────────────────────────────────────────

def metric_card(label: str, value: str, delta: str = "", delta_good: bool = True):
    if delta:
        delta_class = "delta-pos" if delta_good else "delta-neg"
        delta_html  = f'<div class="delta {delta_class}">{delta}</div>'
    else:
        delta_html = ""
    st.markdown(f"""
    <div class="metric-card">
        <div class="label">{label}</div>
        <div class="value">{value}</div>
        {delta_html}
    </div>
    """, unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# Sidebar
# ─────────────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("### ⚙️ Controls")

    lookback = st.selectbox(
        "Lookback Period",
        options=[90, 180, 365, 730],
        index=2,
        format_func=lambda x: f"{x // 365}Y" if x >= 365 else f"{x // 30}M",
    )

    view_mode = st.radio(
        "Chart View",
        options=["Index Level (Base 1,000)", "% Change vs NIFTY 50"],
    )

    show_tier = st.checkbox("Show Tier Sub-Indices", value=False)

    st.markdown("---")
    st.markdown("### 🔄 Data")
    provider_label = get_provider().data_source_label
    st.info(f"Source: **{provider_label}**")

    if st.button("🔃 Force Refresh", use_container_width=True):
        st.session_state["last_full_fetch"] = None
        st.rerun()

    st.markdown("---")
    st.markdown("### 💾 CSV Export")
    eod_clicked = st.button("Export EOD CSV Now", use_container_width=True)


# ─────────────────────────────────────────────────────────────────────────────
# Load Data
# ─────────────────────────────────────────────────────────────────────────────

if _needs_full_refresh():
    load_all_data(lookback_days=lookback)

if is_market_open():
    refresh_live_quotes()

# ─────────────────────────────────────────────────────────────────────────────
# EOD / Hourly auto-export
# ─────────────────────────────────────────────────────────────────────────────
if st.session_state.weights_df is not None and st.session_state.performance_df is not None:
    # Hourly intraday snapshot
    if is_market_open():
        last_snap = st.session_state.get("last_csv_snapshot")
        now_ist   = datetime.now(IST)
        if last_snap is None or (now_ist - last_snap).total_seconds() >= 3600:
            lvl = float(st.session_state.performance_df["index_level"].iloc[-1])
            ret = float(st.session_state.performance_df["daily_return"].iloc[-1] * 100)
            csv_logger.log_index_snapshot(
                lvl, ret, len(st.session_state.weights_df), note="hourly"
            )
            st.session_state["last_csv_snapshot"] = now_ist

    # EOD guard
    csv_logger.maybe_run_eod_export(
        st.session_state.weights_df,
        st.session_state.performance_df,
        st.session_state.metrics or {},
    )

# ─────────────────────────────────────────────────────────────────────────────
# Manual Buttons
# ─────────────────────────────────────────────────────────────────────────────
if eod_clicked and st.session_state.weights_df is not None:
    path = csv_logger.export_eod(
        st.session_state.weights_df,
        st.session_state.performance_df,
        st.session_state.metrics or {},
    )
    st.sidebar.success(f"Exported: {os.path.basename(path)}")

# ─────────────────────────────────────────────────────────────────────────────
# Error guard
# ─────────────────────────────────────────────────────────────────────────────
if st.session_state.fetch_error:
    st.error(f"Data fetch failed: {st.session_state.fetch_error}")
    st.stop()

if st.session_state.weights_df is None:
    st.info("Loading data…")
    st.stop()

weights_df     = st.session_state.weights_df
performance_df = st.session_state.performance_df
nifty_df       = st.session_state.nifty_df
tier_perf      = st.session_state.tier_perf
metrics        = st.session_state.metrics or {}
live_quotes    = st.session_state.live_quotes

current_level  = float(performance_df["index_level"].iloc[-1])
start_level    = float(performance_df["index_level"].iloc[0])
total_return   = (current_level / start_level - 1) * 100
daily_ret      = float(performance_df["daily_return"].iloc[-1] * 100)
last_updated   = datetime.now(IST).strftime("%d %b %Y, %H:%M IST")

# ─────────────────────────────────────────────────────────────────────────────
# Header Banner
# ─────────────────────────────────────────────────────────────────────────────
status_html = market_status_label()
st.markdown(f"""
<div class="nati-header">
    <h1>📈 New Age Tech Index <span style="font-size:1rem; opacity:0.6; font-weight:400">(NATI)</span></h1>
    <p>Tracking India's listed startup ecosystem · v2.0 Tiered Methodology · Updated {last_updated}</p>
    <p>{status_html}</p>
</div>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# Top KPI Row
# ─────────────────────────────────────────────────────────────────────────────
k1, k2, k3, k4, k5, k6 = st.columns(6)

with k1:
    metric_card("NATI Level", f"{current_level:,.2f}",
                delta=f"{daily_ret:+.2f}% today", delta_good=(daily_ret >= 0))
with k2:
    pe = metrics.get("Weighted P/E", "—")
    metric_card("Weighted P/E", str(pe) if pe else "—")
with k3:
    vol = metrics.get("Annualized Vol (σ)", "—")
    metric_card("Index Volatility", str(vol))
with k4:
    mcap = metrics.get("Combined Mcap (₹ Cr)")
    metric_card("Combined Mcap", str(mcap) if mcap else "—")
with k5:
    metric_card("Sharpe Ratio", metrics.get("Sharpe Ratio", "—"))
with k6:
    metric_card("Max Drawdown", metrics.get("Max Drawdown", "—"),
                delta="vs peak", delta_good=False)

st.markdown("---")

# ─────────────────────────────────────────────────────────────────────────────
# Main Chart
# ─────────────────────────────────────────────────────────────────────────────
st.markdown('<div class="section-title">📊 Index Performance</div>', unsafe_allow_html=True)

fig_main = _build_index_chart(performance_df, nifty_df, tier_perf, view_mode, show_tier)
st.plotly_chart(fig_main, use_container_width=True)

# ─────────────────────────────────────────────────────────────────────────────
# Risk Charts Row
# ─────────────────────────────────────────────────────────────────────────────
rc1, rc2 = st.columns(2)
with rc1:
    st.markdown('<div class="section-title">📉 Drawdown</div>', unsafe_allow_html=True)
    st.plotly_chart(_build_drawdown_chart(performance_df), use_container_width=True)
with rc2:
    st.markdown('<div class="section-title">📊 30-Day Rolling Volatility</div>', unsafe_allow_html=True)
    st.plotly_chart(_build_rolling_vol_chart(performance_df), use_container_width=True)

st.markdown("---")

# ─────────────────────────────────────────────────────────────────────────────
# Gainers / Losers
# ─────────────────────────────────────────────────────────────────────────────
gl1, gl2 = st.columns(2)

def _render_movers(items: list[dict], header: str, is_gainer: bool):
    color = "#06A77D" if is_gainer else "#E63946"
    arrow = "▲" if is_gainer else "▼"
    rows  = ""
    for item in items:
        pct = item.get("daily_return_pct", 0)
        rows += f"""
        <tr>
            <td style="padding:6px 8px;">{item['company']}</td>
            <td style="color:#888; font-size:0.8rem; padding:6px 4px;">{item['ticker']}</td>
            <td style="color:{color}; font-weight:700; text-align:right; padding:6px 8px;">
                {arrow} {abs(pct):.2f}%
            </td>
        </tr>"""
    st.markdown(f"""
    <div class="section-title">{header}</div>
    <table style="width:100%; border-collapse:collapse; font-size:0.9rem;">
        {rows}
    </table>
    """, unsafe_allow_html=True)


with gl1:
    gainers = metrics.get("Top 5 Gainers", [])
    if gainers:
        _render_movers(gainers, "🚀 Top Gainers", True)

with gl2:
    losers = metrics.get("Top 5 Losers", [])
    if losers:
        _render_movers(losers, "📉 Top Losers", False)

st.markdown("---")

# ─────────────────────────────────────────────────────────────────────────────
# Constituent Performance Table
# ─────────────────────────────────────────────────────────────────────────────
st.markdown('<div class="section-title">📋 Constituent Performance</div>', unsafe_allow_html=True)

# Filters
f1, f2, f3 = st.columns([2, 2, 3])
with f1:
    tier_filter = st.multiselect("Tier", options=TIER_ORDER, default=TIER_ORDER)
with f2:
    sort_col = st.selectbox("Sort by", ["Index Weight %", "CMP (₹)", "Daily Chg %", "Market Cap (₹ Cr)"])
with f3:
    search_q = st.text_input("Search company / ticker", placeholder="e.g. Zomato or ETERNAL")

display_df = index_engine.build_constituent_table(weights_df, live_quotes)

# Apply filters
display_df = display_df[display_df["Tier"].isin(tier_filter)]
if search_q:
    q = search_q.lower()
    display_df = display_df[
        display_df["Company"].str.lower().str.contains(q) |
        display_df["Ticker"].str.lower().str.contains(q)
    ]
display_df = display_df.sort_values(sort_col, ascending=sort_col not in ["Index Weight %", "Market Cap (₹ Cr)"])


def _color_daily(val):
    """Streamlit style function: red/green for daily change."""
    try:
        v = float(val)
        return "color: #06A77D; font-weight:600" if v >= 0 else "color: #E63946; font-weight:600"
    except Exception:
        return ""


styled = (
    display_df.style
    .map(_color_daily, subset=["Daily Chg %"])
    .format({
        "CMP (₹)":       "{:,.2f}",
        "Daily Chg %":   "{:+.2f}%",
        "Index Weight %":"{:.2f}%",
        "P/E":           lambda x: f"{x:.1f}" if pd.notna(x) else "—",
    })
    .set_properties(**{"font-size": "0.85rem"})
)

st.dataframe(styled, use_container_width=True, height=460)

# ─────────────────────────────────────────────────────────────────────────────
# Full Metrics Panel
# ─────────────────────────────────────────────────────────────────────────────
with st.expander("📐 Full Index Metrics"):
    m1, m2, m3 = st.columns(3)
    metric_keys = [
        ("Total Return", m1), ("Annualized Return", m1), ("Win Rate", m1),
        ("Annualized Vol (σ)", m2), ("Max Drawdown", m2), ("Beta (vs NIFTY 50)", m2),
        ("Sharpe Ratio", m3), ("Sortino Ratio", m3), ("Trading Days", m3),
    ]
    for key, col in metric_keys:
        val = metrics.get(key, "—")
        col.metric(key, str(val) if val is not None else "—")

# ─────────────────────────────────────────────────────────────────────────────
# Footer
# ─────────────────────────────────────────────────────────────────────────────
st.markdown(f"""
<div style="text-align:center; color:#aaa; font-size:0.75rem; margin-top:2rem; padding-top:1rem;
            border-top:1px solid #eee;">
    New Age Tech Index v2.0 · Tiered Methodology · Data: {get_provider().data_source_label}
    · Auto-refreshes every {'5 min' if is_market_open() else '60 min'}
    · Last updated: {last_updated}
</div>
""", unsafe_allow_html=True)
