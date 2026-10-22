"""Transaction cost model (research estimates)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CostModel:
    commission_per_trade: float = 0.0
    commission_pct: float = 0.0
    spread_bps: float = 2.0
    slippage_bps: float = 5.0
    min_notional: float = 1.0
    allow_fractional: bool = True
    stress_multiplier: float = 1.0

    def half_spread_frac(self) -> float:
        return (self.spread_bps * self.stress_multiplier) / 10_000.0 / 2.0

    def slippage_frac(self) -> float:
        return (self.slippage_bps * self.stress_multiplier) / 10_000.0

    def apply_fill_price(self, mid: float, side: str) -> float:
        """side: 'buy' pays up; 'sell' receives down."""
        adj = self.half_spread_frac() + self.slippage_frac()
        if side == "buy":
            return mid * (1.0 + adj)
        if side == "sell":
            return mid * (1.0 - adj)
        raise ValueError(f"unknown side {side}")

    def commission(self, notional: float) -> float:
        return self.commission_per_trade + abs(notional) * self.commission_pct * self.stress_multiplier
