"""P1 post-hoc audit of frozen eval artifacts (no strategy/param changes)."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd
import yaml

from quantstrategyfinder.analytics.metrics import compute_metrics, max_drawdown, monthly_returns
from quantstrategyfinder.data.cache import cache_paths, load_cached_bars


COST_ASSUMPTIONS = (
    "commission_per_trade=0; commission_pct=0; spread_bps=2; slippage_bps=5; "
    "fills at next-bar open ± half-spread+slippage; fractional shares allowed; min_notional=$1."
)

DEVIATION_NOTE = (
    "Fidelity=REIMPLEMENTATION: first-party rule-family adapter; upstream repo code was never "
    "executed. Parameters are adapter defaults, not reverse-engineered from upstream. "
    "Heuristic repo↔adapter mapping may not match the original author's exact rules."
)


def _bootstrap_ci(
    returns: pd.Series,
    *,
    n_boot: int = 2000,
    alpha: float = 0.05,
    seed: int = 42,
) -> dict[str, Any]:
    """Bootstrap CI for mean return (and compounded path total return over same length)."""
    r = returns.dropna().astype(float).values
    if len(r) < 8:
        return {
            "n": int(len(r)),
            "mean": float(np.mean(r)) if len(r) else None,
            "ci_low": None,
            "ci_high": None,
            "total_return_ci_low": None,
            "total_return_ci_high": None,
            "note": "Insufficient observations for bootstrap CI (need >= 8).",
        }
    rng = np.random.default_rng(seed)
    means = []
    totals = []
    n = len(r)
    for _ in range(n_boot):
        sample = rng.choice(r, size=n, replace=True)
        means.append(float(np.mean(sample)))
        totals.append(float(np.prod(1.0 + sample) - 1.0))
    lo, hi = alpha / 2, 1 - alpha / 2
    return {
        "n": n,
        "mean": float(np.mean(r)),
        "ci_low": float(np.quantile(means, lo)),
        "ci_high": float(np.quantile(means, hi)),
        "total_return_ci_low": float(np.quantile(totals, lo)),
        "total_return_ci_high": float(np.quantile(totals, hi)),
        "note": f"{int((1-alpha)*100)}% bootstrap CI on mean period return and path total return "
        f"(n_boot={n_boot}, seed={seed}). Not a guarantee of live edge.",
    }


def _bah_metrics(bars: pd.DataFrame, start: str, end: str, starting_equity: float = 200.0) -> dict[str, Any]:
    """Buy-and-hold on close-to-close over [start, end] inclusive (matched calendar)."""
    seg = bars.loc[start:end]
    if seg.empty or len(seg) < 2:
        return {
            "benchmark_cagr": None,
            "benchmark_max_dd": None,
            "benchmark_total_return": None,
            "benchmark_n_bars": int(len(seg)),
            "benchmark_note": "Insufficient bars for buy-and-hold benchmark.",
        }
    # Simple BAH: buy at first open, mark equity with close (ignore costs for benchmark clarity;
    # note separately that strategy costs are modeled but BAH here is price-path only).
    closes = seg["Close"].astype(float)
    eq = starting_equity * (closes / float(closes.iloc[0]))
    m = compute_metrics(eq, starting_equity=starting_equity)
    return {
        "benchmark_cagr": m.get("cagr"),
        "benchmark_max_dd": m.get("max_drawdown"),
        "benchmark_total_return": m.get("total_return"),
        "benchmark_n_bars": int(len(seg)),
        "benchmark_note": (
            "Buy-and-hold close path on identical OOS dates; costs not deducted on benchmark "
            "(strategy costs are modeled separately)."
        ),
    }


def _estimate_costs_from_fills(
    fills_path: Path,
    bars: pd.DataFrame,
    *,
    start: Optional[str] = None,
    end: Optional[str] = None,
) -> dict[str, Any]:
    if not fills_path.exists():
        return {
            "explicit_commission": 0.0,
            "implied_spread_slippage": None,
            "estimated_total_costs": None,
            "n_fills_window": 0,
            "cost_note": "No fills file.",
        }
    fills = pd.read_csv(fills_path)
    if fills.empty:
        return {
            "explicit_commission": 0.0,
            "implied_spread_slippage": 0.0,
            "estimated_total_costs": 0.0,
            "n_fills_window": 0,
            "cost_note": "Empty fills.",
        }
    fills["timestamp"] = pd.to_datetime(fills["timestamp"], utc=True)
    if start and end:
        t0 = pd.Timestamp(start, tz="UTC")
        t1 = pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1)
        fills = fills[(fills["timestamp"] >= t0) & (fills["timestamp"] < t1)]
    commission = float(fills["commission"].sum()) if "commission" in fills.columns else 0.0
    implied = 0.0
    matched = 0
    for _, row in fills.iterrows():
        ts = row["timestamp"]
        if ts not in bars.index:
            # nearest prior bar
            idx = bars.index.get_indexer([ts], method="nearest")
            if idx[0] < 0:
                continue
            mid = float(bars.iloc[idx[0]]["Open"])
        else:
            mid = float(bars.loc[ts, "Open"])
        qty = float(row["qty"])
        px = float(row["price"])
        implied += abs(px - mid) * qty
        matched += 1
    return {
        "explicit_commission": commission,
        "implied_spread_slippage": implied,
        "estimated_total_costs": commission + implied,
        "n_fills_window": int(len(fills)),
        "n_fills_matched_mid": matched,
        "cost_note": COST_ASSUMPTIONS
        + " Implied spread/slippage = sum(|fill−open_mid|×qty) in window.",
    }


def _pass_justified(row: dict[str, Any], val_cfg: dict[str, Any]) -> dict[str, Any]:
    """Re-check PASS against recorded metrics and configured gates (no re-optimization)."""
    status = row.get("status")
    mv = row.get("metrics_val") or {}
    mt = row.get("metrics_test") or {}
    reasons = list(row.get("reasons") or [])
    checks = []
    ok = True

    def add(name: str, passed: bool, detail: str) -> None:
        nonlocal ok
        checks.append({"check": name, "passed": passed, "detail": detail})
        if not passed:
            ok = False

    if status == "PASS":
        n_val = mv.get("n_observations") or 0
        n_test = mt.get("n_observations") or 0
        soft_min = max(30, int(val_cfg.get("min_bars", 252)) // 4)
        add("sample_size", min(n_val, n_test) >= soft_min, f"val={n_val} test={n_test} soft_min={soft_min}")
        n_trades = (mv.get("n_trades") or 0) + (mt.get("n_trades") or 0)
        add("min_trades", n_trades >= int(val_cfg.get("min_trades", 5)), f"val+test trades={n_trades}")
        sharpe = mv.get("sharpe")
        add(
            "min_val_sharpe",
            sharpe is not None and sharpe >= float(val_cfg.get("min_val_sharpe", -0.5)),
            f"val_sharpe={sharpe}",
        )
        dd_fail = float(val_cfg.get("max_drawdown_fail", 0.5))
        for label, m in (("val", mv), ("test", mt)):
            dd = m.get("max_drawdown")
            add(
                f"{label}_dd_gate",
                dd is None or abs(dd) <= dd_fail,
                f"{label}_max_dd={dd} fail_at={dd_fail}",
            )
        add(
            "eligibility_flag",
            bool(row.get("eligible_for_ranking")),
            f"eligible_for_ranking={row.get('eligible_for_ranking')}",
        )
    else:
        checks.append(
            {
                "check": "status_not_pass",
                "passed": True,
                "detail": f"status={status}; reasons={reasons}",
            }
        )

    return {
        "pass_status": status,
        "pass_justified": ok if status == "PASS" else None,
        "pass_checks": checks,
        "pass_disclaimer": (
            "PASS means hard validation gates were met (sample size, trades, costs modeled, "
            "look-ahead-free engine convention, validation risk/Sharpe thresholds). "
            "PASS does NOT mean proven profitability, live edge, or outperformance of buy-and-hold."
        ),
    }


def _bias_findings(row: dict[str, Any], result: dict[str, Any]) -> list[str]:
    findings = [
        "Order timing: signals from close; fills at next open (engine) — standard no-lookahead fill convention.",
        "Indicators using shift(1) on Donchian/Turtle-style channels avoid same-bar high/low look-ahead; "
        "SMA/EMA/RSI/MACD use same-bar close (signal still filled next open).",
        "Train/val/test are chronological 50/25/25 on one continuous book; parameters were not optimized "
        "on the locked test set in this pipeline.",
        "Survivorship: Yahoo symbols SPY/QQQ/GLD/TLT/BTC-USD are surviving liquid instruments; "
        "no delisted-universe correction — equity/ETF survivorship bias not fully mitigated.",
        "Adapter fidelity is REIMPLEMENTATION with heuristic repo mapping — selection of which "
        "rule-family to attach is a form of researcher degrees of freedom (multiple-testing risk).",
        "Annualization uses periods_per_year=252 for all symbols including BTC-USD (24/7); "
        "crypto annualization may be slightly mis-specified vs calendar-day conventions.",
    ]
    mt = row.get("metrics_test") or {}
    n_tr = mt.get("n_trades") or 0
    n_obs = mt.get("n_observations") or 0
    if n_tr < 5:
        findings.append(f"FLAG: OOS trade count low (n_trades={n_tr}) — statistical reliability weak.")
    if n_obs < 126:
        findings.append(f"FLAG: OOS bars < ~6 months of sessions (n={n_obs}) — insufficient sample.")
    wf = row.get("walkforward") or {}
    if wf.get("mean_sharpe") is not None and wf.get("mean_sharpe") < 0:
        findings.append(
            f"FLAG: walk-forward mean Sharpe negative ({wf.get('mean_sharpe'):.3f}) — unstable path."
        )
    return findings


def _credible_positive(
    *,
    oos_cagr: Optional[float],
    oos_total: Optional[float],
    bench_cagr: Optional[float],
    oos_dd: Optional[float],
    ci: dict[str, Any],
    stress: dict[str, Any],
    n_trades_oos: int,
    n_obs: int,
) -> tuple[bool, str]:
    """Require positive OOS return, not worse DD than -50% already gated, and some statistical support."""
    reasons = []
    if oos_cagr is None or oos_total is None:
        return False, "Missing OOS return metrics."
    if oos_total <= 0 or oos_cagr <= 0:
        return False, "OOS total return or CAGR not positive."
    if bench_cagr is not None and oos_cagr <= bench_cagr:
        reasons.append(
            f"OOS CAGR {oos_cagr:.4f} does not exceed buy-and-hold CAGR {bench_cagr:.4f}."
        )
    # CI on monthly mean: prefer lower bound > 0; else weak
    ci_low = ci.get("ci_low")
    if ci_low is None:
        reasons.append("Bootstrap CI unavailable (small sample).")
    elif ci_low <= 0:
        reasons.append(f"Bootstrap mean-monthly CI lower bound <= 0 ({ci_low:.4f}).")
    if n_trades_oos < 5:
        reasons.append(f"OOS trades={n_trades_oos} < 5.")
    if n_obs < 126:
        reasons.append(f"OOS bars={n_obs} insufficient.")
    # Cost stress: 3x should not flip val sharpe deeply negative if we claim robustness
    s3 = (stress or {}).get("3.0x") or {}
    if s3.get("val_sharpe") is not None and s3["val_sharpe"] < -0.5:
        reasons.append(f"3× cost stress val Sharpe {s3['val_sharpe']:.3f} < -0.5.")
    if oos_dd is not None and abs(oos_dd) > 0.35:
        reasons.append(f"OOS max DD {oos_dd:.2%} severe for $200 account suitability.")

    # Credible edge over benchmark requires beating BAH and CI support
    beats_bah = bench_cagr is None or oos_cagr > bench_cagr
    ci_ok = ci_low is not None and ci_low > 0
    if beats_bah and ci_ok and n_trades_oos >= 5 and n_obs >= 126 and not reasons:
        return True, "Positive OOS CAGR above BAH with monthly-mean CI>0 and adequate sample."
    if beats_bah and ci_ok and n_trades_oos >= 5 and n_obs >= 126:
        # only soft reasons like DD
        soft_only = all("max DD" in r or "3×" in r for r in reasons) if reasons else True
        if soft_only and (oos_dd is None or abs(oos_dd) <= 0.35):
            return True, "Positive OOS vs BAH with CI>0; " + "; ".join(reasons) if reasons else "ok"
    return False, "No statistically defensible advantage: " + (
        "; ".join(reasons) if reasons else "failed positive-OOS gates"
    )


def build_p1_audit(
    *,
    run_id: str = "20261022T011911Z_9bbd8eb2",
    reports_dir: str | Path = "reports",
    cache_dir: str | Path = "data/cache",
    config_path: str = "configs/default.yaml",
) -> tuple[pd.DataFrame, dict[str, Any]]:
    reports_dir = Path(reports_dir)
    art = reports_dir / run_id
    summary = json.loads((art / "summary.json").read_text(encoding="utf-8"))
    cfg = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
    val_cfg = cfg.get("validation") or {}
    starting_equity = float(summary.get("starting_equity", 200.0))

    # Load bars once per symbol
    bars_by_sym: dict[str, pd.DataFrame] = {}
    prov_by_sym: dict[str, dict] = summary.get("provenance") or {}
    for sym in summary.get("symbols") or []:
        bars_path, prov_path = cache_paths(Path(cache_dir), sym, "1d")
        if bars_path.exists() and prov_path.exists():
            bars, _ = load_cached_bars(bars_path, prov_path)
            bars_by_sym[sym] = bars

    rows_out: list[dict[str, Any]] = []
    for row in summary.get("leaderboard") or []:
        sid = row["strategy_id"]
        sym = row["symbol"]
        stem = f"adapter_{sid}_{sym}"
        result_path = art / f"result_{stem}.json"
        result = json.loads(result_path.read_text(encoding="utf-8")) if result_path.exists() else {}
        strat = result.get("strategy") or {}
        attr = row.get("attribution") or result.get("attribution") or {}
        split = (result.get("split") or {}).get("test") or {}
        test_start, test_end = split.get("start"), split.get("end")
        mt = row.get("metrics_test") or {}
        mv = row.get("metrics_val") or {}
        fm = row.get("full_sample_metrics") or {}

        bars = bars_by_sym.get(sym)
        bah = (
            _bah_metrics(bars, test_start, test_end, starting_equity)
            if bars is not None and test_start and test_end
            else {
                "benchmark_cagr": None,
                "benchmark_max_dd": None,
                "benchmark_total_return": None,
                "benchmark_n_bars": None,
                "benchmark_note": "Bars unavailable.",
            }
        )

        # OOS equity path for CI
        eq_path = art / f"equity_{stem}.csv"
        ci = {"n": 0, "ci_low": None, "ci_high": None, "note": "No equity file"}
        oos_eq = pd.Series(dtype=float)
        if eq_path.exists() and test_start and test_end:
            eq_df = pd.read_csv(eq_path, parse_dates=["Date"], index_col="Date")
            if eq_df.index.tz is None:
                eq_df.index = eq_df.index.tz_localize("UTC")
            oos_eq = eq_df["equity"].loc[test_start:test_end].astype(float)
            mrets = monthly_returns(oos_eq)
            ci = _bootstrap_ci(mrets)

        costs = _estimate_costs_from_fills(
            art / f"fills_{stem}.csv",
            bars if bars is not None else pd.DataFrame(),
            start=test_start,
            end=test_end,
        )
        # Also full-sample cost estimate for transparency
        costs_full = _estimate_costs_from_fills(
            art / f"fills_{stem}.csv",
            bars if bars is not None else pd.DataFrame(),
        )

        pass_info = _pass_justified(row, val_cfg)
        bias = _bias_findings(row, result)

        oos_cagr = mt.get("cagr")
        oos_total = mt.get("total_return")
        # Activity in OOS: closed trades with entry in window undercounts holds opened earlier.
        # Also count fills in the OOS window from the ledger.
        n_trades_oos = int(mt.get("n_trades") or 0)
        n_fills_oos = int(costs.get("n_fills_window") or 0)
        n_activity_oos = max(n_trades_oos, n_fills_oos)  # fills imply rebalances in window

        credible, credible_reason = _credible_positive(
            oos_cagr=oos_cagr,
            oos_total=oos_total,
            bench_cagr=bah.get("benchmark_cagr"),
            oos_dd=mt.get("max_drawdown"),
            ci=ci,
            stress=row.get("cost_stress_val") or {},
            n_trades_oos=n_activity_oos,
            n_obs=int(mt.get("n_observations") or 0),
        )

        # Rank score for credible set: excess CAGR vs BAH, then lower |DD|
        excess_cagr = None
        if oos_cagr is not None and bah.get("benchmark_cagr") is not None:
            excess_cagr = float(oos_cagr) - float(bah["benchmark_cagr"])

        stress = row.get("cost_stress_val") or {}
        insufficient = []
        if (mt.get("n_observations") or 0) < 126:
            insufficient.append("oos_bars<126")
        if n_activity_oos < 5:
            insufficient.append("oos_activity<5")
        if ci.get("ci_low") is None:
            insufficient.append("no_bootstrap_ci")

        rows_out.append(
            {
                "run_id": run_id,
                "strategy_id": sid,
                "strategy_name": strat.get("name") or sid,
                "symbol": sym,
                "github_repo": attr.get("source_repo"),
                "github_url": attr.get("source_url"),
                "source_commit": attr.get("source_commit"),
                "license_spdx": attr.get("license_spdx"),
                "fidelity": attr.get("fidelity") or "REIMPLEMENTATION",
                "trading_rules": strat.get("description"),
                "strategy_params": json.dumps(strat.get("params") or {}, sort_keys=True),
                "rule_match_notes": DEVIATION_NOTE,
                "data_source": (prov_by_sym.get(sym) or {}).get("source", "yfinance"),
                "data_interval": "1d",
                "data_adjusted": (prov_by_sym.get(sym) or {}).get("adjusted"),
                "data_hash": (prov_by_sym.get(sym) or {}).get("content_hash") or row.get("data_hash"),
                "full_period_start": (prov_by_sym.get(sym) or {}).get("start"),
                "full_period_end": (prov_by_sym.get(sym) or {}).get("end"),
                "oos_start": test_start,
                "oos_end": test_end,
                "oos_n_bars": mt.get("n_observations"),
                "oos_cagr": oos_cagr,
                "oos_monthly_compounded_equivalent": mt.get("monthly_compounded_equivalent"),
                "oos_actual_mean_monthly_return": mt.get("actual_mean_monthly_return"),
                "oos_actual_median_monthly_return": mt.get("actual_median_monthly_return"),
                "oos_total_return": oos_total,
                "oos_max_drawdown": mt.get("max_drawdown"),
                "oos_sharpe": mt.get("sharpe"),
                "oos_sortino": mt.get("sortino"),
                "oos_profit_factor": mt.get("profit_factor"),
                "oos_win_rate": mt.get("win_rate"),
                "oos_n_trades": mt.get("n_trades"),
                "oos_n_fills_metric": mt.get("n_fills"),
                "oos_n_fills_window": n_fills_oos,
                "oos_activity_count": n_activity_oos,
                "val_sharpe": mv.get("sharpe"),
                "val_max_drawdown": mv.get("max_drawdown"),
                "val_total_return": mv.get("total_return"),
                "full_cagr": fm.get("cagr"),
                "full_max_drawdown": fm.get("max_drawdown"),
                "full_n_trades": fm.get("n_trades"),
                "estimated_oos_trading_costs_usd": costs.get("estimated_total_costs"),
                "oos_explicit_commission": costs.get("explicit_commission"),
                "oos_implied_spread_slippage": costs.get("implied_spread_slippage"),
                "estimated_full_trading_costs_usd": costs_full.get("estimated_total_costs"),
                "cost_assumptions": COST_ASSUMPTIONS,
                "cost_stress_2x_val_sharpe": (stress.get("2.0x") or {}).get("val_sharpe"),
                "cost_stress_2x_val_total_return": (stress.get("2.0x") or {}).get("val_total_return"),
                "cost_stress_2x_val_max_dd": (stress.get("2.0x") or {}).get("val_max_dd"),
                "cost_stress_3x_val_sharpe": (stress.get("3.0x") or {}).get("val_sharpe"),
                "cost_stress_3x_val_total_return": (stress.get("3.0x") or {}).get("val_total_return"),
                "cost_stress_3x_val_max_dd": (stress.get("3.0x") or {}).get("val_max_dd"),
                "bootstrap_monthly_mean": ci.get("mean"),
                "bootstrap_monthly_mean_ci_low": ci.get("ci_low"),
                "bootstrap_monthly_mean_ci_high": ci.get("ci_high"),
                "bootstrap_oos_total_return_ci_low": ci.get("total_return_ci_low"),
                "bootstrap_oos_total_return_ci_high": ci.get("total_return_ci_high"),
                "bootstrap_note": ci.get("note"),
                "benchmark_cagr": bah.get("benchmark_cagr"),
                "benchmark_max_dd": bah.get("benchmark_max_dd"),
                "benchmark_total_return": bah.get("benchmark_total_return"),
                "excess_oos_cagr_vs_bah": excess_cagr,
                "benchmark_note": bah.get("benchmark_note"),
                "validation_status": row.get("status"),
                "eligible_for_ranking": row.get("eligible_for_ranking"),
                "pass_justified": pass_info.get("pass_justified"),
                "pass_disclaimer": pass_info.get("pass_disclaimer"),
                "pass_checks_json": json.dumps(pass_info.get("pass_checks")),
                "feasibility_200": row.get("feasibility_200"),
                "feasibility_reason": (
                    "yes — fractional shares + min notional $1; no hard cash/margin failures recorded"
                    if row.get("feasibility_200")
                    else f"no — rejections={row.get('n_rejections')}; check result JSON"
                ),
                "insufficient_sample_flags": ";".join(insufficient) if insufficient else "",
                "bias_findings": " | ".join(bias),
                "credible_positive_oos": credible,
                "credible_reason": credible_reason,
                "validation_reasons": " | ".join(row.get("reasons") or []),
            }
        )

    df = pd.DataFrame(rows_out)

    # Rank only credible positive OOS: by excess CAGR then milder DD
    cred = df[df["credible_positive_oos"] == True].copy()  # noqa: E712
    if not cred.empty:
        cred = cred.sort_values(
            by=["excess_oos_cagr_vs_bah", "oos_max_drawdown", "oos_sharpe"],
            ascending=[False, False, False],  # max_dd is negative; False sorts -5% before -20%
        )
        cred["audit_rank"] = range(1, len(cred) + 1)
        rank_map = dict(zip(zip(cred["strategy_id"], cred["symbol"]), cred["audit_rank"]))
        df["audit_rank"] = [
            rank_map.get((r.strategy_id, r.symbol)) for r in df.itertuples()
        ]
    else:
        df["audit_rank"] = None

    # Also provide a display ordering for all 50: credible first, then by excess CAGR
    df["_sort_cred"] = df["credible_positive_oos"].astype(int)
    df["_sort_excess"] = df["excess_oos_cagr_vs_bah"].fillna(-999)
    df = df.sort_values(
        by=["_sort_cred", "_sort_excess", "oos_cagr"],
        ascending=[False, False, False],
    ).drop(columns=["_sort_cred", "_sort_excess"])

    n_pass = int((df["validation_status"] == "PASS").sum())
    pass_mask = df["validation_status"] == "PASS"
    n_pass_justified = int(
        df.loc[pass_mask, "pass_justified"].map(lambda x: bool(x) if pd.notna(x) else False).sum()
    )
    n_credible = int(df["credible_positive_oos"].sum())

    meta = {
        "run_id": run_id,
        "n_rows": int(len(df)),
        "n_pass": n_pass,
        "n_pass_justified": n_pass_justified,
        "n_credible_positive_oos": n_credible,
        "message": (
            None
            if n_credible > 0
            else "NO STRATEGY SHOWED A STATISTICALLY DEFENSIBLE OOS EDGE OVER BUY-AND-HOLD"
        ),
        "pass_disclaimer": (
            "PASS ≠ proven profitability. PASS only indicates validation gates were met."
        ),
        "cost_assumptions": COST_ASSUMPTIONS,
        "fidelity_note": DEVIATION_NOTE,
    }
    return df, meta


def write_p1_audit_outputs(
    *,
    run_id: str = "20261022T011911Z_9bbd8eb2",
    reports_dir: str | Path = "reports",
    docs_csv: str | Path = "/cursor/stores/self/docs/p1-audit-report.csv",
    docs_md: str | Path = "/cursor/stores/self/docs/p1-audit-summary.md",
) -> dict[str, Any]:
    df, meta = build_p1_audit(run_id=run_id, reports_dir=reports_dir)
    reports_dir = Path(reports_dir)
    out_dir = reports_dir / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "p1_audit_report.csv"
    meta_path = out_dir / "p1_audit_meta.json"
    df.to_csv(csv_path, index=False)
    # also top-level reports copy for easy download
    reports_dir.joinpath("p1_audit_report.csv").write_bytes(csv_path.read_bytes())

    docs_csv = Path(docs_csv)
    docs_md = Path(docs_md)
    docs_csv.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(docs_csv, index=False)

    top = df[df["credible_positive_oos"] == True].head(5)  # noqa: E712
    # For $200 suitability among credible (or among PASS with positive OOS if none credible)
    pool = df[df["credible_positive_oos"] == True].copy()  # noqa: E712
    if pool.empty:
        pool = df[
            (df["validation_status"] == "PASS")
            & (df["oos_cagr"].fillna(-1) > 0)
            & (df["feasibility_200"] == True)  # noqa: E712
        ].copy()
        pool_note = (
            "No statistically defensible edge vs BAH; showing least-bad PASS+positive-OOS "
            "feasible candidates for operational discussion only — NOT a recommendation."
        )
    else:
        pool_note = "Among credible-positive-OOS set."

    best_200 = None
    if not pool.empty:
        # Prefer milder DD, still positive excess if available, fractional OK
        pool = pool.sort_values(
            by=["feasibility_200", "oos_max_drawdown", "excess_oos_cagr_vs_bah"],
            ascending=[False, False, False],
        )
        best_200 = pool.iloc[0].to_dict()

    # Markdown summary
    lines = [
        "# P1 Audit Summary",
        "",
        f"**Eval run:** `{run_id}`  ",
        f"**Rows audited:** {meta['n_rows']}  ",
        f"**Validation PASS:** {meta['n_pass']} (justified by gates: {meta['n_pass_justified']})  ",
        f"**Credible positive OOS vs buy-and-hold (CI-supported):** {meta['n_credible_positive_oos']}  ",
        "",
        f"> {meta['pass_disclaimer']}",
        "",
    ]
    if meta.get("message"):
        lines += [f"**Finding:** {meta['message']}", ""]

    lines += [
        "## Ranking rule (audit)",
        "",
        "Rank **only** rows with: OOS CAGR>0, OOS CAGR > buy-and-hold CAGR on identical dates, "
        "bootstrap 95% CI lower bound on mean monthly return > 0, OOS trades≥5, OOS bars≥126, "
        "and OOS max DD not worse than −35%. Sort by excess OOS CAGR, then milder drawdown.",
        "",
        "## Top strategies (credible set)",
        "",
    ]
    # Informational nearest misses (NOT an endorsement)
    near = df[(df["validation_status"] == "PASS") & (df["oos_cagr"].fillna(-1) > 0)].copy()
    near = near.sort_values("excess_oos_cagr_vs_bah", ascending=False).head(5)

    if top.empty:
        lines.append("_None met the credible-positive-OOS bar._")
        lines.append("")
        lines.append("### Informational nearest misses (NOT endorsed)")
        lines.append("")
        lines.append(
            "These beat or approach buy-and-hold on point-estimate OOS CAGR but **fail** "
            "the audit’s statistical / activity gates (CI, trades, etc.)."
        )
        lines.append("")
        if near.empty:
            lines.append("_None._")
        else:
            lines.append(
                "| Strategy | Symbol | OOS CAGR | BAH CAGR | Excess | Actual mean monthly | "
                "Max DD | Sharpe | OOS activity | CI low (monthly mean) | Why not credible |"
            )
            lines.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|")
            for _, r in near.iterrows():
                lines.append(
                    f"| {r['strategy_id']} | {r['symbol']} | {_pct(r['oos_cagr'])} "
                    f"| {_pct(r['benchmark_cagr'])} | {_pct(r['excess_oos_cagr_vs_bah'])} "
                    f"| {_pct(r['oos_actual_mean_monthly_return'])} | {_pct(r['oos_max_drawdown'])} "
                    f"| {_num(r['oos_sharpe'])} | {int(r['oos_activity_count'] or 0)} "
                    f"| {_pct(r['bootstrap_monthly_mean_ci_low']) if isinstance(r['bootstrap_monthly_mean_ci_low'], float) else _num(r['bootstrap_monthly_mean_ci_low'])} "
                    f"| {r['credible_reason']} |"
                )
        lines.append("")
    else:
        lines.append(
            "| Rank | Strategy | Symbol | OOS CAGR | Monthly equiv (from CAGR) | "
            "Actual mean monthly | Max DD | Sharpe | Excess vs BAH | Repo |"
        )
        lines.append("|---:|---|---|---:|---:|---:|---:|---:|---:|---|")
        for _, r in top.iterrows():
            lines.append(
                f"| {int(r['audit_rank']) if pd.notna(r['audit_rank']) else ''} "
                f"| {r['strategy_id']} | {r['symbol']} "
                f"| {_pct(r['oos_cagr'])} | {_pct(r['oos_monthly_compounded_equivalent'])} "
                f"| {_pct(r['oos_actual_mean_monthly_return'])} | {_pct(r['oos_max_drawdown'])} "
                f"| {_num(r['oos_sharpe'])} | {_pct(r['excess_oos_cagr_vs_bah'])} "
                f"| {r['github_url']} |"
            )
        lines.append("")
        lines.append(
            "Note: **Monthly equiv (from CAGR)** = `(1+CAGR)^(1/12)-1` — **not** an observed monthly return. "
            "**Actual mean monthly** is from calendar month equity endpoints."
        )
        lines.append("")

    lines += ["## $200 account suitability", "", pool_note, ""]
    if best_200:
        lines += [
            f"- **Candidate:** `{best_200['strategy_id']}` @ `{best_200['symbol']}`",
            f"- Feasible: **{best_200['feasibility_reason']}**",
            f"- OOS CAGR: {_pct(best_200['oos_cagr'])}; Max DD: {_pct(best_200['oos_max_drawdown'])}; "
            f"Sharpe: {_num(best_200['oos_sharpe'])}",
            f"- Excess CAGR vs BAH: {_pct(best_200['excess_oos_cagr_vs_bah'])}",
            f"- Credible positive OOS: **{best_200['credible_positive_oos']}** — {best_200['credible_reason']}",
            f"- Fidelity: {best_200['fidelity']} — {DEVIATION_NOTE}",
            "",
        ]
    else:
        lines.append("No suitable $200 candidate under audit rules.")
        lines.append("")

    lines += [
        "## Bias / methodology checks",
        "",
        "- Look-ahead: next-bar-open fills; channel strategies use prior-bar extremes.",
        "- Leakage: chronological split; test not used for parameter search in this pipeline.",
        "- Survivorship: liquid surviving symbols only (Yahoo); not a full point-in-time universe.",
        "- Overfitting: adapter defaults + heuristic repo mapping introduce selection risk; "
        "multiple-testing across 50 pairs not fully corrected.",
        "- Annualization: 252 for all markets including BTC-USD.",
        "",
        f"## Artifacts",
        "",
        f"- CSV: `{csv_path}`",
        f"- Copy: `{docs_csv}`",
        f"- This summary: `{docs_md}`",
        "",
    ]
    docs_md.write_text("\n".join(lines), encoding="utf-8")
    meta_path.write_text(
        json.dumps({**meta, "best_200": _safe(best_200), "csv": str(csv_path)}, indent=2, default=str),
        encoding="utf-8",
    )
    return {
        **meta,
        "csv_path": str(csv_path),
        "reports_csv": str(reports_dir / "p1_audit_report.csv"),
        "docs_csv": str(docs_csv),
        "docs_md": str(docs_md),
        "best_200": _safe(best_200),
        "top5": top.head(5).to_dict(orient="records"),
    }


def _pct(x: Any) -> str:
    if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return "N/A"
    try:
        return f"{float(x):.2%}"
    except (TypeError, ValueError):
        return "N/A"


def _num(x: Any) -> str:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "N/A"
    try:
        return f"{float(x):.3f}"
    except (TypeError, ValueError):
        return "N/A"


def _safe(d: Optional[dict]) -> Optional[dict]:
    if d is None:
        return None
    out = {}
    for k, v in d.items():
        if isinstance(v, (np.floating, np.integer)):
            out[k] = float(v)
        elif isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            out[k] = None
        else:
            out[k] = v
    return out
