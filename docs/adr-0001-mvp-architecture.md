# ADR-0001: MVP architecture for QuantStrategyFinder

**Status:** Accepted  
**Date:** 2026-10-22  
**Context:** Greenfield P0 MVP per PRD §6 / §9 (Milestones 0–2).

## Decision

1. **Language/runtime:** Python 3.11–3.12, packaged with `pyproject.toml` / setuptools, CLI entry point `qsf`.
2. **Layout:** Modular package under `src/quantstrategyfinder/` matching PRD §6 (`data`, `strategies`, `engine`, `analytics`, `validation`, `discovery` stubs, `persistence`, `dashboard`, `reporting`).
3. **Market data:** Yahoo Finance via `yfinance` for daily OHLCV on SPY, QQQ, GLD, TLT, BTC-USD. Each download stores CSV + provenance JSON (source, retrieval time, hash, coverage). No silent symbol or timeframe substitution.
4. **Backtest:** Signal at close → fill at next open; long/flat only; `$200` default equity; configurable spread/slippage/commission; SQLite run index + filesystem artifacts under `reports/`.
5. **Validation:** Chronological 50/25/25; statuses `PASS` / `FAIL` / `INCONCLUSIVE` / `UNVERIFIED`. Ranking uses validation Sharpe among eligible candidates; final test recorded once.
6. **UI:** Streamlit reads only generated run artifacts.
7. **Out of MVP:** GitHub discovery (P1), walk-forward robustness suite beyond basic gates, futures/perps funding (P2).

## Consequences

- Results are reproducible given cached bars + config, within floating-point tolerance.
- GLD remains an ETF proxy (not XAUUSD). BTC-USD is spot, not perpetuals.
- A credible **NO STRATEGY PASSED VALIDATION** outcome is success.
