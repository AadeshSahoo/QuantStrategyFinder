"""Phase 3 non-zero cost schedules."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from quantstrategyfinder.engine.costs import CostModel


@dataclass(frozen=True)
class Phase3CostSchedule:
    asset_class: str
    model: CostModel
    notes: str


def cost_for_asset_class(asset_class: str, cfg_costs: dict[str, Any]) -> Phase3CostSchedule:
    key = "crypto" if asset_class == "crypto" else "equity_etf"
    raw = dict(cfg_costs.get(key) or {})
    # Map into CostModel fields
    model = CostModel(
        commission_per_trade=float(raw.get("commission_per_trade", 0.0)),
        commission_pct=float(raw.get("commission_pct", 0.0)),
        spread_bps=float(raw.get("spread_bps", 2.0)),
        slippage_bps=float(raw.get("slippage_bps", 5.0)),
        min_notional=float(raw.get("min_notional", 1.0)),
        allow_fractional=bool(raw.get("allow_fractional", True)),
        stress_multiplier=1.0,
    )
    # Enforce non-zero total friction
    if model.commission_pct <= 0 and model.spread_bps <= 0 and model.slippage_bps <= 0:
        raise ValueError("Phase 3 costs must be non-zero in aggregate")
    notes = (
        f"{key}: commission_pct={model.commission_pct}, spread_bps={model.spread_bps}, "
        f"slippage_bps={model.slippage_bps}, min_notional={model.min_notional}"
    )
    return Phase3CostSchedule(asset_class=asset_class, model=model, notes=notes)
