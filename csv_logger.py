"""
csv_logger.py — Automated CSV export and historical audit trail.

Two export modes
────────────────
1. Hourly snapshot  : Written during market hours every N minutes.
                      File: data/index_levels.csv  (append mode, one row per call)

2. End-of-day (EOD) : Written once at 15:35 IST (5 min after close).
                      File: data/eod_YYYYMMDD.csv  (full constituent detail)

Both files are safe to open in Excel while the app is running — they are
written atomically via a temp-file rename to avoid partial reads.
"""

from __future__ import annotations

import logging
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

from config import (
    CSV_CONSTITUENTS, CSV_EOD_PREFIX, CSV_INDEX_LEVELS, DATA_DIR, IST,
)

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _ensure_data_dir() -> None:
    Path(DATA_DIR).mkdir(parents=True, exist_ok=True)


def _atomic_append(path: str, new_row: pd.DataFrame) -> None:
    """Append a single-row DataFrame to CSV atomically."""
    _ensure_data_dir()
    if os.path.exists(path):
        existing = pd.read_csv(path)
        combined = pd.concat([existing, new_row], ignore_index=True)
    else:
        combined = new_row
    _atomic_write(path, combined)


def _atomic_write(path: str, df: pd.DataFrame) -> None:
    """Write DataFrame to CSV via a temp file to prevent partial writes."""
    _ensure_data_dir()
    dir_name  = os.path.dirname(path) or "."
    fd, tmp   = tempfile.mkstemp(dir=dir_name, suffix=".tmp")
    try:
        os.close(fd)
        df.to_csv(tmp, index=False)
        os.replace(tmp, path)   # atomic on POSIX; best-effort on Windows
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


# ─────────────────────────────────────────────────────────────────────────────
# Hourly Index-Level Snapshot
# ─────────────────────────────────────────────────────────────────────────────

def log_index_snapshot(
    index_level: float,
    daily_return_pct: float,
    total_constituents: int,
    data_source: str = "yfinance",
    note: str = "",
) -> None:
    """
    Append a single row to data/index_levels.csv.

    Schema:
        timestamp_ist | index_level | daily_return_pct | constituents | data_source | note
    """
    now = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
    row = pd.DataFrame([{
        "timestamp_ist":    now,
        "index_level":      round(index_level, 4),
        "daily_return_pct": round(daily_return_pct, 4),
        "constituents":     total_constituents,
        "data_source":      data_source,
        "note":             note,
    }])
    _atomic_append(CSV_INDEX_LEVELS, row)
    logger.info("Logged index snapshot: level=%.2f  return=%.3f%%", index_level, daily_return_pct)


# ─────────────────────────────────────────────────────────────────────────────
# EOD Full Constituent Export
# ─────────────────────────────────────────────────────────────────────────────

def export_eod(
    weights_df: pd.DataFrame,
    performance_df: pd.DataFrame,
    metrics: dict,
) -> str:
    """
    Write the end-of-day export CSV.

    Returns the file path written.

    Schema of the main sheet (per constituent):
        date | company | ticker | tier | price | daily_return_pct |
        full_mc_cr | free_float_mc | weight_final | pe | adtv_cr

    A header block with summary metrics is prepended as commented lines.
    """
    today     = datetime.now(IST).strftime("%Y%m%d")
    eod_path  = f"{CSV_EOD_PREFIX}_{today}.csv"

    _ensure_data_dir()

    # ── Build constituent block ──
    eod_df = weights_df.copy()
    eod_df.insert(0, "date", datetime.now(IST).strftime("%Y-%m-%d"))

    # ── Build metrics header ──
    metric_lines: list[str] = [
        f"# New Age Tech Index — EOD Export {today}",
        f"# Generated: {datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S IST')}",
        "#",
    ]
    skip_keys = {"Top 5 Gainers", "Top 5 Losers"}
    for k, v in metrics.items():
        if k not in skip_keys:
            metric_lines.append(f"# {k}: {v}")
    metric_lines.append("#")
    metric_lines.append("# Index end level: " + str(round(performance_df["index_level"].iloc[-1], 4)))
    metric_lines.append("#")

    with open(eod_path, "w") as f:
        f.write("\n".join(metric_lines) + "\n")

    eod_df.to_csv(eod_path, index=False, mode="a")

    logger.info("EOD export written: %s  (%d rows)", eod_path, len(eod_df))
    return eod_path


# ─────────────────────────────────────────────────────────────────────────────
# Constituent Snapshot (for real-time display caching)
# ─────────────────────────────────────────────────────────────────────────────

def save_constituent_snapshot(weights_df: pd.DataFrame) -> None:
    """Overwrite data/constituent_snapshot.csv with current weights."""
    _atomic_write(CSV_CONSTITUENTS, weights_df)
    logger.debug("Constituent snapshot saved: %d rows", len(weights_df))


def load_constituent_snapshot() -> Optional[pd.DataFrame]:
    """Load last saved constituent snapshot, or None if not available."""
    if not os.path.exists(CSV_CONSTITUENTS):
        return None
    try:
        return pd.read_csv(CSV_CONSTITUENTS)
    except Exception as exc:
        logger.warning("Could not load constituent snapshot: %s", exc)
        return None


def load_index_history() -> Optional[pd.DataFrame]:
    """Load accumulated index-level history from CSV."""
    if not os.path.exists(CSV_INDEX_LEVELS):
        return None
    try:
        df = pd.read_csv(CSV_INDEX_LEVELS, parse_dates=["timestamp_ist"])
        return df.sort_values("timestamp_ist")
    except Exception as exc:
        logger.warning("Could not load index history: %s", exc)
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Scheduled EOD Guard (call once per event loop tick — cheap no-op otherwise)
# ─────────────────────────────────────────────────────────────────────────────

_eod_exported_dates: set[str] = set()


def maybe_run_eod_export(
    weights_df: pd.DataFrame,
    performance_df: pd.DataFrame,
    metrics: dict,
) -> bool:
    """
    Export EOD data once per calendar day, at/after 15:35 IST.
    Returns True if export was triggered this call.
    """
    from config import EOD_EXPORT_TIME_HH, EOD_EXPORT_TIME_MM
    now   = datetime.now(IST)
    today = now.strftime("%Y%m%d")

    if today in _eod_exported_dates:
        return False

    eod_time = now.replace(hour=EOD_EXPORT_TIME_HH, minute=EOD_EXPORT_TIME_MM, second=0)
    if now >= eod_time:
        try:
            export_eod(weights_df, performance_df, metrics)
            log_index_snapshot(
                index_level=performance_df["index_level"].iloc[-1],
                daily_return_pct=float(performance_df["daily_return"].iloc[-1] * 100),
                total_constituents=len(weights_df),
                note="EOD",
            )
            _eod_exported_dates.add(today)
            return True
        except Exception as exc:
            logger.error("EOD export failed: %s", exc)
    return False
