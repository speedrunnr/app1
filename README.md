# 📈 New Age Tech Index (NATI) — Production Dashboard

> Tracks India's listed startup ecosystem across 47 constituents using a
> tiered equal-weight methodology. Built in Python · Streamlit · Plotly.

---

## Quick Start

```bash
git clone <your-repo>
cd nati_index

pip install -r requirements.txt

# Run the dashboard
streamlit run app.py
```

Open [http://localhost:8501](http://localhost:8501) in your browser.

---

## Project Structure

```
nati_index/
├── app.py              Main Streamlit dashboard
├── config.py           All constants, tickers, API keys
├── index_engine.py     Tiered weight calculator + performance + metrics
├── data_pipeline.py    yfinance fetcher + broker API layer + market-hours
├── csv_logger.py       Hourly & EOD CSV export
├── airtable_sync.py    Airtable REST sync (headless CMS)
├── requirements.txt
├── data/               Auto-created; holds CSV logs
│   ├── index_levels.csv          Cumulative intraday snapshots
│   ├── constituent_snapshot.csv  Latest weight table
│   └── eod_YYYYMMDD.csv          Daily EOD archives
└── README.md
```

---

## Dashboard Features

| Feature | Detail |
|---|---|
| Interactive chart | Plotly line — switch between **Base 1,000 level** and **% change vs NIFTY 50** |
| Range selector | 1M / 3M / 6M / YTD / 1Y / All — one click |
| Tier sub-indices | Toggle Large / Mid / Small overlays |
| Constituent table | Filterable, sortable; live CMP if broker API connected |
| Daily % colour coding | Green / Red inline |
| KPI tiles | NATI level, Weighted P/E, β, σ, Sharpe, Max Drawdown |
| Gainers / Losers | Top 5 movers updated each refresh |
| Auto-refresh | Every **5 min** during market hours; every **60 min** off-hours |

---

## Index Methodology (v2.0)

```
Tier        Market Cap Range (₹ Cr)    Tier Allocation    Intra-Tier
──────────  ────────────────────────   ───────────────    ──────────
Large       > 50,000                   50 %               Equal weight
Mid         10,000 – 50,000            35 %               Equal weight
Small        1,000 – 10,000            15 %               Equal weight
```

Per-stock weight = `tier_allocation ÷ companies_in_tier`  
Empty tiers → allocation redistributed proportionally across active tiers.  
Minimum size filter: ₹1,000 Cr full market cap + ₹5 Cr ADTV.

---

## Real-Time Data Pipeline

### Default: yfinance (free, ~15-min delayed)

| Limitation | Detail |
|---|---|
| **Latency** | ~15-minute delay for NSE/BSE via Yahoo Finance |
| **Rate limit** | ~2,000 requests/hr/IP — mitigated by batch `yf.download()` |
| **Reliability** | Unofficial API — no SLA; breaks occasionally on Yahoo-side changes |
| **Verdict** | Fine for EOD analysis and intraday dashboards; **not** suitable for algo-trading |

### Upgrade: Broker API (true real-time)

Set the `BROKER_PROVIDER` environment variable to activate:

```bash
# Zerodha KiteConnect  (~50ms WebSocket feed)
export BROKER_PROVIDER=kite
export KITE_API_KEY=your_api_key
export KITE_ACCESS_TOKEN=your_daily_token   # regenerate daily

# Dhan HQ  (<500ms REST)
export BROKER_PROVIDER=dhan
export DHAN_CLIENT_ID=your_client_id
export DHAN_ACCESS_TOKEN=your_token         # monthly refresh

# Shoonya (Finvasia) — free API
export BROKER_PROVIDER=shoonya
export SHOONYA_USER_ID=your_user
export SHOONYA_PASSWORD=your_password
```

History (for weight computation) always uses yfinance to preserve API quota.

### Broker Comparison

| Broker | Latency | Cost | Access Token |
|---|---|---|---|
| Kite (Zerodha) | ~50ms WS | ₹2,000/mo | Daily OAuth, automatable |
| Dhan HQ | ~300ms | Free | Monthly, manual |
| Shoonya | ~500ms | Free | Session-based |

---

## CSV Backup System

Two automatic export modes:

**Hourly snapshot** (`data/index_levels.csv`) — appended every 60 min during
market hours. Schema:
```
timestamp_ist, index_level, daily_return_pct, constituents, data_source, note
```

**EOD export** (`data/eod_YYYYMMDD.csv`) — triggered once at 15:35 IST.
Contains full constituent detail + a commented metrics header block.

Files are written atomically (temp-file rename) — safe to open in Excel
while the app is running.

You can also trigger a manual EOD export via the **"Export EOD CSV Now"**
button in the sidebar.

---

## Airtable Integration

### Setup

1. Go to [airtable.com/create/tokens](https://airtable.com/create/tokens)
2. Create a **Personal Access Token** with scopes:
   - `data.records:read`
   - `data.records:write`
3. Create a Base with three tables exactly as below.

### Required Airtable Tables

**Table 1: `Index Levels`**
```
Name (Single line text — primary field)
Timestamp IST  (Date/time)
Index Level    (Number, 4 decimals)
Daily Return % (Number, 4 decimals)
Total Constituents (Number)
Data Source    (Single line text)
Notes          (Single line text)
```

**Table 2: `Constituents`**
```
Name           (Single line text — primary, stores Company name)
Ticker         (Single line text)
Tier           (Single select: Large / Mid / Small)
CMP (₹)        (Currency)
Daily Chg %    (Number)
Market Cap (₹ Cr) (Number)
Index Weight % (Number)
P/E            (Number)
ADTV (₹ Cr)   (Number)
Last Updated   (Date/time)
```

**Table 3: `Metrics`**
```
Name           (Single line text — primary)
Value          (Single line text)
Last Updated   (Date/time)
```

### Environment Variables

```bash
export AIRTABLE_API_KEY="patXXXXXXXXXXXXXX"
export AIRTABLE_BASE_ID="appXXXXXXXXXXXXXX"
```

Or set them directly in `config.py`.

### Test Connection

```bash
python airtable_sync.py --test
```

### Sync Behaviour

- **Manual**: Click "Sync to Airtable" in the sidebar
- **Automatic**: Hook into `maybe_run_eod_export()` in `csv_logger.py` to
  auto-sync at EOD
- Constituents use **upsert** (merge on Ticker) — no duplicate rows
- Index Levels always **append** (full history preserved)
- Metrics **upsert** on Name — always shows latest value

---

## Environment Variables Reference

```bash
# Airtable
AIRTABLE_API_KEY=
AIRTABLE_BASE_ID=

# Broker API (pick one)
BROKER_PROVIDER=yfinance   # or: kite / dhan / shoonya
KITE_API_KEY=
KITE_ACCESS_TOKEN=
DHAN_CLIENT_ID=
DHAN_ACCESS_TOKEN=
SHOONYA_USER_ID=
SHOONYA_PASSWORD=
```

---

## Deployment (Production Checklist)

- [ ] Run behind a **reverse proxy** (nginx) with HTTPS
- [ ] Set env vars via system environment or a `.env` file (not committed to git)
- [ ] Use **`systemd`** or **`supervisord`** to keep `streamlit run app.py` alive
- [ ] Mount `data/` on a **persistent volume** (Docker) so CSV logs survive restarts
- [ ] Schedule a **daily cron** at 15:35 IST as a backup EOD trigger:
  ```cron
  35 15 * * 1-5  cd /path/to/nati_index && python -c "import csv_logger; ..."
  ```
- [ ] Rotate `index_levels.csv` monthly to avoid unbounded growth
- [ ] Airtable personal tokens expire — set a calendar reminder to refresh

---

*New Age Tech Index v2.0 · Author: Sandeep Singh · Last updated: May 2026*
