"""Metrics conventions and chronological splits."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quantstrategyfinder.analytics.metrics import compute_metrics, monthly_returns
from quantstrategyfinder.validation.robustness import evaluate_candidate
from quantstrategyfinder.validation.splits import chronological_split


def test_chronological_split_50_25_25():
    idx = pd.date_range("2015-01-01", periods=100, freq="B", tz="UTC")
    bars = pd.DataFrame(
        {
            "Open": 1.0,
            "High": 1.0,
            "Low": 1.0,
            "Close": 1.0,
            "Volume": 1,
        },
        index=idx,
    )
    s = chronological_split(bars, train_frac=0.5, val_frac=0.25, test_frac=0.25)
    assert len(s.train) + len(s.val) + len(s.test) == 100
    assert s.train.index.max() < s.val.index.min()
    assert s.val.index.max() < s.test.index.min()


def test_monthly_returns_are_actual_not_cagr_derived():
    idx = pd.date_range("2020-01-01", periods=90, freq="D", tz="UTC")
    # Deterministic equity path
    eq = pd.Series(np.linspace(200, 220, len(idx)), index=idx)
    m = monthly_returns(eq)
    metrics = compute_metrics(eq, starting_equity=200.0)
    assert metrics["actual_mean_monthly_return"] == pytest.approx(float(m.mean()))
    # CAGR monthly equivalent must be a separate field
    assert "monthly_compounded_equivalent" in metrics
    if metrics["monthly_compounded_equivalent"] is not None and len(m) > 0:
        # They are not required to match; ensure both exist as distinct concepts
        assert metrics["actual_mean_monthly_return"] is not None


def test_validation_inconclusive_too_few_trades():
    idx = pd.date_range("2020-01-01", periods=100, freq="B", tz="UTC")
    eq = pd.Series(200.0, index=idx)
    out = evaluate_candidate(
        equity_train=eq.iloc[:50],
        equity_val=eq.iloc[50:75],
        equity_test=eq.iloc[75:],
        starting_equity=200.0,
        trades_val=pd.DataFrame(),
        trades_test=pd.DataFrame(),
        min_bars=252,
        min_trades=5,
    )
    assert out.status in {"INCONCLUSIVE", "FAIL", "UNVERIFIED"}
