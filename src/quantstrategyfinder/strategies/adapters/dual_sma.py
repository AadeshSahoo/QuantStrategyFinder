from __future__ import annotations

import pandas as pd

from quantstrategyfinder.strategies.base import Strategy

from ._common import adapter_meta


class DualSMA(Strategy):
    meta = adapter_meta(
        id="dual_sma",
        name="Dual SMA Crossover (adapter)",
        description="Long when fast SMA > slow SMA; flat otherwise.",
        lookback=200,
        source_note="Classic dual moving-average cross family.",
    )

    def __init__(self, fast: int = 50, slow: int = 200, **kwargs) -> None:
        if fast >= slow:
            raise ValueError("fast must be < slow")
        super().__init__(fast=fast, slow=slow, **kwargs)
        self.fast, self.slow = fast, slow

    def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
        c = bars["Close"].astype(float)
        f = c.rolling(self.fast, min_periods=self.fast).mean()
        s = c.rolling(self.slow, min_periods=self.slow).mean()
        sig = (f > s).astype(float).where(s.notna(), 0.0)
        sig.name = "target_weight"
        return sig
