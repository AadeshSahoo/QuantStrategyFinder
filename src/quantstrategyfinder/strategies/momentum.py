"""Time-series momentum baseline (first-party)."""

from __future__ import annotations

import pandas as pd

from .base import Strategy, StrategyMeta


class TimeSeriesMomentum(Strategy):
    meta = StrategyMeta(
        id="momentum",
        version="1.0.0",
        name="Time-Series Momentum",
        market="multi",
        timeframe="1d",
        description=(
            "Long when trailing lookback total return exceeds threshold; flat otherwise. "
            "Classic TSMOM long/flat variant."
        ),
        source_provenance="first-party baseline (QuantStrategyFinder)",
        lookback=60,
    )

    def __init__(self, lookback: int = 60, hold_threshold: float = 0.0, **kwargs) -> None:
        super().__init__(lookback=lookback, hold_threshold=hold_threshold, **kwargs)
        self.lookback = lookback
        self.hold_threshold = hold_threshold

    def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
        close = bars["Close"].astype(float)
        # Return observed at close of t uses prices through t; fill next open
        ret = close / close.shift(self.lookback) - 1.0
        signal = (ret > self.hold_threshold).astype(float)
        signal = signal.where(ret.notna(), other=0.0)
        signal.name = "target_weight"
        return signal
