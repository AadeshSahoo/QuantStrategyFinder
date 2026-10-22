"""Evaluate APPROVED first-party adapters only (never upstream code)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from quantstrategyfinder.analytics.metrics import compute_metrics
from quantstrategyfinder.data.sources import fetch_universe
from quantstrategyfinder.engine.backtest import BacktestConfig, run_backtest
from quantstrategyfinder.engine.costs import CostModel
from quantstrategyfinder.persistence.repository import RunRepository
from quantstrategyfinder.pipeline import git_commit_short, load_config
from quantstrategyfinder.reporting.export import export_run_bundle
from quantstrategyfinder.strategies.adapters import ADAPTER_REGISTRY, get_adapter
from quantstrategyfinder.validation.robustness import evaluate_candidate
from quantstrategyfinder.validation.splits import chronological_split
from quantstrategyfinder.validation.walkforward import simple_walkforward_sharpe

from .review import approve_shortlist_mapped
from .store import CandidateStore


def _cost_model(cfg: dict[str, Any], stress: float = 1.0) -> CostModel:
    cost_cfg = dict(cfg.get("costs") or {})
    cost_cfg["stress_multiplier"] = stress
    fields = CostModel.__dataclass_fields__
    return CostModel(**{k: cost_cfg[k] for k in fields if k in cost_cfg})


def evaluate_approved_adapters(
    *,
    config_path: str = "configs/default.yaml",
    store_path: str = "data/discovery/candidates.sqlite",
    reports_dir: str = "reports",
    symbols: Optional[list[str]] = None,
    auto_approve_mapped: bool = False,
    cost_stress_multipliers: tuple[float, ...] = (1.0, 2.0, 3.0),
) -> dict[str, Any]:
    """
    Backtest approved adapter strategies on the MVP universe with OOS validation.
    Isolation: only `get_adapter` first-party classes run — no dynamic import of repos.
    """
    store = CandidateStore(store_path)
    if auto_approve_mapped:
        approve_shortlist_mapped(store=store, open_source_only=True)

    approved = store.list_candidates(status="approved")
    # Deduplicate by adapter_id (multiple repos may map to same family)
    by_adapter: dict[str, dict[str, Any]] = {}
    for row in approved:
        aid = row.get("adapter_id")
        if not aid or aid not in ADAPTER_REGISTRY:
            continue
        # Keep highest-star attribution source
        prev = by_adapter.get(aid)
        if prev is None or int(row.get("stars") or 0) > int(prev.get("stars") or 0):
            by_adapter[aid] = row

    cfg = load_config(config_path)
    symbols = symbols or list(cfg["universe"])
    starting_equity = float(cfg.get("starting_equity", 200.0))
    data_cfg = cfg.get("data") or {}
    split_cfg = cfg.get("splits") or {}
    val_cfg = cfg.get("validation") or {}

    fetched = fetch_universe(
        symbols,
        lookback_years=int(data_cfg.get("lookback_years", 10)),
        adjusted=bool(data_cfg.get("adjusted", True)),
        cache_dir=data_cfg.get("cache_dir", "data/cache"),
        force_refresh=False,
    )

    repo = RunRepository(reports_dir)
    run_id, artifact_dir = repo.create_run(git_commit=git_commit_short())
    provenance = {s: p.to_dict() for s, (_, p) in fetched.items()}
    repo.save_json(artifact_dir, "provenance.json", provenance)

    leaderboard: list[dict[str, Any]] = []
    warnings: list[str] = []

    if not by_adapter:
        warnings.append(
            "No approved adapters to evaluate. Run discover + review approve first."
        )

    for aid, src in by_adapter.items():
        strategy = get_adapter(aid)
        for symbol, (bars, prov) in fetched.items():
            # Skip futures-only claims without futures modeling (P2)
            markets = json.loads(src.get("markets_json") or "[]")
            if markets == ["futures"] and symbol not in {"SPY", "QQQ", "GLD", "TLT", "BTC-USD"}:
                continue

            splits = chronological_split(
                bars,
                train_frac=float(split_cfg.get("train_frac", 0.5)),
                val_frac=float(split_cfg.get("val_frac", 0.25)),
                test_frac=float(split_cfg.get("test_frac", 0.25)),
            )
            costs = _cost_model(cfg, 1.0)
            result = run_backtest(
                bars,
                strategy,
                config=BacktestConfig(
                    starting_equity=starting_equity, symbol=symbol, costs=costs
                ),
            )
            eq = result.equity_curve["equity"]

            def _seg(idx):
                return eq.reindex(idx).dropna()

            def _rebase(seg: pd.Series):
                if seg.empty:
                    return seg, starting_equity
                return seg, float(seg.iloc[0])

            eq_tr, st_tr = _rebase(_seg(splits.train.index))
            eq_va, st_va = _rebase(_seg(splits.val.index))
            eq_te, st_te = _rebase(_seg(splits.test.index))

            def _filter_trades(df: pd.DataFrame, idx) -> pd.DataFrame:
                if df is None or df.empty or "entry_time" not in df.columns:
                    return pd.DataFrame()
                t = pd.to_datetime(df["entry_time"], utc=True)
                return df.loc[(t >= idx[0]) & (t <= idx[-1])]

            outcome = evaluate_candidate(
                equity_train=eq_tr,
                equity_val=eq_va,
                equity_test=eq_te,
                starting_equity_train=st_tr,
                starting_equity_val=st_va,
                starting_equity_test=st_te,
                trades_train=_filter_trades(result.trades, splits.train.index),
                trades_val=_filter_trades(result.trades, splits.val.index),
                trades_test=_filter_trades(result.trades, splits.test.index),
                fills_test=result.fills,
                min_bars=int(val_cfg.get("min_bars", 252)),
                min_trades=int(val_cfg.get("min_trades", 5)),
                max_drawdown_fail=float(val_cfg.get("max_drawdown_fail", 0.5)),
                min_val_sharpe=float(val_cfg.get("min_val_sharpe", -0.5)),
            )

            # Cost stress on validation window equity path (base fill already at 1x)
            stress_notes: dict[str, Any] = {}
            for mult in cost_stress_multipliers:
                stressed = run_backtest(
                    bars,
                    strategy,
                    config=BacktestConfig(
                        starting_equity=starting_equity,
                        symbol=symbol,
                        costs=_cost_model(cfg, mult),
                    ),
                )
                seg = stressed.equity_curve["equity"].reindex(splits.val.index).dropna()
                if len(seg) >= 2:
                    m = compute_metrics(seg, starting_equity=float(seg.iloc[0]))
                    stress_notes[f"{mult}x"] = {
                        "val_sharpe": m.get("sharpe"),
                        "val_total_return": m.get("total_return"),
                        "val_max_dd": m.get("max_drawdown"),
                    }

            wf = simple_walkforward_sharpe(eq)

            full_metrics = compute_metrics(
                eq,
                starting_equity=starting_equity,
                trades=result.trades,
                fills=result.fills,
            )
            stem = f"adapter_{aid}_{symbol}"
            repo.save_df(artifact_dir, f"equity_{stem}.csv", result.equity_curve)
            if not result.fills.empty:
                repo.save_df(artifact_dir, f"fills_{stem}.csv", result.fills)
            if not result.trades.empty:
                repo.save_df(artifact_dir, f"trades_{stem}.csv", result.trades)

            attribution = {
                "source_repo": src.get("repo_full_name"),
                "source_url": src.get("html_url"),
                "source_commit": src.get("commit_hash"),
                "license_spdx": src.get("license_spdx"),
                "open_source_badge": src.get("open_source_badge"),
                "fidelity": src.get("fidelity") or "REIMPLEMENTATION",
                "adapter_id": aid,
                "isolation": "first_party_adapter_only",
                "author_claimed_note": src.get("author_claimed_note"),
            }
            repo.save_json(
                artifact_dir,
                f"result_{stem}.json",
                {
                    "strategy": strategy.describe(),
                    "attribution": attribution,
                    "validation": outcome.to_dict(),
                    "full_sample_metrics": full_metrics,
                    "cost_stress_val": stress_notes,
                    "walkforward": wf,
                    "split": splits.summary(),
                    "provenance": prov.to_dict(),
                },
            )

            # $200 feasibility: any hard rejections?
            feasibility_ok = len(result.rejections) == 0 or all(
                r.get("reason") != "insufficient_cash" for r in result.rejections
            )

            leaderboard.append(
                {
                    "strategy_id": aid,
                    "strategy_version": strategy.meta.version,
                    "symbol": symbol,
                    "status": outcome.status,
                    "reasons": outcome.reasons,
                    "eligible_for_ranking": outcome.eligible_for_ranking and feasibility_ok,
                    "metrics_val": outcome.metrics_val,
                    "metrics_test": outcome.metrics_test,
                    "metrics_train": outcome.metrics_train,
                    "full_sample_metrics": full_metrics,
                    "cost_stress_val": stress_notes,
                    "walkforward": wf,
                    "attribution": attribution,
                    "feasibility_200": feasibility_ok,
                    "n_rejections": len(result.rejections),
                    "data_hash": prov.content_hash,
                    "kind": "adapter",
                }
            )

    # Rank eligible by composite of val Sharpe, OOS CAGR proxy (test), DD, feasibility
    eligible = [r for r in leaderboard if r.get("eligible_for_ranking")]

    def rank_key(r: dict) -> tuple:
        mv, mt = r.get("metrics_val") or {}, r.get("metrics_test") or {}
        sharpe = mv.get("sharpe") if mv.get("sharpe") is not None else float("-inf")
        cagr = mt.get("cagr") if mt.get("cagr") is not None else float("-inf")
        dd = abs(mt.get("max_drawdown") or 0.0)
        return (float(sharpe), float(cagr), -float(dd))

    eligible_sorted = sorted(eligible, key=rank_key, reverse=True)
    for i, r in enumerate(eligible_sorted, start=1):
        r["rank"] = i

    n_pass = sum(1 for r in leaderboard if r.get("status") == "PASS")
    summary: dict[str, Any] = {
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "git_commit": git_commit_short(),
        "kind": "p1_adapter_evaluation",
        "starting_equity": starting_equity,
        "symbols": list(fetched.keys()),
        "strategies": sorted(by_adapter.keys()),
        "provenance": provenance,
        "leaderboard": leaderboard,
        "eligible_ranked": eligible_sorted,
        "any_passed": n_pass > 0,
        "message": None if n_pass > 0 else "NO STRATEGY PASSED VALIDATION",
        "counts": {
            "discovered": store.counts()["discovered"],
            "shortlisted": store.counts()["shortlisted"],
            "approved_repos": store.counts()["approved"],
            "adapters_evaluated": len(by_adapter),
            "symbol_strategy_pairs": len(leaderboard),
            "validated_pass": n_pass,
            "eligible_ranked": len(eligible_sorted),
        },
        "warnings": warnings,
        "artifact_dir": str(artifact_dir),
        "config_path": str(config_path),
        "safety": {
            "upstream_code_executed": False,
            "isolation": "first_party_adapters_only",
        },
    }
    export_run_bundle(artifact_dir, summary)
    repo.finalize(run_id, "completed", summary)
    # Also write discovery evaluation pointer
    Path("data/discovery").mkdir(parents=True, exist_ok=True)
    Path("data/discovery/last_eval.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "counts": summary["counts"],
                "message": summary["message"],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return summary
