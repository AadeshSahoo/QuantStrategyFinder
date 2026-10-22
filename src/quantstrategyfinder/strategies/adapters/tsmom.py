from __future__ import annotations

import pandas as pd

from quantstrategyfinder.strategies.base import Strategy

from ._common import adapter_meta


class TSMOM12(Strategy):
    meta = adapter_meta(
        id="tsmom",
        name="12-1 Time-Series Momentum (adapter)",
        description="Long when 252d return > 0 (approx 12m); flat otherwise.",
        lookback=252,
        source_note="Classic TSMOM / trend-following momentum family.",
    )

    def __init__(self, lookback: int = 252, threshold: float = 0.0, **kwargs) -> None:
        super().__init__(lookback=lookback, threshold=threshold, **kwargs)
        self.lookback, self.threshold = lookback, threshold

    def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
        c = bars["Close"].astype(float)
        ret = c / c.shift(self.lookback) - 1.0
        sig = (ret > self.threshold).astype(float).where(ret.notna(), 0.0)
        sig.name = "target_weight"
        return sig
