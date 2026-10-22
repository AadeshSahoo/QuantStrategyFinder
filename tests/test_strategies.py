"""Baseline strategy smoke tests on fixtures."""

from __future__ import annotations

import numpy as np
import pandas as pd

from quantstrategyfinder.strategies import STRATEGY_REGISTRY, get_strategy


def _bars(n=400):
    idx = pd.date_range("2018-01-01", periods=n, freq="B", tz="UTC")
    close = np.linspace(100, 150, n) + np.sin(np.linspace(0, 20, n)) * 5
    open_ = np.concatenate([[close[0]], close[:-1]])
    return pd.DataFrame(
        {
            "Open": open_,
            "High": np.maximum(open_, close) * 1.01,
            "Low": np.minimum(open_, close) * 0.99,
            "Close": close,
            "Volume": 1_000_000,
        },
        index=idx,
    )


def test_registry_has_three_baselines():
    assert set(STRATEGY_REGISTRY) >= {"ma_trend", "donchian", "momentum"}


def test_each_baseline_emits_aligned_signals():
    bars = _bars()
    for sid in ("ma_trend", "donchian", "momentum"):
        strat = get_strategy(sid)
        sig = strat.generate_signals(bars)
        assert len(sig) == len(bars)
        assert sig.index.equals(bars.index)
        assert sig.between(-1.0, 1.0).all()
