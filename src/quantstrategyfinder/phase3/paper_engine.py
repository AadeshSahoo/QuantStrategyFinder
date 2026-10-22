"""Idempotent daily paper-trading loop (SIMULATED — not live brokerage)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

import pandas as pd
import yaml

from quantstrategyfinder.data.sources import fetch_daily_ohlcv
from quantstrategyfinder.phase2.registry import get_phase2_strategy
from quantstrategyfinder.phase3.costs import cost_for_asset_class
from quantstrategyfinder.phase3.export import export_phase3_deliverables
from quantstrategyfinder.phase3.forward_metrics import compute_forward_performance
from quantstrategyfinder.phase3.store import PaperStore

logger = logging.getLogger(__name__)


def load_phase3_config(path: str | Path = "configs/phase3-forward-trading-config.yaml") -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def register_config(
    config_path: str | Path = "configs/phase3-forward-trading-config.yaml",
    *,
    db_path: Optional[str] = None,
    code_version: Optional[str] = None,
) -> dict[str, Any]:
    """Freeze shortlist into SQLite. Idempotent if already registered with same DB."""
    path = Path(config_path)
    text = path.read_text(encoding="utf-8")
    cfg = yaml.safe_load(text)
    db = db_path or cfg["persistence"]["sqlite_path"]
    store = PaperStore(db)
    from quantstrategyfinder.pipeline import git_commit_short

    ver = code_version or cfg.get("code_version_pin") or git_commit_short() or "unknown"
    h = store.register(cfg, config_text=text, code_version=str(ver))
    # Also write snapshot beside DB
    snap = Path(db).parent / "registered_config_snapshot.yaml"
    snap.write_text(text, encoding="utf-8")
    meta = store.registration_meta() or {}
    return {
        "config_hash": h,
        "db_path": str(db),
        "snapshot": str(snap),
        "already_registered": meta.get("config_hash") == h and store.is_registered(),
        "n_candidates": cfg["n_candidates_registered"],
        "forward_start_date": cfg["forward_start_date"],
        "code_version": ver,
        "label": cfg.get("label"),
    }


def _history_for_signal(bars: pd.DataFrame, asof: pd.Timestamp) -> pd.DataFrame:
    """Bars with index <= asof (inclusive) — information available after that close."""
    return bars.loc[bars.index <= asof]


def _next_session(bars: pd.DataFrame, after: pd.Timestamp) -> Optional[pd.Timestamp]:
    future = bars.index[bars.index > after]
    if len(future) == 0:
        return None
    return pd.Timestamp(future[0])


def _rebalance(
    store: PaperStore,
    *,
    candidate_id: str,
    target_weight: float,
    mid: float,
    costs,
    exec_date: str,
    signal_date: str,
    order_key: str,
) -> dict[str, Any]:
    acct = store.get_account(candidate_id)
    cash = float(acct["cash"])
    qty = float(acct["position_qty"])
    avg = float(acct["avg_entry"])
    equity = cash + qty * mid
    target_weight = max(0.0, min(1.0, float(target_weight)))
    target_value = equity * target_weight
    delta_value = target_value - qty * mid

    if abs(delta_value) < costs.min_notional:
        store.insert_order(
            candidate_id=candidate_id,
            order_key=order_key,
            signal_date=signal_date,
            exec_date=exec_date,
            side="none",
            target_weight=target_weight,
            status="skipped",
            reason="below_min_notional",
        )
        return {"status": "skipped", "reason": "below_min_notional"}

    side = "buy" if delta_value > 0 else "sell"
    fill_px = costs.apply_fill_price(mid, side)
    raw_qty = abs(delta_value) / fill_px
    if not costs.allow_fractional:
        raw_qty = float(int(raw_qty))
        if raw_qty <= 0:
            store.insert_order(
                candidate_id=candidate_id,
                order_key=order_key,
                signal_date=signal_date,
                exec_date=exec_date,
                side=side,
                target_weight=target_weight,
                status="rejected",
                reason="integer_qty_infeasible",
            )
            return {"status": "rejected", "reason": "integer_qty_infeasible"}

    if side == "buy":
        commission = costs.commission(raw_qty * fill_px)
        debit = raw_qty * fill_px + commission
        if debit > cash + 1e-9:
            # scale to cash
            afford = cash / (fill_px * (1.0 + costs.commission_pct) + 1e-12)
            if not costs.allow_fractional:
                afford = float(int(afford))
            raw_qty = max(0.0, afford)
            commission = costs.commission(raw_qty * fill_px)
            debit = raw_qty * fill_px + commission
            if raw_qty * fill_px < costs.min_notional:
                store.insert_order(
                    candidate_id=candidate_id,
                    order_key=order_key,
                    signal_date=signal_date,
                    exec_date=exec_date,
                    side=side,
                    target_weight=target_weight,
                    status="rejected",
                    reason="insufficient_cash",
                )
                return {"status": "rejected", "reason": "insufficient_cash"}
        new_qty = qty + raw_qty
        avg = ((avg * qty) + (fill_px * raw_qty)) / new_qty if new_qty > 0 else 0.0
        cash -= debit
        qty = new_qty
        spread_cost = abs(fill_px - mid) * raw_qty
    else:
        raw_qty = min(raw_qty, qty)
        if raw_qty <= 0:
            store.insert_order(
                candidate_id=candidate_id,
                order_key=order_key,
                signal_date=signal_date,
                exec_date=exec_date,
                side=side,
                target_weight=target_weight,
                status="skipped",
                reason="no_position",
            )
            return {"status": "skipped", "reason": "no_position"}
        commission = costs.commission(raw_qty * fill_px)
        cash += raw_qty * fill_px - commission
        qty -= raw_qty
        if qty <= 1e-12:
            qty = 0.0
            avg = 0.0
        spread_cost = abs(fill_px - mid) * raw_qty

    if not store.insert_order(
        candidate_id=candidate_id,
        order_key=order_key,
        signal_date=signal_date,
        exec_date=exec_date,
        side=side,
        target_weight=target_weight,
        status="filled",
        reason=None,
    ):
        return {"status": "duplicate_order"}

    store.insert_fill(
        order_key=order_key,
        candidate_id=candidate_id,
        exec_date=exec_date,
        side=side,
        qty=raw_qty,
        mid_price=mid,
        fill_price=fill_px,
        notional=raw_qty * fill_px,
        commission=commission,
        spread_slippage_cost=spread_cost,
    )
    store.update_account(candidate_id, cash=cash, position_qty=qty, avg_entry=avg)
    return {"status": "filled", "side": side, "qty": raw_qty, "fill_price": fill_px}


def run_paper_job(
    config_path: str | Path = "configs/phase3-forward-trading-config.yaml",
    *,
    force_reregister: bool = False,
) -> dict[str, Any]:
    """
    Process all new sessions on/after forward_start_date for each registered candidate.
    Idempotent: re-running does not duplicate order_keys.
    """
    cfg = load_phase3_config(config_path)
    db_path = cfg["persistence"]["sqlite_path"]
    store = PaperStore(db_path)
    if force_reregister and store.is_registered():
        raise RuntimeError("Refusing force_reregister on existing DB — use a new sqlite path.")
    if not store.is_registered():
        register_config(config_path)

    job_id = store.start_job()
    forward_start = pd.Timestamp(cfg["forward_start_date"], tz="UTC")
    data_cfg = cfg.get("data") or {}
    detail: dict[str, Any] = {
        "label": cfg.get("label"),
        "forward_start_date": cfg["forward_start_date"],
        "candidates": [],
        "warnings": [],
    }

    try:
        for cand in store.list_candidates():
            cid = cand["candidate_id"]
            sym = cand["symbol"]
            asset_class = cand["asset_class"]
            params = json.loads(cand["params_json"])
            strategy = get_phase2_strategy(cand["strategy_id"], **params)
            schedule = cost_for_asset_class(asset_class, cfg.get("costs") or {})
            costs = schedule.model

            bars, prov = fetch_daily_ohlcv(
                sym,
                lookback_years=int(data_cfg.get("lookback_years", 10)),
                cache_dir=data_cfg.get("cache_dir", "data/cache"),
                # Scheduled/paper jobs must see newly published sessions.
                force_refresh=True,
            )
            # Only process exec dates >= forward_start
            forward_bars = bars.loc[bars.index >= forward_start]
            if forward_bars.empty:
                detail["warnings"].append(
                    f"{cid}: no bars on/after {cfg['forward_start_date']} yet "
                    f"(latest cached end={(prov.end if hasattr(prov,'end') else 'n/a')})."
                )
                detail["candidates"].append(
                    {"candidate_id": cid, "new_sessions": 0, "fills": 0, "status": "no_new_data"}
                )
                continue

            # Warmup history must include pre-forward bars for indicators
            fills_n = 0
            sessions = 0
            # Signal dates: each bar D in forward window uses history through D's prior session
            # Convention: after close of day T, signal observed; fill at open of T+1.
            # For each potential exec day E >= forward_start, signal_date = previous session.
            all_idx = bars.index
            for exec_ts in forward_bars.index:
                sessions += 1
                loc = all_idx.get_loc(exec_ts)
                if isinstance(loc, slice) or not isinstance(loc, (int,)):
                    # non-unique — skip
                    continue
                if loc == 0:
                    continue
                signal_ts = all_idx[loc - 1]
                signal_date = str(signal_ts.date())
                exec_date = str(exec_ts.date())
                order_key = f"{cid}|{exec_date}|rebalance"

                if store.order_exists(order_key):
                    # Still refresh equity mark
                    acct = store.get_account(cid)
                    mark = float(bars.loc[exec_ts, "Close"])
                    eq = float(acct["cash"]) + float(acct["position_qty"]) * mark
                    store.upsert_equity(
                        cid,
                        exec_date,
                        cash=float(acct["cash"]),
                        position_qty=float(acct["position_qty"]),
                        mark_price=mark,
                        equity=eq,
                    )
                    continue

                hist = _history_for_signal(bars, signal_ts)
                if hist.empty:
                    continue
                sig_series = strategy.generate_signals(hist)
                target = float(sig_series.iloc[-1]) if len(sig_series) else 0.0
                store.insert_signal(cid, signal_date, signal_date, target)

                mid = float(bars.loc[exec_ts, "Open"])
                if mid <= 0 or pd.isna(mid):
                    store.insert_order(
                        candidate_id=cid,
                        order_key=order_key,
                        signal_date=signal_date,
                        exec_date=exec_date,
                        side="none",
                        target_weight=target,
                        status="rejected",
                        reason="invalid_open",
                    )
                    continue

                result = _rebalance(
                    store,
                    candidate_id=cid,
                    target_weight=target,
                    mid=mid,
                    costs=costs,
                    exec_date=exec_date,
                    signal_date=signal_date,
                    order_key=order_key,
                )
                if result.get("status") == "filled":
                    fills_n += 1

                acct = store.get_account(cid)
                mark = float(bars.loc[exec_ts, "Close"])
                eq = float(acct["cash"]) + float(acct["position_qty"]) * mark
                store.upsert_equity(
                    cid,
                    exec_date,
                    cash=float(acct["cash"]),
                    position_qty=float(acct["position_qty"]),
                    mark_price=mark,
                    equity=eq,
                )

            detail["candidates"].append(
                {
                    "candidate_id": cid,
                    "symbol": sym,
                    "new_sessions_processed": sessions,
                    "fills": fills_n,
                    "cost_notes": schedule.notes,
                    "data_end": prov.end,
                    "data_hash": prov.content_hash,
                }
            )

        # Metrics + exports (mark job complete before export so report sees finished status)
        perf = compute_forward_performance(store, cfg)
        detail["performance_summary"] = perf.get("summary")
        detail["job_id"] = job_id
        detail["db_path"] = db_path
        detail["scheduler_note"] = (
            "One-shot job completed in this environment. Continuous forward testing requires "
            "a persistent host running scripts/phase3_paper_job.py on a schedule "
            "(see docs/phase3-scheduler.md)."
        )
        store.finish_job(job_id, "completed", detail)
        paths = export_phase3_deliverables(store, cfg, perf, detail)
        detail["exports"] = {k: str(v) for k, v in paths.items()}
        store.finish_job(job_id, "completed", detail)
        return detail
    except Exception as exc:  # noqa: BLE001
        store.finish_job(job_id, "failed", {"error": str(exc)})
        raise
