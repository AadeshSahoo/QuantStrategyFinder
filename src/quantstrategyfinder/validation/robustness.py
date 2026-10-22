"""Validation status: PASS / FAIL / INCONCLUSIVE / UNVERIFIED."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from quantstrategyfinder.analytics.metrics import compute_metrics


@dataclass
class ValidationOutcome:
    status: str  # PASS | FAIL | INCONCLUSIVE | UNVERIFIED
    reasons: list[str] = field(default_factory=list)
    metrics_train: dict[str, Any] = field(default_factory=dict)
    metrics_val: dict[str, Any] = field(default_factory=dict)
    metrics_test: dict[str, Any] = field(default_factory=dict)
    eligible_for_ranking: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "reasons": self.reasons,
            "eligible_for_ranking": self.eligible_for_ranking,
            "metrics_train": self.metrics_train,
            "metrics_val": self.metrics_val,
            "metrics_test": self.metrics_test,
        }


def evaluate_candidate(
    *,
    equity_train,
    equity_val,
    equity_test,
    starting_equity: float | None = None,
    starting_equity_train: float | None = None,
    starting_equity_val: float | None = None,
    starting_equity_test: float | None = None,
    trades_train=None,
    trades_val=None,
    trades_test=None,
    fills_test=None,
    min_bars: int = 252,
    min_trades: int = 5,
    max_drawdown_fail: float = 0.50,
    min_val_sharpe: float = -0.5,
    data_verified: bool = True,
    look_ahead_free: bool = True,
    costs_modeled: bool = True,
) -> ValidationOutcome:
    """
    Hard gates then soft checks. Does NOT optimize on test.
    Test metrics are recorded once for reporting; selection uses train/val only.
    """
    reasons: list[str] = []

    if not data_verified:
        return ValidationOutcome(
            status="UNVERIFIED",
            reasons=["Market data provenance missing or unverified."],
        )
    if not look_ahead_free:
        return ValidationOutcome(status="FAIL", reasons=["Look-ahead bias detected or unproven."])
    if not costs_modeled:
        return ValidationOutcome(status="FAIL", reasons=["Costs not modeled."])

    base = starting_equity if starting_equity is not None else 200.0
    start_train = starting_equity_train if starting_equity_train is not None else base
    start_val = starting_equity_val if starting_equity_val is not None else base
    start_test = starting_equity_test if starting_equity_test is not None else base

    m_train = compute_metrics(equity_train, starting_equity=start_train, trades=trades_train)
    m_val = compute_metrics(equity_val, starting_equity=start_val, trades=trades_val)
    m_test = compute_metrics(
        equity_test, starting_equity=start_test, trades=trades_test, fills=fills_test
    )

    n_train = m_train.get("n_observations") or 0
    n_val = m_val.get("n_observations") or 0
    n_test = m_test.get("n_observations") or 0

    if min(n_train, n_val, n_test) < max(30, min_bars // 4):
        reasons.append(
            f"Insufficient bars in one or more splits "
            f"(train={n_train}, val={n_val}, test={n_test}; soft min={max(30, min_bars // 4)})."
        )
        return ValidationOutcome(
            status="INCONCLUSIVE",
            reasons=reasons,
            metrics_train=m_train,
            metrics_val=m_val,
            metrics_test=m_test,
        )

    n_trades_val = m_val.get("n_trades") or 0
    n_trades_test = m_test.get("n_trades") or 0
    if n_trades_val + n_trades_test < min_trades:
        reasons.append(
            f"Too few trades across val+test ({n_trades_val + n_trades_test} < {min_trades})."
        )
        return ValidationOutcome(
            status="INCONCLUSIVE",
            reasons=reasons,
            metrics_train=m_train,
            metrics_val=m_val,
            metrics_test=m_test,
        )

    val_dd = m_val.get("max_drawdown")
    if val_dd is not None and abs(val_dd) > max_drawdown_fail:
        reasons.append(f"Validation max drawdown {val_dd:.2%} exceeds fail threshold {max_drawdown_fail:.0%}.")
        return ValidationOutcome(
            status="FAIL",
            reasons=reasons,
            metrics_train=m_train,
            metrics_val=m_val,
            metrics_test=m_test,
            eligible_for_ranking=False,
        )

    val_sharpe = m_val.get("sharpe")
    if val_sharpe is None:
        reasons.append("Validation Sharpe undefined (insufficient return variance).")
        return ValidationOutcome(
            status="INCONCLUSIVE",
            reasons=reasons,
            metrics_train=m_train,
            metrics_val=m_val,
            metrics_test=m_test,
        )

    if val_sharpe < min_val_sharpe:
        reasons.append(
            f"Validation Sharpe {val_sharpe:.3f} below minimum {min_val_sharpe}."
        )
        return ValidationOutcome(
            status="FAIL",
            reasons=reasons,
            metrics_train=m_train,
            metrics_val=m_val,
            metrics_test=m_test,
        )

    # Selection uses val; test is reported but not used to flip PASS→FAIL for ranking
    # except catastrophic test drawdown as a hard safety gate
    test_dd = m_test.get("max_drawdown")
    if test_dd is not None and abs(test_dd) > max_drawdown_fail:
        reasons.append(
            f"Final test max drawdown {test_dd:.2%} exceeds fail threshold {max_drawdown_fail:.0%}."
        )
        return ValidationOutcome(
            status="FAIL",
            reasons=reasons,
            metrics_train=m_train,
            metrics_val=m_val,
            metrics_test=m_test,
        )

    reasons.append(
        "Passed hard gates on provenance, costs, sample size, trades, and validation risk/Sharpe. "
        "Final-test metrics recorded once; not used for parameter selection."
    )
    return ValidationOutcome(
        status="PASS",
        reasons=reasons,
        metrics_train=m_train,
        metrics_val=m_val,
        metrics_test=m_test,
        eligible_for_ranking=True,
    )
