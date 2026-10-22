"""Forward-test metrics with insufficient-evidence gating and BH over n=5."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from quantstrategyfinder.analytics.metrics import compute_metrics, monthly_returns
from quantstrategyfinder.data.sources import fetch_daily_ohlcv
from quantstrategyfinder.phase2.stats import benjamini_hochberg, bootstrap_monthly_ci
from quantstrategyfinder.phase3.store import PaperStore


def _bah_equity(symbol: str, dates: pd.DatetimeIndex, start_equity: float, cache_dir: str) -> pd.Series:
    bars, _ = fetch_daily_ohlcv(symbol, lookback_years=10, cache_dir=cache_dir)
    # Align to paper equity dates
    closes = bars["Close"].reindex(dates).ffill()
    if closes.isna().all():
        return pd.Series(start_equity, index=dates, name="bah")
    first = closes.dropna().iloc[0]
    return (start_equity * (closes / first)).rename("bah")


def compute_forward_performance(store: PaperStore, cfg: dict[str, Any]) -> dict[str, Any]:
    insuff = cfg.get("insufficient_evidence") or {}
    min_days = int(insuff.get("min_trading_days", 21))
    min_trades = int(insuff.get("min_completed_trades", 5))
    min_months = int(insuff.get("min_months_for_cagr", 3))
    mt = cfg.get("multiple_testing") or {}
    q = float(mt.get("q", 0.10))
    cache_dir = (cfg.get("data") or {}).get("cache_dir", "data/cache")
    forward_start = cfg["forward_start_date"]

    eq_rows = store.export_equity()
    fill_rows = store.export_fills()
    fills_df = pd.DataFrame(fill_rows)
    eq_df = pd.DataFrame(eq_rows)

    results: list[dict[str, Any]] = []
    pvals: list[tuple[str, float | None]] = []

    for cand in store.list_candidates():
        cid = cand["candidate_id"]
        start_eq = float(cand["starting_equity"])
        sym = cand["symbol"]
        bench = cand["benchmark_symbol"]
        sub = eq_df[eq_df["candidate_id"] == cid].copy() if not eq_df.empty else pd.DataFrame()
        n_fills = int((fills_df["candidate_id"] == cid).sum()) if not fills_df.empty else 0

        row: dict[str, Any] = {
            "candidate_id": cid,
            "strategy_id": cand["strategy_id"],
            "symbol": sym,
            "benchmark_symbol": bench,
            "forward_start_date": forward_start,
            "starting_equity": start_eq,
            "n_equity_days": int(len(sub)),
            "n_fills": n_fills,
            "label": "SIMULATED — NOT LIVE TRADING",
            "validation_status": "INSUFFICIENT_EVIDENCE",
            "validation_notes": [],
        }

        if sub.empty or len(sub) < min_days or n_fills < min_trades:
            row["validation_notes"].append(
                f"Insufficient forward sample (days={len(sub)}/{min_days}, fills={n_fills}/{min_trades}). "
                "Do not treat as validated."
            )
            # Still compute whatever we can
            if not sub.empty:
                eq = sub.set_index(pd.to_datetime(sub["asof_date"], utc=True))["equity"].astype(float)
                m = compute_metrics(eq, starting_equity=start_eq)
                row.update(
                    {
                        "ending_equity": m.get("ending_equity"),
                        "total_return": m.get("total_return"),
                        "max_drawdown": m.get("max_drawdown"),
                        "n_observations": m.get("n_observations"),
                    }
                )
            results.append(row)
            pvals.append((cid, None))
            continue

        eq = sub.set_index(pd.to_datetime(sub["asof_date"], utc=True))["equity"].astype(float)
        m = compute_metrics(eq, starting_equity=start_eq)
        months = monthly_returns(eq)
        ci = bootstrap_monthly_ci(eq, n_boot=1000, seed=42)
        bah = _bah_equity(bench, eq.index, start_eq, cache_dir)
        bah_m = compute_metrics(bah.dropna(), starting_equity=start_eq)
        cash_eq = pd.Series(start_eq, index=eq.index, name="cash")

        # Excess monthly mean vs BAH for p-value
        ms = monthly_returns(eq)
        mb = monthly_returns(bah)
        aligned = pd.concat([ms, mb], axis=1, join="inner").dropna()
        p_excess = None
        if len(aligned) >= 8:
            excess = (aligned.iloc[:, 0] - aligned.iloc[:, 1]).values
            rng = np.random.default_rng(42)
            means = [float(np.mean(rng.choice(excess, size=len(excess), replace=True))) for _ in range(1000)]
            p_excess = float(np.mean(np.array(means) <= 0.0))

        fees = 0.0
        if not fills_df.empty:
            fsub = fills_df[fills_df["candidate_id"] == cid]
            fees = float(fsub["commission"].sum() + fsub["spread_slippage_cost"].sum())

        cagr_ok = len(months) >= min_months
        row.update(
            {
                "ending_equity": m.get("ending_equity"),
                "total_return": m.get("total_return"),
                "cagr": m.get("cagr") if cagr_ok else None,
                "cagr_note": None
                if cagr_ok
                else f"CAGR withheld — need >={min_months} months (have {len(months)}).",
                "monthly_compounded_equivalent": m.get("monthly_compounded_equivalent")
                if cagr_ok
                else None,
                "actual_mean_monthly": m.get("actual_mean_monthly_return"),
                "actual_median_monthly": m.get("actual_median_monthly_return"),
                "max_drawdown": m.get("max_drawdown"),
                "sharpe": m.get("sharpe"),
                "sortino": m.get("sortino"),
                "win_rate": None,  # trade-level incomplete for open books
                "n_observations": m.get("n_observations"),
                "benchmark_total_return": bah_m.get("total_return"),
                "benchmark_cagr": bah_m.get("cagr") if cagr_ok else None,
                "cash_total_return": 0.0,
                "excess_total_return_vs_bah": (
                    None
                    if m.get("total_return") is None or bah_m.get("total_return") is None
                    else float(m["total_return"]) - float(bah_m["total_return"])
                ),
                "bootstrap_monthly_ci_low": ci.get("ci_low"),
                "bootstrap_monthly_ci_high": ci.get("ci_high"),
                "excess_bootstrap_p": p_excess,
                "total_fees_paid": fees,
                "validation_status": "FORWARD_RUNNING_UNVALIDATED",
                "validation_notes": [
                    "Forward sample meets minimum day/fill thresholds but is NOT labeled validated. "
                    "Validation requires precommitted gates on adequate independent forward evidence "
                    "after multiple-testing correction."
                ],
            }
        )
        pvals.append((cid, p_excess))
        results.append(row)

    bh = benjamini_hochberg(pvals, q=q)
    for r in results:
        r["bh_fdr_pass"] = bool(bh.get(r["candidate_id"]))
        if r["validation_status"] == "FORWARD_RUNNING_UNVALIDATED" and r["bh_fdr_pass"]:
            # Still do not auto-validate on short forward windows
            r["validation_notes"].append(
                "BH-FDR pass on current short forward window is provisional — "
                "insufficient for STATISTICALLY VALIDATED label per Phase 3 policy."
            )
        if r["validation_status"] != "INSUFFICIENT_EVIDENCE" and not r["bh_fdr_pass"]:
            r["validation_notes"].append("Failed BH-FDR among the 5 registered candidates (or p undefined).")

    n_insuff = sum(1 for r in results if r["validation_status"] == "INSUFFICIENT_EVIDENCE")
    summary = {
        "n_candidates": len(results),
        "n_insufficient_evidence": n_insuff,
        "n_forward_running_unvalidated": sum(
            1 for r in results if r["validation_status"] == "FORWARD_RUNNING_UNVALIDATED"
        ),
        "n_statistically_validated": 0,  # never auto-promote on short samples
        "multiple_testing_n": int((cfg.get("multiple_testing") or {}).get("n_tests", 5)),
        "forward_start_date": forward_start,
        "message": (
            "No candidate is labeled STATISTICALLY VALIDATED on this forward sample. "
            if n_insuff == len(results)
            else "Forward running; none validated yet."
        ),
    }
    return {"rows": results, "summary": summary}
