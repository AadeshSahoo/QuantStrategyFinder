"""Performance metrics with explicit return conventions."""

from __future__ import annotations

from typing import Any, Optional

import numpy as np
import pandas as pd


def _safe_div(a: float, b: float) -> float | None:
    if b == 0 or np.isnan(b) or np.isnan(a):
        return None
    return float(a / b)


def monthly_returns(equity: pd.Series) -> pd.Series:
    """Actual calendar month-by-month simple returns from equity curve."""
    if equity.empty:
        return pd.Series(dtype=float)
    eq = equity.copy()
    eq.index = pd.to_datetime(eq.index)
    monthly = eq.resample("ME").last().dropna()
    return monthly.pct_change().dropna().rename("monthly_return")


def max_drawdown(equity: pd.Series) -> float:
    if equity.empty:
        return 0.0
    peak = equity.cummax()
    dd = equity / peak - 1.0
    return float(dd.min())


def compute_metrics(
    equity: pd.Series,
    *,
    starting_equity: float,
    trades: Optional[pd.DataFrame] = None,
    fills: Optional[pd.DataFrame] = None,
    periods_per_year: float = 252.0,
    total_costs: Optional[float] = None,
) -> dict[str, Any]:
    """
    Return conventions:
    - Daily returns: simple pct_change on equity marked at close.
    - CAGR: (ending/start)^(periods_per_year/n_periods) - 1 using trading days.
    - monthly_compounded_equivalent: (1+CAGR)^(1/12)-1 — NOT an observed monthly return.
    - actual_monthly_*: from calendar month equity endpoints.
    """
    out: dict[str, Any] = {
        "starting_equity": starting_equity,
        "ending_equity": None,
        "total_return": None,
        "cagr": None,
        "monthly_compounded_equivalent": None,
        "actual_mean_monthly_return": None,
        "actual_median_monthly_return": None,
        "actual_monthly_returns": {},
        "volatility_ann": None,
        "sharpe": None,
        "sortino": None,
        "calmar": None,
        "max_drawdown": None,
        "worst_month": None,
        "profit_factor": None,
        "win_rate": None,
        "expectancy": None,
        "n_trades": 0,
        "n_fills": 0,
        "turnover_approx": None,
        "mean_exposure": None,
        "total_costs": total_costs,
        "n_observations": 0,
        "periods_per_year": periods_per_year,
        "notes": [
            "CAGR annualization uses trading-day count and periods_per_year "
            f"(default {periods_per_year}; crypto still uses calendar trading bars from source).",
            "monthly_compounded_equivalent is derived from CAGR, not observed monthly returns.",
        ],
    }

    if equity is None or equity.empty or len(equity) < 2:
        out["notes"].append("Insufficient equity observations for metrics.")
        return out

    eq = equity.astype(float)
    out["ending_equity"] = float(eq.iloc[-1])
    out["total_return"] = float(eq.iloc[-1] / starting_equity - 1.0)
    out["n_observations"] = int(len(eq))
    out["max_drawdown"] = max_drawdown(eq)

    n = len(eq)
    years = n / periods_per_year
    if years > 0 and starting_equity > 0 and eq.iloc[-1] > 0:
        out["cagr"] = float((eq.iloc[-1] / starting_equity) ** (1.0 / years) - 1.0)
        if out["cagr"] is not None:
            out["monthly_compounded_equivalent"] = float((1.0 + out["cagr"]) ** (1.0 / 12.0) - 1.0)

    rets = eq.pct_change().dropna()
    if len(rets) >= 2:
        vol = float(rets.std(ddof=1) * np.sqrt(periods_per_year))
        out["volatility_ann"] = vol
        mean = float(rets.mean())
        out["sharpe"] = _safe_div(mean * periods_per_year, vol) if vol else None
        downside = rets[rets < 0]
        if len(downside) >= 1:
            dvol = float(downside.std(ddof=1) * np.sqrt(periods_per_year))
            out["sortino"] = _safe_div(mean * periods_per_year, dvol) if dvol else None
        if out["cagr"] is not None and out["max_drawdown"] not in (None, 0.0):
            out["calmar"] = _safe_div(out["cagr"], abs(out["max_drawdown"]))

    mrets = monthly_returns(eq)
    if not mrets.empty:
        out["actual_mean_monthly_return"] = float(mrets.mean())
        out["actual_median_monthly_return"] = float(mrets.median())
        out["worst_month"] = float(mrets.min())
        out["actual_monthly_returns"] = {
            (idx.strftime("%Y-%m") if hasattr(idx, "strftime") else str(idx)): float(val)
            for idx, val in mrets.items()
        }

    if trades is not None and not trades.empty:
        closed = trades[trades["status"].isin(["closed"])] if "status" in trades.columns else trades
        out["n_trades"] = int(len(closed))
        if "realized_pnl" in closed.columns and len(closed):
            pnls = closed["realized_pnl"].dropna().astype(float)
            if len(pnls):
                wins = pnls[pnls > 0]
                losses = pnls[pnls <= 0]
                out["win_rate"] = float((pnls > 0).mean())
                out["expectancy"] = float(pnls.mean())
                gross_profit = float(wins.sum()) if len(wins) else 0.0
                gross_loss = float(-losses.sum()) if len(losses) else 0.0
                out["profit_factor"] = _safe_div(gross_profit, gross_loss) if gross_loss else None

    if fills is not None and not fills.empty:
        out["n_fills"] = int(len(fills))
        if "notional" in fills.columns:
            out["turnover_approx"] = float(fills["notional"].abs().sum() / starting_equity)
        if total_costs is None and "commission" in fills.columns:
            # Commission only; spread/slippage embedded in fill prices
            out["total_costs"] = float(fills["commission"].sum())
            out["notes"].append(
                "total_costs currently sums explicit commissions; "
                "spread/slippage are embedded in fill prices vs mid."
            )

    return out
