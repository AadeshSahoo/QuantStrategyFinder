# QuantStrategyFinder

Research-only Python app that backtests **first-party baseline** strategies on **real** daily market data, validates them on a chronological holdout, and shows honest PASS/FAIL/INCONCLUSIVE/UNVERIFIED results in a Streamlit dashboard.

This does **not** place live trades, certify future profits, or run untrusted GitHub strategy code (discovery is P1).

## Requirements

- Python **3.11 or 3.12**
- Network access for first-time Yahoo Finance downloads (`yfinance`)

## Install

### Windows PowerShell

```powershell
cd QuantStrategyFinder
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
pip install -e ".[dev]"
```

### Linux / Cursor cloud

```bash
cd QuantStrategyFinder
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
pip install -e ".[dev]"
```

## Quick start

```bash
# 1) Fetch real daily bars (cached under data/cache/)
qsf fetch-data

# 2) Run baselines + chronological 50/25/25 validation
qsf backtest

# 3) Inspect a run
qsf validate <RUN_ID>
qsf report <RUN_ID>

# 4) Dashboard (reads reports/<RUN_ID>/ artifacts only)
qsf dashboard --port 8507
```

Open [http://127.0.0.1:8507](http://127.0.0.1:8507) after the dashboard starts.

Unit tests (no network):

```bash
pytest -q -m "not e2e"
```

Real-data end-to-end (network):

```bash
pytest -q -m e2e
```

## Default universe & strategies

| Symbol | Notes |
|--------|--------|
| SPY, QQQ, TLT | US ETFs (adjusted close scaled OHLC) |
| GLD | **Gold ETF proxy** — not XAUUSD / GC futures |
| BTC-USD | Spot crypto USD — not perpetual futures |

Baselines: `ma_trend`, `donchian`, `momentum` (see `src/quantstrategyfinder/strategies/`).

## Cost & account assumptions (MVP)

- Starting equity: **$200** (configurable in `configs/default.yaml`)
- Fill: signal observed at **close** → order filled at **next bar open**
- Costs: spread + slippage in bps + optional commission (`configs/default.yaml`)
- Long/flat only; fractional shares allowed by default
- Idle cash earns **0%**; no futures margin or funding yet

## Validation

- Chronological split: **50% train / 25% validation / 25% locked test**
- Statuses: `PASS`, `FAIL`, `INCONCLUSIVE`, `UNVERIFIED`
- Ranking only among eligible `PASS` candidates using **validation** Sharpe
- If none qualify, the report states **NO STRATEGY PASSED VALIDATION**

Actual month-by-month returns are shown separately from the CAGR-derived monthly equivalent `(1+CAGR)^(1/12)-1`.

## Outputs

Each `qsf backtest` writes `reports/<run_id>/`:

- `summary.json`, `report.md`, `leaderboard.csv`, `provenance.json`
- Per candidate: `equity_*.csv`, `fills_*.csv`, `trades_*.csv`, `result_*.json`

## Known limitations

- Data source is Yahoo Finance via `yfinance` (free, best-effort; not a licensed institutional feed).
- No GitHub strategy discovery (P1).
- No walk-forward / bootstrap / multiple-testing battery beyond MVP gates (P1).
- No intraday crypto, gold futures roll models, or perps funding (P2).
- Missing data fails clearly — results are never fabricated.

## Architecture

See [docs/adr-0001-mvp-architecture.md](docs/adr-0001-mvp-architecture.md) and the PRD (project docs).

## License

MIT (application code). Market data remains subject to upstream provider terms.
