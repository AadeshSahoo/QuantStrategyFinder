"""Real-data end-to-end test (network)."""

from __future__ import annotations

from pathlib import Path

import pytest

from quantstrategyfinder.data.sources import fetch_daily_ohlcv
from quantstrategyfinder.engine.backtest import BacktestConfig, run_backtest
from quantstrategyfinder.engine.costs import CostModel
from quantstrategyfinder.pipeline import run_mvp_pipeline
from quantstrategyfinder.strategies import get_strategy
from quantstrategyfinder.validation.splits import chronological_split


@pytest.mark.e2e
def test_fetch_spy_and_btc_with_provenance(tmp_path: Path):
    cache = tmp_path / "cache"
    spy, spy_prov = fetch_daily_ohlcv("SPY", lookback_years=3, cache_dir=cache)
    btc, btc_prov = fetch_daily_ohlcv("BTC-USD", lookback_years=3, cache_dir=cache)
    assert len(spy) > 200
    assert len(btc) > 200
    assert spy_prov.source == "yfinance"
    assert btc_prov.content_hash
    assert spy_prov.n_bars == len(spy)
    # Provenance files written
    assert list(cache.glob("*.provenance.json"))


@pytest.mark.e2e
def test_three_baselines_and_holdout(tmp_path: Path):
    cache = tmp_path / "cache"
    bars, _ = fetch_daily_ohlcv("QQQ", lookback_years=5, cache_dir=cache)
    splits = chronological_split(bars)
    assert len(splits.test) > 0
    costs = CostModel()
    for sid in ("ma_trend", "donchian", "momentum"):
        result = run_backtest(
            bars,
            get_strategy(sid),
            config=BacktestConfig(starting_equity=200.0, symbol="QQQ", costs=costs),
        )
        assert not result.equity_curve.empty
        assert result.final_equity > 0


@pytest.mark.e2e
def test_pipeline_writes_artifacts(tmp_path: Path, monkeypatch):
    # Point cache into tmp via a tiny config
    cfg = tmp_path / "cfg.yaml"
    cache = tmp_path / "cache"
    reports = tmp_path / "reports"
    cfg.write_text(
        f"""
starting_equity: 200
universe: [SPY, BTC-USD]
data:
  interval: 1d
  lookback_years: 3
  cache_dir: {cache.as_posix()}
  adjusted: true
  timezone: UTC
costs:
  commission_per_trade: 0.0
  commission_pct: 0.0
  spread_bps: 2.0
  slippage_bps: 5.0
  min_notional: 1.0
  allow_fractional: true
splits:
  train_frac: 0.50
  val_frac: 0.25
  test_frac: 0.25
validation:
  min_bars: 100
  min_trades: 1
  max_drawdown_fail: 0.80
  min_val_sharpe: -5.0
strategies:
  ma_trend: {{fast: 20, slow: 50}}
  donchian: {{entry_lookback: 20, exit_lookback: 10}}
  momentum: {{lookback: 60, hold_threshold: 0.0}}
""",
        encoding="utf-8",
    )
    summary = run_mvp_pipeline(config_path=cfg, reports_dir=reports)
    assert summary["run_id"]
    art = Path(summary["artifact_dir"])
    assert (art / "summary.json").exists()
    assert (art / "report.md").exists()
    assert (art / "provenance.json").exists()
    assert summary["leaderboard"]
