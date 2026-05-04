"""
airtable_sync.py — Push index output to Airtable as a headless CMS.

Airtable Base structure (create these tables before first sync):
────────────────────────────────────────────────────────────────
Table 1: "Index Levels"
    Fields:  Name (Text), Timestamp IST, Index Level, Daily Return %,
             Total Constituents, Data Source, Notes

Table 2: "Constituents"
    Fields:  Name (Text), Ticker, Tier, CMP (₹), Daily Chg %,
             Market Cap (₹ Cr), Index Weight %, P/E, ADTV (₹ Cr), Last Updated

Table 3: "Metrics"
    Fields:  Name (Text), Value, Last Updated

Setup
─────
1. Go to https://airtable.com/create/tokens — create a Personal Access Token
   with scopes: data.records:read, data.records:write
2. Set the env vars:
       export AIRTABLE_API_KEY="patXXXXXXXXXX"
       export AIRTABLE_BASE_ID="appXXXXXXXXXX"
3. Run:  python airtable_sync.py --test
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Optional

import requests

from config import (
    AIRTABLE_API_KEY, AIRTABLE_BASE_ID,
    AIRTABLE_CONSTITUENT_TABLE, AIRTABLE_INDEX_TABLE, AIRTABLE_METRICS_TABLE,
    IST,
)

logger = logging.getLogger(__name__)

# Maximum records Airtable accepts per PATCH/POST
_BATCH_SIZE = 10


# ─────────────────────────────────────────────────────────────────────────────
# Low-level HTTP helpers
# ─────────────────────────────────────────────────────────────────────────────

class AirtableClient:
    """Thin REST client for Airtable v0 API — no third-party SDK required."""

    BASE_URL = "https://api.airtable.com/v0"

    def __init__(self, api_key: str, base_id: str):
        self.api_key = api_key
        self.base_id = base_id
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {api_key}",
            "Content-Type":  "application/json",
        })

    def _url(self, table: str) -> str:
        # URL-encode table name spaces for safety
        import urllib.parse
        return f"{self.BASE_URL}/{self.base_id}/{urllib.parse.quote(table)}"

    def list_records(self, table: str, max_records: int = 100) -> list[dict]:
        resp = self.session.get(
            self._url(table),
            params={"maxRecords": max_records},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json().get("records", [])

    def create_records(self, table: str, fields_list: list[dict]) -> list[dict]:
        """Create up to _BATCH_SIZE records per call."""
        created: list[dict] = []
        for i in range(0, len(fields_list), _BATCH_SIZE):
            batch = fields_list[i : i + _BATCH_SIZE]
            payload = {"records": [{"fields": f} for f in batch]}
            resp = self.session.post(self._url(table), json=payload, timeout=10)
            resp.raise_for_status()
            created.extend(resp.json().get("records", []))
        return created

    def upsert_records(
        self,
        table: str,
        fields_list: list[dict],
        merge_on: list[str],
    ) -> dict:
        """
        Airtable PATCH with performUpsert — matches on merge_on field(s).
        Requires Airtable API v0 with upsert support (Jan 2024+).
        """
        created = updated = 0
        for i in range(0, len(fields_list), _BATCH_SIZE):
            batch = fields_list[i : i + _BATCH_SIZE]
            payload = {
                "records":        [{"fields": f} for f in batch],
                "performUpsert":  {"fieldsToMergeOn": merge_on},
            }
            resp = self.session.patch(self._url(table), json=payload, timeout=15)
            resp.raise_for_status()
            data     = resp.json()
            created += len(data.get("createdRecords", []))
            updated += len(data.get("updatedRecords", []))
        return {"created": created, "updated": updated}

    def delete_all_records(self, table: str) -> int:
        """Delete every record in a table (use with caution)."""
        records = self.list_records(table, max_records=100)
        ids     = [r["id"] for r in records]
        if not ids:
            return 0
        for i in range(0, len(ids), _BATCH_SIZE):
            batch = ids[i : i + _BATCH_SIZE]
            resp  = self.session.delete(
                self._url(table),
                params=[("records[]", rid) for rid in batch],
                timeout=10,
            )
            resp.raise_for_status()
        return len(ids)

    def is_configured(self) -> bool:
        return (
            self.api_key not in ("", "YOUR_AIRTABLE_API_KEY")
            and self.base_id not in ("", "YOUR_AIRTABLE_BASE_ID")
        )


# ─────────────────────────────────────────────────────────────────────────────
# Sync Functions
# ─────────────────────────────────────────────────────────────────────────────

_client: Optional[AirtableClient] = None


def _get_client() -> AirtableClient:
    global _client
    if _client is None:
        _client = AirtableClient(AIRTABLE_API_KEY, AIRTABLE_BASE_ID)
    return _client


def sync_index_level(
    index_level: float,
    daily_return_pct: float,
    total_constituents: int,
    data_source: str = "yfinance",
    note: str = "",
) -> bool:
    """
    Append one row to the "Index Levels" table.
    Returns True on success.
    """
    client = _get_client()
    if not client.is_configured():
        logger.warning("Airtable not configured — skipping index level sync.")
        return False

    now = datetime.now(IST).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    fields = {
        "Name":               f"NATI {datetime.now(IST).strftime('%Y-%m-%d %H:%M')}",
        "Timestamp IST":      now,
        "Index Level":        round(index_level, 4),
        "Daily Return %":     round(daily_return_pct, 4),
        "Total Constituents": total_constituents,
        "Data Source":        data_source,
        "Notes":              note,
    }
    try:
        client.create_records(AIRTABLE_INDEX_TABLE, [fields])
        logger.info("Airtable: synced index level %.2f", index_level)
        return True
    except Exception as exc:
        logger.error("Airtable index level sync failed: %s", exc)
        return False


def sync_constituents(weights_df, live_quotes: Optional[dict] = None) -> bool:
    """
    Upsert each constituent row into the "Constituents" table.
    Merges on the "Ticker" field so existing rows are updated in-place.
    Returns True on success.
    """
    import pandas as pd

    client = _get_client()
    if not client.is_configured():
        logger.warning("Airtable not configured — skipping constituent sync.")
        return False

    now = datetime.now(IST).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    fields_list: list[dict] = []

    for _, row in weights_df.iterrows():
        ticker = row["ticker"]
        cmp    = (live_quotes.get(ticker) if live_quotes else None) or row["price"]
        daily_pct = (
            round((cmp / row["price"] - 1) * 100, 2)
            if live_quotes and ticker in live_quotes
            else row.get("daily_return_pct", 0)
        )
        fields_list.append({
            "Name":               row["company"],
            "Ticker":             ticker,
            "Tier":               row["tier"],
            "CMP (₹)":            round(float(cmp), 2),
            "Daily Chg %":        round(float(daily_pct), 2),
            "Market Cap (₹ Cr)":  round(float(row["full_mc_cr"]), 2),
            "Index Weight %":     round(float(row["weight_final"]) * 100, 4),
            "P/E":                float(row["pe"]) if pd.notna(row.get("pe")) else None,
            "ADTV (₹ Cr)":        round(float(row["adtv_cr"]), 2) if pd.notna(row.get("adtv_cr")) else None,
            "Last Updated":       now,
        })
        # Remove None values — Airtable rejects explicit nulls for some field types
        fields_list[-1] = {k: v for k, v in fields_list[-1].items() if v is not None}

    try:
        result = client.upsert_records(
            AIRTABLE_CONSTITUENT_TABLE, fields_list, merge_on=["Ticker"]
        )
        logger.info(
            "Airtable constituents: created=%d updated=%d",
            result["created"], result["updated"],
        )
        return True
    except Exception as exc:
        logger.error("Airtable constituent sync failed: %s", exc)
        return False


def sync_metrics(metrics: dict) -> bool:
    """
    Upsert key-value metric rows into the "Metrics" table.
    Merges on the "Name" field.
    Returns True on success.
    """
    client = _get_client()
    if not client.is_configured():
        logger.warning("Airtable not configured — skipping metrics sync.")
        return False

    now = datetime.now(IST).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    skip = {"Top 5 Gainers", "Top 5 Losers"}
    fields_list = [
        {"Name": k, "Value": str(v), "Last Updated": now}
        for k, v in metrics.items()
        if k not in skip and v is not None
    ]

    try:
        result = client.upsert_records(AIRTABLE_METRICS_TABLE, fields_list, merge_on=["Name"])
        logger.info(
            "Airtable metrics: created=%d updated=%d",
            result["created"], result["updated"],
        )
        return True
    except Exception as exc:
        logger.error("Airtable metrics sync failed: %s", exc)
        return False


def full_sync(
    index_level: float,
    daily_return_pct: float,
    weights_df,
    metrics: dict,
    live_quotes: Optional[dict] = None,
    data_source: str = "yfinance",
) -> dict[str, bool]:
    """Run all three sync operations.  Returns status dict."""
    return {
        "index_level":  sync_index_level(index_level, daily_return_pct, len(weights_df), data_source),
        "constituents": sync_constituents(weights_df, live_quotes),
        "metrics":      sync_metrics(metrics),
    }


# ─────────────────────────────────────────────────────────────────────────────
# CLI test helper
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(levelname)s — %(message)s")
    parser = argparse.ArgumentParser(description="Airtable sync tester")
    parser.add_argument("--test", action="store_true", help="Send a dummy record to verify connection")
    args = parser.parse_args()

    if args.test:
        client = _get_client()
        if not client.is_configured():
            print("❌  Airtable credentials not set. Update config.py or set env vars.")
        else:
            ok = sync_index_level(1000.0, 0.0, 0, note="connection-test")
            print("✅  Connection OK" if ok else "❌  Sync failed — check logs.")
