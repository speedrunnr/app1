"""
config.py — Central configuration for the New Age Tech Index system.
Edit this file to update tickers, API keys, and index parameters.
"""

from __future__ import annotations
import os
from zoneinfo import ZoneInfo

# ─────────────────────────────────────────────────────────────────────────────
# TIMEZONE
# ─────────────────────────────────────────────────────────────────────────────
IST = ZoneInfo("Asia/Kolkata")

# ─────────────────────────────────────────────────────────────────────────────
# MARKET HOURS (NSE/BSE)
# ─────────────────────────────────────────────────────────────────────────────
MARKET_OPEN_HH  = 9
MARKET_OPEN_MM  = 15
MARKET_CLOSE_HH = 15
MARKET_CLOSE_MM = 30

# ─────────────────────────────────────────────────────────────────────────────
# INDEX PARAMETERS
# ─────────────────────────────────────────────────────────────────────────────
BASE_INDEX_VALUE  = 1_000.0   # Index starts at 1,000
MIN_MARKET_CAP_CR = 1_000.0   # Minimum full market-cap (₹ Crore) to qualify
MIN_ADTV_CRORES   = 5.0       # Minimum Average Daily Traded Value (₹ Crore)
NIFTY_TICKER      = "^NSEI"

TIER_CONFIG = {
    "Large": {"min_mc_cr": 50_000,  "max_mc_cr": float("inf"), "allocation": 0.50},
    "Mid":   {"min_mc_cr": 10_000,  "max_mc_cr": 50_000,       "allocation": 0.35},
    "Small": {"min_mc_cr":  1_000,  "max_mc_cr": 10_000,       "allocation": 0.15},
}
TIER_ORDER  = ["Large", "Mid", "Small"]
TIER_COLORS = {"Large": "#2E86AB", "Mid": "#F18F01", "Small": "#06A77D"}

# ─────────────────────────────────────────────────────────────────────────────
# CONSTITUENT UNIVERSE  (47 companies)
# ─────────────────────────────────────────────────────────────────────────────
CONSTITUENT_UNIVERSE: dict[str, dict] = {
    "Eternal (Zomato)":         {"ticker": "ETERNAL.NS",    "free_float_factor": 0.85},
    "Groww":                    {"ticker": "GROWW.NS",       "free_float_factor": 0.50},
    "Swiggy":                   {"ticker": "SWIGGY.NS",      "free_float_factor": 0.50},
    "Lenskart":                 {"ticker": "LENSKART.NS",    "free_float_factor": 0.50},
    "Nykaa":                    {"ticker": "NYKAA.NS",       "free_float_factor": 0.48},
    "Info Edge":                {"ticker": "NAUKRI.NS",      "free_float_factor": 0.62},
    "Paytm":                    {"ticker": "PAYTM.NS",       "free_float_factor": 1.00},
    "PB Fintech":               {"ticker": "POLICYBZR.NS",  "free_float_factor": 0.95},
    "Meesho":                   {"ticker": "MEESHO.NS",      "free_float_factor": 0.50},
    "Delhivery":                {"ticker": "DELHIVERY.NS",   "free_float_factor": 0.80},
    "Physics Wallah":           {"ticker": "PWL.NS",         "free_float_factor": 0.50},
    "Digit Insurance":          {"ticker": "GODIGIT.NS",     "free_float_factor": 0.25},
    "Ather Energy":             {"ticker": "ATHERENERG.NS",  "free_float_factor": 0.50},
    "Pine Labs":                {"ticker": "PINELABS.NS",    "free_float_factor": 0.50},
    "Urban Company":            {"ticker": "URBANCO.NS",     "free_float_factor": 0.50},
    "TBO Tek":                  {"ticker": "TBOTEK.NS",      "free_float_factor": 0.20},
    "IndiaMart":                {"ticker": "INDIAMART.NS",   "free_float_factor": 0.45},
    "FirstCry":                 {"ticker": "FIRSTCRY.NS",    "free_float_factor": 0.30},
    "Ola Electric":             {"ticker": "OLAELEC.NS",     "free_float_factor": 0.20},
    "Blackbuck":                {"ticker": "BLACKBUCK.NS",   "free_float_factor": 0.25},
    "Nazara Tech":              {"ticker": "NAZARA.NS",      "free_float_factor": 0.70},
    "Honasa (Mamaearth)":       {"ticker": "HONASA.NS",      "free_float_factor": 0.65},
    "Aequs":                    {"ticker": "AEQUS.NS",       "free_float_factor": 0.50},
    "CarTrade":                 {"ticker": "CARTRADE.NS",    "free_float_factor": 0.55},
    "ixigo":                    {"ticker": "IXIGO.NS",       "free_float_factor": 0.40},
    "Amagi Media Labs":         {"ticker": "AMAGI.NS",       "free_float_factor": 0.50},
    "WeWork India":             {"ticker": "WEWORK.NS",      "free_float_factor": 0.50},
    "Shadowfax":                {"ticker": "SHADOWFAX.NS",   "free_float_factor": 0.50},
    "Wakefit":                  {"ticker": "WAKEFIT.NS",     "free_float_factor": 0.50},
    "MapmyIndia":               {"ticker": "MAPMYINDIA.NS",  "free_float_factor": 0.47},
    "Bluestone":                {"ticker": "BLUESTONE.NS",   "free_float_factor": 0.50},
    "Avenues AI":               {"ticker": "CCAVENUE.NS",    "free_float_factor": 0.70},
    "Rategain":                 {"ticker": "RATEGAIN.NS",    "free_float_factor": 0.45},
    "Justdial":                 {"ticker": "JUSTDIAL.NS",    "free_float_factor": 0.25},
    "Smartworks":               {"ticker": "SMARTWORKS.NS",  "free_float_factor": 0.50},
    "E2E Networks":             {"ticker": "E2E.NS",         "free_float_factor": 0.35},
    "Capillary Technologies":   {"ticker": "CAPILLARY.NS",   "free_float_factor": 0.50},
    "Zaggle":                   {"ticker": "ZAGGLE.NS",      "free_float_factor": 0.30},
    "Indiqube Spaces":          {"ticker": "INDIQUBE.NS",    "free_float_factor": 0.50},
    "Yatra":                    {"ticker": "YATRA.NS",       "free_float_factor": 0.40},
    "Easemytrip":               {"ticker": "EASEMYTRIP.NS",  "free_float_factor": 0.28},
    "Awfis":                    {"ticker": "AWFIS.NS",       "free_float_factor": 0.30},
    "FINO Payment Bank":        {"ticker": "FINOPB.NS",      "free_float_factor": 0.75},
    "Ideaforge":                {"ticker": "IDEAFORGE.NS",   "free_float_factor": 0.30},
    "Mobikwik":                 {"ticker": "MOBIKWIK.NS",    "free_float_factor": 0.30},
    "Unicommerce":              {"ticker": "UNIECOM.NS",     "free_float_factor": 0.25},
    "Matrimony":                {"ticker": "MATRIMONY.NS",   "free_float_factor": 0.48},
}

# ─────────────────────────────────────────────────────────────────────────────
# REFRESH INTERVALS
# ─────────────────────────────────────────────────────────────────────────────
REFRESH_INTERVAL_MARKET_HOURS_SEC  = 300   # 5 min during market hours
REFRESH_INTERVAL_OFF_HOURS_SEC     = 3600  # 1 hour off-market
CSV_HOURLY_EXPORT_INTERVAL_MIN     = 60    # hourly CSV during market hours
EOD_EXPORT_TIME_HH                 = 15    # 3:30 PM EOD export
EOD_EXPORT_TIME_MM                 = 35

# ─────────────────────────────────────────────────────────────────────────────
# CSV / FILE PATHS
# ─────────────────────────────────────────────────────────────────────────────
DATA_DIR           = os.path.join(os.path.dirname(__file__), "data")
CSV_INDEX_LEVELS   = os.path.join(DATA_DIR, "index_levels.csv")
CSV_CONSTITUENTS   = os.path.join(DATA_DIR, "constituent_snapshot.csv")
CSV_EOD_PREFIX     = os.path.join(DATA_DIR, "eod")           # eod_YYYYMMDD.csv

# ─────────────────────────────────────────────────────────────────────────────
# BROKER API FALLBACK  (optional — currently a placeholder)
# Set BROKER_PROVIDER to "kite" | "dhan" | "shoonya" to enable real-time feed
# ─────────────────────────────────────────────────────────────────────────────
BROKER_PROVIDER   = os.getenv("BROKER_PROVIDER", "yfinance")   # default to yfinance
KITE_API_KEY      = os.getenv("KITE_API_KEY", "")
KITE_ACCESS_TOKEN = os.getenv("KITE_ACCESS_TOKEN", "")
DHAN_CLIENT_ID    = os.getenv("DHAN_CLIENT_ID", "")
DHAN_ACCESS_TOKEN = os.getenv("DHAN_ACCESS_TOKEN", "")
SHOONYA_USER_ID   = os.getenv("SHOONYA_USER_ID", "")
SHOONYA_PASSWORD  = os.getenv("SHOONYA_PASSWORD", "")
