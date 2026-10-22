"""Broker simulation: cash, positions, fills, trade ledger."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

from .costs import CostModel


@dataclass
class Order:
    timestamp: pd.Timestamp
    symbol: str
    target_weight: float
    reason: str = ""


@dataclass
class Fill:
    timestamp: pd.Timestamp
    symbol: str
    side: str
    qty: float
    price: float
    notional: float
    commission: float
    reason: str = ""


@dataclass
class Trade:
    """Round-trip or position change record."""

    entry_time: pd.Timestamp
    exit_time: Optional[pd.Timestamp]
    symbol: str
    qty: float
    entry_price: float
    exit_price: Optional[float]
    realized_pnl: Optional[float]
    costs: float
    status: str  # open | closed | rejected


@dataclass
class BrokerState:
    cash: float
    position_qty: float = 0.0
    avg_entry_price: float = 0.0
    symbol: str = ""
    fills: list[Fill] = field(default_factory=list)
    trades: list[Trade] = field(default_factory=list)
    rejections: list[dict] = field(default_factory=list)
    open_trade: Optional[Trade] = None

    def equity(self, mark_price: float) -> float:
        return self.cash + self.position_qty * mark_price

    def mark_to_market(self, mark_price: float) -> dict:
        unrealized = self.position_qty * (mark_price - self.avg_entry_price) if self.position_qty else 0.0
        return {
            "cash": self.cash,
            "position_qty": self.position_qty,
            "market_value": self.position_qty * mark_price,
            "equity": self.equity(mark_price),
            "unrealized_pnl": unrealized,
            "avg_entry_price": self.avg_entry_price,
        }


class SimulatedBroker:
    def __init__(self, starting_equity: float, symbol: str, costs: CostModel) -> None:
        if starting_equity <= 0:
            raise ValueError("starting_equity must be positive")
        self.costs = costs
        self.state = BrokerState(cash=float(starting_equity), symbol=symbol)

    def rebalance_to_weight(
        self,
        *,
        timestamp: pd.Timestamp,
        open_price: float,
        target_weight: float,
        reason: str = "",
    ) -> Optional[Fill]:
        """Move toward target portfolio weight using next-bar open mid price."""
        if open_price <= 0 or pd.isna(open_price):
            self.state.rejections.append(
                {
                    "timestamp": str(timestamp),
                    "reason": "unavailable_or_invalid_open",
                    "target_weight": target_weight,
                }
            )
            return None

        equity = self.state.equity(open_price)
        target_weight = max(0.0, min(1.0, float(target_weight)))  # MVP: long/flat only
        target_value = equity * target_weight
        current_value = self.state.position_qty * open_price
        delta_value = target_value - current_value

        if abs(delta_value) < self.costs.min_notional:
            return None

        side = "buy" if delta_value > 0 else "sell"
        fill_price = self.costs.apply_fill_price(open_price, side)
        raw_qty = delta_value / fill_price

        if not self.costs.allow_fractional:
            raw_qty = float(int(raw_qty)) if side == "buy" else -float(int(abs(raw_qty)))
            if raw_qty == 0:
                self.state.rejections.append(
                    {
                        "timestamp": str(timestamp),
                        "reason": "integer_qty_infeasible",
                        "target_weight": target_weight,
                        "equity": equity,
                        "price": fill_price,
                    }
                )
                return None

        qty = abs(raw_qty)
        notional = qty * fill_price
        commission = self.costs.commission(notional)

        if side == "buy":
            total_debit = notional + commission
            if total_debit > self.state.cash + 1e-9:
                # Scale down to available cash
                affordable = self.state.cash / (fill_price * (1.0 + self.costs.commission_pct) + 1e-12)
                if self.costs.allow_fractional:
                    qty = max(0.0, affordable)
                else:
                    qty = float(int(affordable))
                if qty * fill_price < self.costs.min_notional:
                    self.state.rejections.append(
                        {
                            "timestamp": str(timestamp),
                            "reason": "insufficient_cash",
                            "cash": self.state.cash,
                            "needed": total_debit,
                        }
                    )
                    return None
                notional = qty * fill_price
                commission = self.costs.commission(notional)
                total_debit = notional + commission
                if total_debit > self.state.cash + 1e-9:
                    self.state.rejections.append(
                        {
                            "timestamp": str(timestamp),
                            "reason": "insufficient_cash",
                            "cash": self.state.cash,
                            "needed": total_debit,
                        }
                    )
                    return None
            # Update average entry
            new_qty = self.state.position_qty + qty
            if new_qty > 0:
                self.state.avg_entry_price = (
                    (self.state.avg_entry_price * self.state.position_qty) + (fill_price * qty)
                ) / new_qty
            self.state.position_qty = new_qty
            self.state.cash -= total_debit
            if self.state.open_trade is None and self.state.position_qty > 0:
                self.state.open_trade = Trade(
                    entry_time=timestamp,
                    exit_time=None,
                    symbol=self.state.symbol,
                    qty=self.state.position_qty,
                    entry_price=self.state.avg_entry_price,
                    exit_price=None,
                    realized_pnl=None,
                    costs=commission,
                    status="open",
                )
        else:
            qty = min(qty, self.state.position_qty)
            if qty <= 0:
                return None
            notional = qty * fill_price
            commission = self.costs.commission(notional)
            proceeds = notional - commission
            realized = (fill_price - self.state.avg_entry_price) * qty - commission
            self.state.cash += proceeds
            self.state.position_qty -= qty
            if self.state.open_trade is not None:
                self.state.open_trade.costs += commission
                if self.state.position_qty <= 1e-12:
                    self.state.position_qty = 0.0
                    self.state.open_trade.exit_time = timestamp
                    self.state.open_trade.exit_price = fill_price
                    self.state.open_trade.realized_pnl = realized
                    self.state.open_trade.status = "closed"
                    self.state.trades.append(self.state.open_trade)
                    self.state.open_trade = None
                    self.state.avg_entry_price = 0.0
            else:
                self.state.avg_entry_price = 0.0 if self.state.position_qty == 0 else self.state.avg_entry_price

        fill = Fill(
            timestamp=timestamp,
            symbol=self.state.symbol,
            side=side,
            qty=qty,
            price=fill_price,
            notional=notional,
            commission=commission,
            reason=reason,
        )
        self.state.fills.append(fill)
        return fill
