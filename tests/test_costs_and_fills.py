"""Deterministic tests for costs, next-bar fills, and no look-ahead."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quantstrategyfinder.engine.backtest import BacktestConfig, run_backtest
from quantstrategyfinder.engine.broker import SimulatedBroker
from quantstrategyfinder.engine.costs import CostModel
from quantstrategyfinder.strategies.ma_trend import MovingAverageTrend
from quantstrategyfinder.strategies.momentum import TimeSeriesMomentum


def _synth_bars(n: int = 300, start: float = 100.0, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2020-01-01", periods=n, freq="B", tz="UTC")
    rets = rng.normal(0.0005, 0.01, size=n)
    close = start * np.cumprod(1 + rets)
    open_ = np.concatenate([[start], close[:-1]])
    high = np.maximum(open_, close) * 1.001
    low = np.minimum(open_, close) * 0.999
    vol = rng.integers(1_000_000, 2_000_000, size=n)
    return pd.DataFrame(
        {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": vol},
        index=idx,
    )


def test_buy_pays_spread_and_slippage():
    costs = CostModel(spread_bps=10, slippage_bps=10, commission_per_trade=0.0)
    broker = SimulatedBroker(200.0, "TEST", costs)
    fill = broker.rebalance_to_weight(
        timestamp=pd.Timestamp("2020-01-02", tz="UTC"),
        open_price=100.0,
        target_weight=1.0,
    )
    assert fill is not None
    # half-spread 5bps + slip 10bps = 15bps
    assert fill.price == pytest.approx(100.0 * (1 + 0.0015), rel=1e-9)
    assert broker.state.cash < 200.0


def test_insufficient_cash_rejects_impossible_size():
    costs = CostModel(min_notional=1.0, allow_fractional=False, spread_bps=0, slippage_bps=0)
    broker = SimulatedBroker(200.0, "TEST", costs)
    # Price so high integer share cannot be bought
    fill = broker.rebalance_to_weight(
        timestamp=pd.Timestamp("2020-01-02", tz="UTC"),
        open_price=500.0,
        target_weight=1.0,
    )
    assert fill is None
    assert any(r["reason"] == "integer_qty_infeasible" for r in broker.state.rejections)


def test_next_bar_fill_no_lookahead():
    """Signal on day t must not fill using day t open."""
    bars = _synth_bars(80)
    # Force a known signal: momentum with lookback 2 on rising series
    close = np.linspace(100, 180, len(bars))
    bars = bars.copy()
    bars["Close"] = close
    bars["Open"] = np.concatenate([[100], close[:-1]])
    bars["High"] = bars[["Open", "Close"]].max(axis=1) * 1.001
    bars["Low"] = bars[["Open", "Close"]].min(axis=1) * 0.999

    strat = TimeSeriesMomentum(lookback=5, hold_threshold=-1.0)  # always long after warmup
    costs = CostModel(spread_bps=0, slippage_bps=0)
    result = run_backtest(
        bars, strat, config=BacktestConfig(starting_equity=200.0, symbol="TEST", costs=costs)
    )
    assert not result.fills.empty
    first_fill_ts = pd.Timestamp(result.fills.iloc[0]["timestamp"])
    # First actionable signal index is lookback; fill is next bar
    signals = strat.generate_signals(bars)
    first_signal_idx = signals[signals > 0].index[0]
    assert first_fill_ts > first_signal_idx or first_fill_ts == bars.index[
        bars.index.get_loc(first_signal_idx) + 1
    ]


def test_ma_trend_warmup_flat():
    bars = _synth_bars(250)
    strat = MovingAverageTrend(fast=10, slow=50)
    sig = strat.generate_signals(bars)
    assert (sig.iloc[:49] == 0).all()


def test_drawdown_computation():
    from quantstrategyfinder.analytics.metrics import max_drawdown

    eq = pd.Series([100.0, 110.0, 90.0, 95.0])
    assert max_drawdown(eq) == pytest.approx((90 / 110) - 1.0)
