"""Unit tests for Phase 2 strategy signals."""

from __future__ import annotations

import numpy as np
import pandas as pd

from quantstrategyfinder.phase2.registry import get_phase2_strategy, list_phase2_strategies
from quantstrategyfinder.phase2.stats import benjamini_hochberg


def _bars(n: int = 400) -> pd.DataFrame:
    idx = pd.date_range("2018-01-01", periods=n, freq="B", tz="UTC")
    close = np.linspace(100, 140, n) + np.sin(np.linspace(0, 15, n)) * 4
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


def test_phase2_registry_includes_new_families():
    ids = set(list_phase2_strategies())
    assert {"supertrend", "short_reversal", "vol_target_trend"} <= ids


def test_new_strategies_emit_aligned_signals():
    bars = _bars()
    for sid in ("supertrend", "short_reversal", "vol_target_trend"):
        sig = get_phase2_strategy(sid).generate_signals(bars)
        assert len(sig) == len(bars)
        assert sig.between(0.0, 1.0).all()


def test_bh_fdr_basic():
    pvals = [("a", 0.001), ("b", 0.04), ("c", 0.5), ("d", None)]
    out = benjamini_hochberg(pvals, q=0.10)
    assert out["a"] is True
    assert out["d"] is False
