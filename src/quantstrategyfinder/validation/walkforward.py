"""Simple walk-forward diagnostics for P1 (strictly past windows)."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from quantstrategyfinder.analytics.metrics import compute_metrics


def simple_walkforward_sharpe(
    equity: pd.Series,
    *,
    n_folds: int = 4,
    min_bars: int = 60,
) -> dict[str, Any]:
    """
    Split the equity curve into chronological folds; report per-fold Sharpe.
    This is diagnostic only — not used to re-optimize on the final test fold.
    """
    if equity is None or len(equity) < min_bars * 2:
        return {
            "n_folds": 0,
            "fold_sharpes": [],
            "mean_sharpe": None,
            "note": "Insufficient equity length for walk-forward folds.",
        }

    eq = equity.astype(float).dropna()
    folds = np.array_split(np.arange(len(eq)), n_folds)
    sharpes: list[float | None] = []
    for idxs in folds:
        if len(idxs) < min_bars:
            sharpes.append(None)
            continue
        seg = eq.iloc[idxs[0] : idxs[-1] + 1]
        m = compute_metrics(seg, starting_equity=float(seg.iloc[0]))
        sharpes.append(m.get("sharpe"))

    valid = [s for s in sharpes if s is not None]
    return {
        "n_folds": n_folds,
        "fold_sharpes": sharpes,
        "mean_sharpe": float(np.mean(valid)) if valid else None,
        "note": (
            "Walk-forward folds are chronological partitions of one continuous backtest "
            "equity path; parameters are not refit per fold in this MVP+P1 diagnostic."
        ),
    }
