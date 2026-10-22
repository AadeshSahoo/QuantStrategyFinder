"""Event-driven / vectorized hybrid backtest with next-bar fills."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np
import pandas as pd

from quantstrategyfinder.strategies.base import Strategy

from .broker import SimulatedBroker
from .costs import CostModel


@dataclass
class BacktestConfig:
    starting_equity: float = 200.0
    symbol: str = "SPY"
    costs: CostModel = field(default_factory=CostModel)


@dataclass
class BacktestResult:
    symbol: str
    strategy_id: str
    strategy_version: str
    starting_equity: float
    equity_curve: pd.DataFrame
    fills: pd.DataFrame
    trades: pd.DataFrame
    rejections: list[dict]
    signals: pd.Series
    config: dict[str, Any]
    notes: list[str] = field(default_factory=list)

    @property
    def final_equity(self) -> float:
        if self.equity_curve.empty:
            return self.starting_equity
        return float(self.equity_curve["equity"].iloc[-1])


def run_backtest(
    bars: pd.DataFrame,
    strategy: Strategy,
    *,
    config: Optional[BacktestConfig] = None,
) -> BacktestResult:
    """
    Signal at close of bar t → target weight observed after close.
    Fill at open of bar t+1 (no look-ahead on fill price).
    Equity marked at close each day.
    """
    cfg = config or BacktestConfig()
    if bars.empty:
        raise ValueError("bars are empty — cannot backtest")

    signals = strategy.generate_signals(bars)
    signals = signals.reindex(bars.index).fillna(0.0)

    broker = SimulatedBroker(cfg.starting_equity, cfg.symbol, cfg.costs)
    records: list[dict] = []
    notes: list[str] = [
        "Fill convention: signals observed at close; orders filled at next bar open.",
        "Idle cash earns 0% interest (trading P&L separated from financing).",
        f"Cost stress multiplier={cfg.costs.stress_multiplier}",
    ]

    # Pre-shift: action for day i uses signal from day i-1
    target_for_open = signals.shift(1)

    for i, (ts, row) in enumerate(bars.iterrows()):
        open_px = float(row["Open"])
        close_px = float(row["Close"])
        tgt = target_for_open.iloc[i]
        if not pd.isna(tgt):
            broker.rebalance_to_weight(
                timestamp=ts,
                open_price=open_px,
                target_weight=float(tgt),
                reason=f"signal={float(tgt):.2f}",
            )
        mtm = broker.state.mark_to_market(close_px)
        records.append(
            {
                "Date": ts,
                "open": open_px,
                "close": close_px,
                "signal": float(signals.iloc[i]),
                "target_at_open": float(tgt) if not pd.isna(tgt) else 0.0,
                **mtm,
                "exposure": mtm["market_value"] / mtm["equity"] if mtm["equity"] else 0.0,
            }
        )

    equity_curve = pd.DataFrame.from_records(records).set_index("Date")
    fills_df = pd.DataFrame([f.__dict__ for f in broker.state.fills])
    trade_rows = [t.__dict__ for t in broker.state.trades]
    if broker.state.open_trade is not None:
        # Mark open trade at end for ledger completeness
        ot = broker.state.open_trade
        trade_rows.append(
            {
                **ot.__dict__,
                "exit_time": bars.index[-1],
                "exit_price": float(bars["Close"].iloc[-1]),
                "realized_pnl": None,
                "status": "open_eod",
            }
        )
    trades_df = pd.DataFrame(trade_rows) if trade_rows else pd.DataFrame()

    return BacktestResult(
        symbol=cfg.symbol,
        strategy_id=strategy.meta.id,
        strategy_version=strategy.meta.version,
        starting_equity=cfg.starting_equity,
        equity_curve=equity_curve,
        fills=fills_df,
        trades=trades_df,
        rejections=list(broker.state.rejections),
        signals=signals,
        config={
            "starting_equity": cfg.starting_equity,
            "symbol": cfg.symbol,
            "costs": cfg.costs.__dict__,
            "strategy": strategy.describe(),
        },
        notes=notes,
    )


def buy_and_hold(
    bars: pd.DataFrame,
    *,
    starting_equity: float = 200.0,
    symbol: str = "SPY",
    costs: Optional[CostModel] = None,
) -> BacktestResult:
    """Benchmark: buy full equity on first available open, hold to end."""
    from quantstrategyfinder.strategies.base import Strategy, StrategyMeta

    class _BAH(Strategy):
        meta = StrategyMeta(
            id="buy_and_hold",
            version="1.0.0",
            name="Buy and Hold",
            market="multi",
            timeframe="1d",
            description="Buy on first signal day and hold.",
            source_provenance="benchmark",
            lookback=1,
        )

        def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
            s = pd.Series(1.0, index=bars.index, name="target_weight")
            # First bar signal becomes actionable next open via shift
            return s

    return run_backtest(
        bars,
        _BAH(),
        config=BacktestConfig(starting_equity=starting_equity, symbol=symbol, costs=costs or CostModel()),
    )


def cash_benchmark(bars: pd.DataFrame, *, starting_equity: float = 200.0) -> pd.Series:
    """Flat cash equity (0% interest)."""
    return pd.Series(starting_equity, index=bars.index, name="cash_equity")
