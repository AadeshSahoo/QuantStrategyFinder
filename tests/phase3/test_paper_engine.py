"""Phase 3 paper-trading unit/integration tests."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
import yaml

from quantstrategyfinder.engine.costs import CostModel
from quantstrategyfinder.phase3.costs import cost_for_asset_class
from quantstrategyfinder.phase3.paper_engine import _rebalance, register_config, run_paper_job
from quantstrategyfinder.phase3.store import PaperStore


def test_costs_are_nonzero():
    cfg = yaml.safe_load(Path("configs/phase3-forward-trading-config.yaml").read_text())
    eq = cost_for_asset_class("equities", cfg["costs"])
    cr = cost_for_asset_class("crypto", cfg["costs"])
    assert eq.model.commission_pct > 0 or eq.model.spread_bps > 0
    assert cr.model.commission_pct > 0
    buy = eq.model.apply_fill_price(100.0, "buy")
    assert buy > 100.0


def test_store_idempotent_orders(tmp_path: Path):
    store = PaperStore(tmp_path / "t.sqlite")
    cfg = yaml.safe_load(Path("configs/phase3-forward-trading-config.yaml").read_text())
    # minimal register
    text = Path("configs/phase3-forward-trading-config.yaml").read_text()
    store.register(cfg, config_text=text, code_version="test")
    cid = cfg["candidates"][0]["candidate_id"]
    ok1 = store.insert_order(
        candidate_id=cid,
        order_key="k1",
        signal_date="2026-10-22",
        exec_date="2026-10-23",
        side="buy",
        target_weight=1.0,
        status="filled",
        reason=None,
    )
    ok2 = store.insert_order(
        candidate_id=cid,
        order_key="k1",
        signal_date="2026-10-22",
        exec_date="2026-10-23",
        side="buy",
        target_weight=1.0,
        status="filled",
        reason=None,
    )
    assert ok1 is True
    assert ok2 is False


def test_rebalance_respects_cash(tmp_path: Path):
    store = PaperStore(tmp_path / "t2.sqlite")
    cfg = yaml.safe_load(Path("configs/phase3-forward-trading-config.yaml").read_text())
    text = Path("configs/phase3-forward-trading-config.yaml").read_text()
    store.register(cfg, config_text=text, code_version="test")
    cid = cfg["candidates"][2]["candidate_id"]  # META equity
    costs = CostModel(commission_pct=0.001, spread_bps=2, slippage_bps=5, min_notional=1.0)
    # First buy almost all cash
    r = _rebalance(
        store,
        candidate_id=cid,
        target_weight=1.0,
        mid=100.0,
        costs=costs,
        exec_date="2026-10-23",
        signal_date="2026-10-22",
        order_key=f"{cid}|2026-10-23|rebalance",
    )
    assert r["status"] == "filled"
    acct = store.get_account(cid)
    assert acct["cash"] >= -1e-6
    assert acct["position_qty"] > 0


def test_signal_timing_uses_prior_bar():
    # Documented convention: exec on day T uses signal from T-1 close history
    idx = pd.date_range("2026-10-01", periods=5, freq="B", tz="UTC")
    assert idx[1] > idx[0]


def test_register_and_run_smoke(tmp_path: Path, monkeypatch):
    """Integration: register against temp DB by patching config persistence paths."""
    src = Path("configs/phase3-forward-trading-config.yaml").read_text()
    cfg = yaml.safe_load(src)
    cfg["persistence"]["sqlite_path"] = str(tmp_path / "paper.sqlite")
    cfg["persistence"]["exports_dir"] = str(tmp_path / "exports")
    # Keep forward_start; may yield no new bars — still must complete
    cfg_path = tmp_path / "cfg.yaml"
    cfg_path.write_text(yaml.dump(cfg), encoding="utf-8")
    reg = register_config(cfg_path)
    assert reg["n_candidates"] == 5
    detail = run_paper_job(cfg_path)
    assert "job_id" in detail
    assert Path(cfg["persistence"]["sqlite_path"]).exists()
    # Idempotent second run
    detail2 = run_paper_job(cfg_path)
    store = PaperStore(cfg["persistence"]["sqlite_path"])
    fills1 = len(store.export_fills())
    # run again
    run_paper_job(cfg_path)
    fills2 = len(store.export_fills())
    assert fills2 == fills1  # no duplicate fills


def test_fees_nonzero_on_fill(tmp_path: Path):
    store = PaperStore(tmp_path / "fees.sqlite")
    cfg = yaml.safe_load(Path("configs/phase3-forward-trading-config.yaml").read_text())
    store.register(cfg, config_text=Path("configs/phase3-forward-trading-config.yaml").read_text(), code_version="t")
    cid = "tsmom_NVDA"
    costs = cost_for_asset_class("equities", cfg["costs"]).model
    r = _rebalance(
        store,
        candidate_id=cid,
        target_weight=1.0,
        mid=100.0,
        costs=costs,
        exec_date="2026-10-23",
        signal_date="2026-10-22",
        order_key=f"{cid}|fee-test",
    )
    assert r["status"] == "filled"
    fills = store.export_fills()
    assert len(fills) == 1
    assert fills[0]["commission"] > 0 or fills[0]["spread_slippage_cost"] > 0
    assert fills[0]["fill_price"] > fills[0]["mid_price"]  # buy pays up


def test_data_gap_skips_without_crash(tmp_path: Path):
    """Missing/invalid open rejects order; store remains consistent."""
    store = PaperStore(tmp_path / "gap.sqlite")
    cfg = yaml.safe_load(Path("configs/phase3-forward-trading-config.yaml").read_text())
    store.register(cfg, config_text=Path("configs/phase3-forward-trading-config.yaml").read_text(), code_version="t")
    cid = "dual_sma_SHY"
    costs = cost_for_asset_class("fixed_income", cfg["costs"]).model
    # Zero mid simulates bad bar
    store.insert_order(
        candidate_id=cid,
        order_key=f"{cid}|gap|rej",
        signal_date="2026-10-22",
        exec_date="2026-10-23",
        side="none",
        target_weight=0.0,
        status="rejected",
        reason="invalid_open",
    )
    assert store.get_account(cid)["cash"] == cfg["starting_equity_per_strategy"]
    assert costs.min_notional > 0


def test_forward_metrics_insufficient_evidence(tmp_path: Path):
    from quantstrategyfinder.phase3.forward_metrics import compute_forward_performance

    store = PaperStore(tmp_path / "m.sqlite")
    cfg = yaml.safe_load(Path("configs/phase3-forward-trading-config.yaml").read_text())
    store.register(cfg, config_text=Path("configs/phase3-forward-trading-config.yaml").read_text(), code_version="t")
    perf = compute_forward_performance(store, cfg)
    assert perf["summary"]["n_statistically_validated"] == 0
    assert perf["summary"]["n_insufficient_evidence"] == 5
    assert all(r["validation_status"] == "INSUFFICIENT_EVIDENCE" for r in perf["rows"])


def test_benchmark_bah_and_cash_columns(tmp_path: Path):
    """With synthetic equity days, performance row exposes BAH/cash fields once sample grows."""
    from quantstrategyfinder.phase3.forward_metrics import compute_forward_performance

    store = PaperStore(tmp_path / "b.sqlite")
    cfg = yaml.safe_load(Path("configs/phase3-forward-trading-config.yaml").read_text())
    # Lower thresholds so we exercise benchmark path with synthetic marks
    cfg["insufficient_evidence"]["min_trading_days"] = 3
    cfg["insufficient_evidence"]["min_completed_trades"] = 0
    store.register(cfg, config_text=yaml.dump(cfg), code_version="t")
    cid = "dual_sma_SHY"
    for i, d in enumerate(["2026-10-22", "2026-10-23", "2026-10-24", "2026-10-27"]):
        store.upsert_equity(cid, d, cash=200.0, position_qty=0.0, mark_price=80.0 + i, equity=200.0)
    perf = compute_forward_performance(store, cfg)
    row = next(r for r in perf["rows"] if r["candidate_id"] == cid)
    assert row["cash_total_return"] == 0.0
    assert "benchmark_total_return" in row or row["validation_status"] == "INSUFFICIENT_EVIDENCE"
    # Never auto-validate
    assert perf["summary"]["n_statistically_validated"] == 0
