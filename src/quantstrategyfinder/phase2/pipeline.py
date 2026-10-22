"""Phase 2 research pipeline with checkpoints (isolated outputs)."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import pandas as pd
import yaml

from quantstrategyfinder.analytics.metrics import compute_metrics
from quantstrategyfinder.data.sources import fetch_daily_ohlcv
from quantstrategyfinder.data.validation import DataValidationError
from quantstrategyfinder.engine.backtest import BacktestConfig, run_backtest
from quantstrategyfinder.engine.costs import CostModel
from quantstrategyfinder.persistence.repository import new_run_id
from quantstrategyfinder.pipeline import git_commit_short
from quantstrategyfinder.validation.splits import chronological_split

from .export import write_phase2_outputs
from .registry import SOURCE_CITATIONS, get_phase2_strategy
from .stats import benjamini_hochberg, bootstrap_excess_p, bootstrap_monthly_ci
from .universe import build_symbol_map, feasibility_constraints, periods_per_year

logger = logging.getLogger(__name__)


def load_phase2_config(path: str | Path = "configs/phase2.yaml") -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _cost_model(cfg: dict[str, Any], stress: float = 1.0) -> CostModel:
    c = dict(cfg.get("costs") or {})
    c["stress_multiplier"] = stress
    fields = CostModel.__dataclass_fields__
    return CostModel(**{k: c[k] for k in fields if k in c})


def _bah_equity(bars: pd.DataFrame, start: str, end: str, equity0: float) -> pd.Series:
    seg = bars.loc[start:end]
    if seg.empty:
        return pd.Series(dtype=float)
    closes = seg["Close"].astype(float)
    return (equity0 * (closes / float(closes.iloc[0]))).rename("bah")


def _oos_activity(fills: pd.DataFrame, start: str, end: str) -> int:
    if fills is None or fills.empty:
        return 0
    t = pd.to_datetime(fills["timestamp"], utc=True)
    t0 = pd.Timestamp(start, tz="UTC")
    t1 = pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1)
    return int(((t >= t0) & (t < t1)).sum())


def _evaluate_gates(
    *,
    row: dict[str, Any],
    cfg: dict[str, Any],
    bh_pass: bool,
) -> tuple[str, list[str]]:
    """Return board ('validated'|'experimental') and failure reasons."""
    v = cfg.get("validation") or {}
    reasons: list[str] = []
    oos_cagr = row.get("oos_cagr")
    oos_total = row.get("oos_total_return")
    if v.get("require_positive_oos_cagr", True):
        if oos_cagr is None or oos_total is None or oos_cagr <= 0 or oos_total <= 0:
            reasons.append("OOS CAGR/total return not positive after costs.")
    if v.get("require_beat_buy_and_hold", True):
        bah = row.get("benchmark_cagr")
        if bah is None or oos_cagr is None or oos_cagr <= bah:
            reasons.append("OOS CAGR does not exceed buy-and-hold on identical dates.")
    if v.get("require_monthly_ci_low_gt_0", True):
        ci_low = row.get("bootstrap_monthly_ci_low")
        if ci_low is None or ci_low <= 0:
            reasons.append(f"Bootstrap monthly-mean CI low not > 0 (ci_low={ci_low}).")
    min_bars = int(v.get("min_oos_bars", 126))
    if (row.get("oos_n_bars") or 0) < min_bars:
        reasons.append(f"OOS bars {(row.get('oos_n_bars') or 0)} < {min_bars}.")
    min_act = int(v.get("min_oos_activity", 10))
    if (row.get("oos_activity") or 0) < min_act:
        reasons.append(f"OOS activity {(row.get('oos_activity') or 0)} < {min_act}.")
    max_dd = float(v.get("max_oos_drawdown", 0.35))
    dd = row.get("oos_max_drawdown")
    if dd is not None and abs(dd) > max_dd:
        reasons.append(f"|OOS max DD| {abs(dd):.2%} > {max_dd:.0%}.")
    sharpe_2x = row.get("cost_stress_2x_val_sharpe")
    min_s = float(v.get("min_val_sharpe_at_2x_cost", -0.5))
    if sharpe_2x is not None and sharpe_2x < min_s:
        reasons.append(f"2× cost val Sharpe {sharpe_2x:.3f} < {min_s}.")
    if not row.get("feasible_200"):
        reasons.append("Not feasible on $200 cash-account assumptions: " + "; ".join(row.get("feasibility_reasons") or []))
    if not bh_pass:
        reasons.append("Failed Benjamini–Hochberg FDR control on excess-return bootstrap p-value.")
    if reasons:
        return "experimental", reasons
    return "validated", ["Passed all precommitted Phase 2 validated gates."]


def run_phase2_smoke(config_path: str = "configs/phase2.yaml") -> dict[str, Any]:
    cfg = load_phase2_config(config_path)
    smoke = cfg.get("smoke") or {}
    return run_phase2_pipeline(
        config_path=config_path,
        symbols=list(smoke.get("symbols") or ["SPY"]),
        strategy_ids=list(smoke.get("strategies") or ["ema_trend"]),
        tag="smoke",
    )


def run_phase2_pipeline(
    *,
    config_path: str = "configs/phase2.yaml",
    symbols: Optional[list[str]] = None,
    strategy_ids: Optional[list[str]] = None,
    tag: str = "full",
    resume: bool = True,
) -> dict[str, Any]:
    cfg = load_phase2_config(config_path)
    results_root = Path(cfg.get("results_dir", "reports/phase2"))
    results_root.mkdir(parents=True, exist_ok=True)
    run_id = f"phase2_{tag}_{new_run_id()}"
    out_dir = results_root / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    ckpt_path = out_dir / "checkpoint.jsonl"

    sym_map = build_symbol_map(cfg)
    if symbols is None:
        symbols = list(sym_map.keys())
    if strategy_ids is None:
        strategy_ids = list(cfg.get("strategies") or [])

    starting_equity = float(cfg.get("starting_equity", 200.0))
    split_cfg = cfg.get("splits") or {}
    val_cfg = cfg.get("validation") or {}
    cache_dir = cfg.get("cache_dir", "data/cache")
    lookback = int(cfg.get("lookback_years", 10))

    # Snapshot config
    (out_dir / "config_snapshot.yaml").write_text(
        yaml.dump({**cfg, "run_symbols": symbols, "run_strategies": strategy_ids}),
        encoding="utf-8",
    )

    # Fetch data
    provenance: dict[str, Any] = {}
    bars_by: dict[str, pd.DataFrame] = {}
    fetch_errors: dict[str, str] = {}
    for sym in symbols:
        try:
            bars, prov = fetch_daily_ohlcv(
                sym, lookback_years=lookback, cache_dir=cache_dir, force_refresh=False
            )
            bars_by[sym] = bars
            provenance[sym] = {
                **prov.to_dict(),
                "asset_class": sym_map.get(sym, "unknown"),
                "periods_per_year": periods_per_year(sym_map.get(sym, "equities"), cfg),
            }
            logger.info("Loaded %s (%d bars)", sym, len(bars))
        except Exception as exc:  # noqa: BLE001
            fetch_errors[sym] = str(exc)
            logger.error("Fetch failed %s: %s", sym, exc)

    (out_dir / "fetch_errors.json").write_text(json.dumps(fetch_errors, indent=2), encoding="utf-8")
    if not bars_by:
        raise DataValidationError("Phase 2: no symbols downloaded successfully.")

    # Resume set
    done: set[str] = set()
    rows: list[dict[str, Any]] = []
    if resume and ckpt_path.exists():
        for line in ckpt_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rec = json.loads(line)
            done.add(f"{rec['strategy_id']}::{rec['symbol']}")
            rows.append(rec)

    costs = _cost_model(cfg, 1.0)
    total = len(strategy_ids) * len(bars_by)
    completed = len(done)
    for sid in strategy_ids:
        strategy = get_phase2_strategy(sid)
        cite = SOURCE_CITATIONS.get(sid, {"source": sid, "url": "", "fidelity": "REIMPLEMENTATION"})
        for sym, bars in bars_by.items():
            key = f"{sid}::{sym}"
            if key in done:
                continue
            asset_class = sym_map.get(sym, "unknown")
            ppy = periods_per_year(asset_class, cfg)
            feas = feasibility_constraints(sym, asset_class, cfg)
            try:
                splits = chronological_split(
                    bars,
                    train_frac=float(split_cfg.get("train_frac", 0.5)),
                    val_frac=float(split_cfg.get("val_frac", 0.25)),
                    test_frac=float(split_cfg.get("test_frac", 0.25)),
                )
                result = run_backtest(
                    bars,
                    strategy,
                    config=BacktestConfig(
                        starting_equity=starting_equity, symbol=sym, costs=costs
                    ),
                )
                eq = result.equity_curve["equity"]
                test = splits.test
                t0, t1 = str(test.index[0].date()), str(test.index[-1].date())
                oos_eq = eq.reindex(test.index).dropna()
                if oos_eq.empty:
                    raise ValueError("Empty OOS equity")
                oos_metrics = compute_metrics(
                    oos_eq,
                    starting_equity=float(oos_eq.iloc[0]),
                    trades=result.trades,
                    fills=result.fills,
                    periods_per_year=ppy,
                )
                val_eq = eq.reindex(splits.val.index).dropna()
                # 2x cost stress on full path, measure val window
                stressed = run_backtest(
                    bars,
                    strategy,
                    config=BacktestConfig(
                        starting_equity=starting_equity,
                        symbol=sym,
                        costs=_cost_model(cfg, 2.0),
                    ),
                )
                val_st = stressed.equity_curve["equity"].reindex(splits.val.index).dropna()
                stress_m = (
                    compute_metrics(val_st, starting_equity=float(val_st.iloc[0]), periods_per_year=ppy)
                    if len(val_st) >= 2
                    else {}
                )
                bah = _bah_equity(bars, t0, t1, float(oos_eq.iloc[0]))
                bah_m = (
                    compute_metrics(bah, starting_equity=float(bah.iloc[0]), periods_per_year=ppy)
                    if len(bah) >= 2
                    else {}
                )
                ci = bootstrap_monthly_ci(
                    oos_eq,
                    n_boot=int(val_cfg.get("bootstrap_n", 1000)),
                    seed=int(val_cfg.get("bootstrap_seed", 42)),
                )
                excess_p = bootstrap_excess_p(
                    oos_eq,
                    bah,
                    n_boot=int(val_cfg.get("bootstrap_n", 1000)),
                    seed=int(val_cfg.get("bootstrap_seed", 42)),
                )
                activity = _oos_activity(result.fills, t0, t1)
                # $200 sim path = OOS equity already starts from continuous book; rebase to $200
                sim_eq = 200.0 * (oos_eq / float(oos_eq.iloc[0]))
                worst_dd_usd = float((sim_eq - sim_eq.cummax()).min()) if len(sim_eq) else None

                # Save equity artifact
                stem = f"{sid}_{sym.replace('=', '_').replace('/', '_')}"
                result.equity_curve.to_csv(out_dir / f"equity_{stem}.csv")
                if not result.fills.empty:
                    result.fills.to_csv(out_dir / f"fills_{stem}.csv", index=False)
                if not result.trades.empty:
                    result.trades.to_csv(out_dir / f"trades_{stem}.csv", index=False)

                rec = {
                    "run_id": run_id,
                    "strategy_id": sid,
                    "strategy_name": strategy.meta.name,
                    "strategy_description": strategy.meta.description,
                    "strategy_params": strategy.params,
                    "source": cite.get("source"),
                    "source_url": cite.get("url"),
                    "fidelity": cite.get("fidelity"),
                    "symbol": sym,
                    "asset_class": asset_class,
                    "periods_per_year": ppy,
                    "data_hash": provenance[sym].get("content_hash"),
                    "data_source": provenance[sym].get("source"),
                    "data_start": provenance[sym].get("start"),
                    "data_end": provenance[sym].get("end"),
                    "oos_start": t0,
                    "oos_end": t1,
                    "oos_n_bars": oos_metrics.get("n_observations"),
                    "oos_cagr": oos_metrics.get("cagr"),
                    "oos_total_return": oos_metrics.get("total_return"),
                    "oos_monthly_compounded_equivalent": oos_metrics.get(
                        "monthly_compounded_equivalent"
                    ),
                    "oos_actual_mean_monthly": oos_metrics.get("actual_mean_monthly_return"),
                    "oos_actual_median_monthly": oos_metrics.get("actual_median_monthly_return"),
                    "oos_max_drawdown": oos_metrics.get("max_drawdown"),
                    "oos_sharpe": oos_metrics.get("sharpe"),
                    "oos_sortino": oos_metrics.get("sortino"),
                    "oos_calmar": oos_metrics.get("calmar"),
                    "oos_win_rate": oos_metrics.get("win_rate"),
                    "oos_profit_factor": oos_metrics.get("profit_factor"),
                    "oos_n_trades": oos_metrics.get("n_trades"),
                    "oos_activity": activity,
                    "oos_turnover": oos_metrics.get("turnover_approx"),
                    "oos_worst_month": oos_metrics.get("worst_month"),
                    "oos_total_costs_note": oos_metrics.get("total_costs"),
                    "benchmark_cagr": bah_m.get("cagr"),
                    "benchmark_max_dd": bah_m.get("max_drawdown"),
                    "benchmark_total_return": bah_m.get("total_return"),
                    "excess_oos_cagr": (
                        None
                        if oos_metrics.get("cagr") is None or bah_m.get("cagr") is None
                        else float(oos_metrics["cagr"]) - float(bah_m["cagr"])
                    ),
                    "bootstrap_monthly_ci_low": ci.get("ci_low"),
                    "bootstrap_monthly_ci_high": ci.get("ci_high"),
                    "bootstrap_p_mean_le_0": ci.get("p_one_sided_mean_gt_0"),
                    "excess_bootstrap_p": excess_p.get("p_excess_le_0"),
                    "cost_stress_2x_val_sharpe": stress_m.get("sharpe"),
                    "feasible_200": feas["feasible_200"] and len(result.rejections) < 50,
                    "feasibility_reasons": feas["reasons"],
                    "sim_200_end_equity": float(sim_eq.iloc[-1]) if len(sim_eq) else None,
                    "sim_200_worst_dd_usd": worst_dd_usd,
                    "n_rejections": len(result.rejections),
                    "stem": stem,
                    "status": "ok",
                    "error": None,
                }
            except Exception as exc:  # noqa: BLE001
                logger.exception("Failed %s @ %s", sid, sym)
                rec = {
                    "run_id": run_id,
                    "strategy_id": sid,
                    "symbol": sym,
                    "asset_class": asset_class,
                    "status": "error",
                    "error": str(exc),
                    "feasible_200": False,
                    "feasibility_reasons": [str(exc)],
                    "board": "experimental",
                    "failure_reasons": [f"Runtime error: {exc}"],
                    "label": "UNVALIDATED — RESEARCH ONLY",
                }
            rows.append(rec)
            with ckpt_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, default=str) + "\n")
            completed += 1
            if completed % 10 == 0 or completed == total:
                logger.info("Progress %d/%d", completed, total)

    # BH-FDR across successful pairs with excess p-values
    pvals = [
        (f"{r['strategy_id']}::{r['symbol']}", r.get("excess_bootstrap_p"))
        for r in rows
        if r.get("status") == "ok"
    ]
    bh = benjamini_hochberg(pvals, q=float(val_cfg.get("bh_fdr_q", 0.10)))

    for r in rows:
        if r.get("status") != "ok":
            continue
        key = f"{r['strategy_id']}::{r['symbol']}"
        board, reasons = _evaluate_gates(row=r, cfg=cfg, bh_pass=bool(bh.get(key)))
        r["bh_fdr_pass"] = bool(bh.get(key))
        r["board"] = board
        r["failure_reasons"] = reasons
        r["label"] = (
            "STATISTICALLY VALIDATED"
            if board == "validated"
            else "UNVALIDATED — RESEARCH ONLY"
        )

    summary = {
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": git_commit_short(),
        "tag": tag,
        "n_strategies": len(strategy_ids),
        "n_symbols_requested": len(symbols),
        "n_symbols_loaded": len(bars_by),
        "n_combinations_attempted": len(strategy_ids) * len(bars_by),
        "n_combinations_ok": sum(1 for r in rows if r.get("status") == "ok"),
        "n_validated": sum(1 for r in rows if r.get("board") == "validated"),
        "n_experimental": sum(1 for r in rows if r.get("board") == "experimental"),
        "fetch_errors": fetch_errors,
        "artifact_dir": str(out_dir),
        "holdout_note": (
            "Final OOS (test) window inspected once for this run. Further claims require a new "
            "future holdout or paper-trading period."
        ),
        "gates": val_cfg,
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    (out_dir / "provenance.json").write_text(json.dumps(provenance, indent=2), encoding="utf-8")

    paths = write_phase2_outputs(out_dir, rows, provenance, summary)
    summary["output_files"] = {k: str(v) for k, v in paths.items()}
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    # pointer
    (results_root / "latest.json").write_text(
        json.dumps({"run_id": run_id, "dir": str(out_dir), **{k: summary[k] for k in (
            "n_validated", "n_experimental", "n_combinations_ok", "n_strategies", "n_symbols_loaded"
        )}}, indent=2),
        encoding="utf-8",
    )
    return summary
