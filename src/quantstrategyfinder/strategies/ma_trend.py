"""Moving-average trend following baseline (first-party)."""

from __future__ import annotations

import pandas as pd

from .base import Strategy, StrategyMeta


class MovingAverageTrend(Strategy):
    meta = StrategyMeta(
        id="ma_trend",
        version="1.0.0",
        name="Moving Average Trend",
        market="multi",
        timeframe="1d",
        description="Long when fast SMA > slow SMA; flat otherwise. Classic trend filter.",
        source_provenance="first-party baseline (QuantStrategyFinder)",
        lookback=200,
    )

    def __init__(self, fast: int = 50, slow: int = 200, **kwargs) -> None:
        if fast >= slow:
            raise ValueError("fast must be < slow")
        super().__init__(fast=fast, slow=slow, **kwargs)
        self.fast = fast
        self.slow = slow

    def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
        close = bars["Close"].astype(float)
        fast_ma = close.rolling(self.fast, min_periods=self.fast).mean()
        slow_ma = close.rolling(self.slow, min_periods=self.slow).mean()
        signal = (fast_ma > slow_ma).astype(float)
        signal = signal.where(slow_ma.notna(), other=0.0)
        signal.name = "target_weight"
        return signal
