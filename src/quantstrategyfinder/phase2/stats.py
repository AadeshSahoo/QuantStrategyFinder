"""Phase 2 statistical helpers: bootstrap CIs, BH-FDR, excess-return p-values."""

from __future__ import annotations

from typing import Any, Optional

import numpy as np
import pandas as pd

from quantstrategyfinder.analytics.metrics import monthly_returns


def bootstrap_monthly_ci(
    equity: pd.Series,
    *,
    n_boot: int = 1000,
    alpha: float = 0.05,
    seed: int = 42,
) -> dict[str, Any]:
    m = monthly_returns(equity)
    r = m.dropna().astype(float).values
    if len(r) < 8:
        return {
            "n_months": int(len(r)),
            "mean": float(np.mean(r)) if len(r) else None,
            "ci_low": None,
            "ci_high": None,
            "p_one_sided_mean_gt_0": None,
            "note": "Insufficient months for bootstrap.",
        }
    rng = np.random.default_rng(seed)
    means = np.empty(n_boot)
    for i in range(n_boot):
        means[i] = float(np.mean(rng.choice(r, size=len(r), replace=True)))
    lo, hi = np.quantile(means, [alpha / 2, 1 - alpha / 2])
    # one-sided p: share of bootstrap means <= 0
    p = float(np.mean(means <= 0.0))
    return {
        "n_months": int(len(r)),
        "mean": float(np.mean(r)),
        "ci_low": float(lo),
        "ci_high": float(hi),
        "p_one_sided_mean_gt_0": p,
        "note": f"{int((1-alpha)*100)}% bootstrap CI on mean monthly return; p=share(mean<=0).",
    }


def bootstrap_excess_p(
    strategy_eq: pd.Series,
    benchmark_eq: pd.Series,
    *,
    n_boot: int = 1000,
    seed: int = 42,
) -> dict[str, Any]:
    """One-sided p that mean monthly excess return <= 0."""
    ms = monthly_returns(strategy_eq)
    mb = monthly_returns(benchmark_eq)
    aligned = pd.concat([ms, mb], axis=1, join="inner").dropna()
    if aligned.empty or len(aligned) < 8:
        return {"n_months": int(len(aligned)), "mean_excess": None, "p_excess_le_0": None}
    excess = (aligned.iloc[:, 0] - aligned.iloc[:, 1]).values
    rng = np.random.default_rng(seed)
    means = np.empty(n_boot)
    for i in range(n_boot):
        means[i] = float(np.mean(rng.choice(excess, size=len(excess), replace=True)))
    return {
        "n_months": int(len(excess)),
        "mean_excess": float(np.mean(excess)),
        "p_excess_le_0": float(np.mean(means <= 0.0)),
    }


def benjamini_hochberg(
    pvalues: list[tuple[str, Optional[float]]],
    *,
    q: float = 0.10,
) -> dict[str, bool]:
    """
    Return map key -> rejected (significant) under BH FDR control.
    Keys with None p-values are never rejected.
    """
    valid = [(k, p) for k, p in pvalues if p is not None and not (isinstance(p, float) and np.isnan(p))]
    m = len(valid)
    out = {k: False for k, _ in pvalues}
    if m == 0:
        return out
    ordered = sorted(valid, key=lambda kp: kp[1])
    thresh_rank = 0
    for i, (k, p) in enumerate(ordered, start=1):
        if p <= (i / m) * q:
            thresh_rank = i
    for i, (k, p) in enumerate(ordered, start=1):
        if i <= thresh_rank:
            out[k] = True
    return out
