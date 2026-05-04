"""
data_pipeline.py — Real-time & historical data fetching with market-hours
awareness and broker-API fallback.

yfinance Limitations (documented for production):
─────────────────────────────────────────────────
1. DATA LATENCY   : yfinance pulls data from Yahoo Finance, which carries a
                    ~15-minute delay for NSE/BSE quotes.
2. RATE LIMITING  : Batch downloading prices is safe. Fetching metadata (.info)
                    in a loop will result in IP bans. We now rely on config.py
                    for outstanding shares.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from typing import Optional

import numpy as np
import pandas as pd
import yfinance as yf

from config import (
    BROKER_PROVIDER, CONSTITUENT_UNIVERSE, DHAN_ACCESS_TOKEN, DHAN_CLIENT_ID,
    IST, KITE_ACCESS_TOKEN, KITE_API_KEY, MARKET_CLOSE_HH, MARKET_CLOSE_MM,
    MARKET_OPEN_HH, MARKET_OPEN_MM, MIN_ADTV_CRORES, MIN_MARKET_CAP_CR,
    SHOONYA_PASSWORD, SHOONYA_USER_ID, TIER_CONFIG, TIER_ORDER,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Market-Hours Utilities
# ─────────────────────────────────────────────────────────────────────────────

def is_market_open() -> bool:
    """Return True if the current IST time falls within NSE/BSE trading hours."""
    now = datetime.now(IST)
    if now.weekday() >= 5:          # Saturday=5, Sunday=6
        return False
    market_open  = now.replace(hour=MARKET_OPEN_HH,  minute=MARKET_OPEN_MM,  second=0, microsecond=0)
    market_close = now.replace(hour=MARKET_CLOSE_HH, minute=MARKET_CLOSE_MM, second=0, microsecond=0)
    return market_open <= now <= market_close


def seconds_to_market_open() -> int:
    """Seconds until next market open (0 if already open)."""
    if is_market_open():
        return 0
    now = datetime.now(IST)
    # Try today first, then next weekday
    for delta_days in range(7):
        candidate = (now + timedelta(days=delta_days)).replace(
            hour=MARKET_OPEN_HH, minute=MARKET_OPEN_MM, second=0, microsecond=0
        )
        if candidate > now and candidate.weekday() < 5:
            return max(0, int((candidate - now).total_seconds()))
    return 0


def market_status_label() -> str:
    """Human-readable market status string for display."""
    now = datetime.now(IST)
    if is_market_open():
        close = now.replace(hour=MARKET_CLOSE_HH, minute=MARKET_CLOSE_MM, second=0)
        mins_left = int((close - now).total_seconds() / 60)
        return f"🟢 Market Open — closes in {mins_left} min"
    if now.weekday() >= 5:
        return "🔴 Market Closed (Weekend)"
    return "🔴 Market Closed"


# ─────────────────────────────────────────────────────────────────────────────
# yfinance Fetcher  (default / free tier)
# ─────────────────────────────────────────────────────────────────────────────

class YFinanceFetcher:
    """
    Batch-downloads NSE data via yfinance.
    """

    LATENCY_NOTE = (
        "⚠️  yfinance carries a ~15-minute data delay for NSE/BSE. "
        "For true real-time quotes set BROKER_PROVIDER=kite|dhan|shoonya."
    )

    def fetch_history(
        self,
        start_date: str,
        end_date: str,
        progress: bool = False,
    ) -> dict[str, dict]:
        """
        Fetch OHLCV history for all constituents.
        """
        tickers = [info["ticker"] for info in CONSTITUENT_UNIVERSE.values()]
        logger.info("Batch-downloading %d tickers from yfinance …", len(tickers))

        # ── 1. Batch OHLCV download ──────────────────────────────────────────
        for attempt in range(3):
            try:
                raw = yf.download(
                    tickers,
                    start=start_date,
                    end=end_date,
                    group_by="ticker",
                    auto_adjust=True,
                    progress=progress,
                    threads=True,
                )
                break
            except Exception as exc:
                wait = 10 * 2 ** attempt
                logger.warning("yf.download attempt %d failed: %s — retrying in %ds", attempt + 1, exc, wait)
                time.sleep(wait)
        else:
            raise RuntimeError("yfinance batch download failed after 3 attempts.")

        # ── 2. Parse data and assign config metadata ──────────────────────────
        data: dict[str, dict] = {}
        failed: list[str] = []
        not_listed: list[str] = []

        for company, info in CONSTITUENT_UNIVERSE.items():
            ticker = info["ticker"]
            try:
                if len(tickers) == 1:
                    price_s  = raw["Close"]
                    volume_s = raw["Volume"]
                else:
                    if ticker not in raw.columns.get_level_values(0):
                        not_listed.append(f"{company} ({ticker})")
                        continue
                    price_s  = raw[ticker]["Close"]
                    volume_s = raw[ticker]["Volume"]

                price_s  = price_s.dropna()
                volume_s = volume_s.dropna()

                if price_s.empty:
                    not_listed.append(f"{company} ({ticker})")
                    continue

                # ── BYPASS YAHOO FINANCE METADATA RATE LIMITS ──
                # Read shares and PE from config.py directly. 
                # If not present in config, fall back to a default of 15 Crore shares so the UI doesn't crash.
                shares = info.get("shares", 150_000_000)
                pe     = info.get("pe", 45.0)

                data[ticker] = {
                    "company": company,
                    "price":   price_s,
                    "volume":  volume_s,
                    "shares":  shares,
                    "pe":      pe,
                    "free_float_factor": info["free_float_factor"],
                }

            except Exception as exc:
                logger.debug("Error processing %s: %s", ticker, exc)
                failed.append(f"{company} ({ticker})")

        if not_listed:
            logger.warning("Not listed / no data: %s", not_listed)
        if failed:
            logger.warning("Failed to fetch: %s", failed)

        logger.info(
            "Fetched %d/%d tickers  |  not_listed=%d  failed=%d",
            len(data), len(tickers), len(not_listed), len(failed),
        )
        return data

    def fetch_current_quotes(self) -> dict[str, float]:
        """
        Return the latest available price for each ticker.
        During market hours this will be ~15 min delayed.
        """
        tickers = [info["ticker"] for info in CONSTITUENT_UNIVERSE.values()]
        quotes: dict[str, float] = {}
        raw = yf.download(tickers, period="1d", interval="1m", progress=False, threads=True)
        for company, info in CONSTITUENT_UNIVERSE.items():
            ticker = info["ticker"]
            try:
                if len(tickers) == 1:
                    price = float(raw["Close"].dropna().iloc[-1])
                else:
                    price = float(raw[ticker]["Close"].dropna().iloc[-1])
                quotes[ticker] = price
            except Exception:
                pass
        return quotes


# ─────────────────────────────────────────────────────────────────────────────
# Broker API Fetcher  (real-time — requires credentials)
# ─────────────────────────────────────────────────────────────────────────────

class BrokerFetcher:
    """Thin adapter layer over broker APIs for true real-time (< 1 sec) quotes."""

    NSE_SYMBOL_MAP = {ticker: ticker.replace(".NS", "") for ticker in
                      [v["ticker"] for v in CONSTITUENT_UNIVERSE.values()]}

    def __init__(self, provider: str):
        self.provider = provider
        self._client  = None

    def connect(self) -> bool:
        if self.provider == "kite":
            return self._connect_kite()
        elif self.provider == "dhan":
            return self._connect_dhan()
        elif self.provider == "shoonya":
            return self._connect_shoonya()
        return False

    def _connect_kite(self) -> bool:
        try:
            from kiteconnect import KiteConnect          # type: ignore
            self._client = KiteConnect(api_key=KITE_API_KEY)
            self._client.set_access_token(KITE_ACCESS_TOKEN)
            profile = self._client.profile()
            logger.info("Kite connected: %s", profile.get("user_name"))
            return True
        except ImportError:
            logger.error("kiteconnect not installed. Run: pip install kiteconnect")
        except Exception as exc:
            logger.error("Kite connection failed: %s", exc)
        return False

    def _connect_dhan(self) -> bool:
        try:
            from dhanhq import dhanhq                   # type: ignore
            self._client = dhanhq(DHAN_CLIENT_ID, DHAN_ACCESS_TOKEN)
            logger.info("Dhan HQ connected for client %s", DHAN_CLIENT_ID)
            return True
        except ImportError:
            logger.error("dhanhq not installed. Run: pip install dhanhq")
        except Exception as exc:
            logger.error("Dhan connection failed: %s", exc)
        return False

    def _connect_shoonya(self) -> bool:
        try:
            from NorenRestApiPy.NorenApi import NorenApi  # type: ignore
            self._client = NorenApi(
                host="https://api.shoonya.com/NorenWClientTP/",
                websocket="wss://api.shoonya.com/NorenWSTP/",
            )
            ret = self._client.login(
                userid=SHOONYA_USER_ID,
                password=SHOONYA_PASSWORD,
                twoFA="",
                vendor_code="",
                api_secret="",
                imei="",
            )
            logger.info("Shoonya login: %s", ret)
            return True
        except ImportError:
            logger.error("NorenRestApiPy not installed. Run: pip install NorenRestApiPy")
        except Exception as exc:
            logger.error("Shoonya connection failed: %s", exc)
        return False

    def fetch_current_quotes(self) -> dict[str, float]:
        if self._client is None:
            raise RuntimeError("BrokerFetcher not connected. Call .connect() first.")
        if self.provider == "kite":
            return self._kite_ltp()
        elif self.provider == "dhan":
            return self._dhan_ltp()
        elif self.provider == "shoonya":
            return self._shoonya_ltp()
        raise ValueError(f"Unknown provider: {self.provider}")

    def _kite_ltp(self) -> dict[str, float]:
        nse_symbols = [f"NSE:{sym}" for sym in self.NSE_SYMBOL_MAP.values()]
        ltp_data    = self._client.ltp(nse_symbols)
        result: dict[str, float] = {}
        for yf_ticker, nse_sym in self.NSE_SYMBOL_MAP.items():
            key = f"NSE:{nse_sym}"
            if key in ltp_data:
                result[yf_ticker] = ltp_data[key]["last_price"]
        return result

    def _dhan_ltp(self) -> dict[str, float]:
        result: dict[str, float] = {}
        for yf_ticker, nse_sym in self.NSE_SYMBOL_MAP.items():
            try:
                resp = self._client.get_ltp_data(
                    security_id=nse_sym, exchange_segment="NSE_EQ",
                )
                result[yf_ticker] = float(resp["data"]["last_price"])
            except Exception as exc:
                logger.debug("Dhan LTP failed for %s: %s", nse_sym, exc)
        return result

    def _shoonya_ltp(self) -> dict[str, float]:
        result: dict[str, float] = {}
        for yf_ticker, nse_sym in self.NSE_SYMBOL_MAP.items():
            try:
                resp = self._client.get_quotes(exchange="NSE", token=nse_sym)
                result[yf_ticker] = float(resp["lp"])
            except Exception as exc:
                logger.debug("Shoonya LTP failed for %s: %s", nse_sym, exc)
        return result


# ─────────────────────────────────────────────────────────────────────────────
# Unified DataProvider (auto-selects fetcher based on config)
# ─────────────────────────────────────────────────────────────────────────────

class DataProvider:
    """
    Single entry-point for the rest of the application.
    """

    def __init__(self):
        self._yf      = YFinanceFetcher()
        self._broker: Optional[BrokerFetcher] = None
        self._use_broker = BROKER_PROVIDER not in ("yfinance", "")

        if self._use_broker:
            self._broker = BrokerFetcher(BROKER_PROVIDER)
            ok = self._broker.connect()
            if not ok:
                logger.warning(
                    "Broker %s connection failed — falling back to yfinance (15-min delay).",
                    BROKER_PROVIDER,
                )
                self._use_broker = False

    def fetch_history(self, start_date: str, end_date: str) -> dict[str, dict]:
        return self._yf.fetch_history(start_date, end_date)

    def fetch_current_quotes(self) -> dict[str, float]:
        if self._use_broker and self._broker:
            try:
                return self._broker.fetch_current_quotes()
            except Exception as exc:
                logger.warning("Broker quote fetch failed: %s — using yfinance.", exc)
        return self._yf.fetch_current_quotes()

    @property
    def data_source_label(self) -> str:
        if self._use_broker:
            return f"Real-time via {BROKER_PROVIDER.title()}"
        return "yfinance (15-min delayed)"
