from __future__ import annotations

import pandas as pd

from quantstrategyfinder.strategies.base import Strategy

from ._common import adapter_meta


class ROCMomentum(Strategy):
    meta = adapter_meta(
        id="roc_momentum",
        name="Rate-of-Change Momentum (adapter)",
        description="Long when N-day ROC > 0; flat otherwise.",
        lookback=20,
        source_note="Rate-of-change momentum family.",
    )

    def __init__(self, lookback: int = 20, **kwargs) -> None:
        super().__init__(lookback=lookback, **kwargs)
        self.lookback = lookback

    def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
        c = bars["Close"].astype(float)
        roc = c.pct_change(self.lookback)
        sig = (roc > 0).astype(float).where(roc.notna(), 0.0)
        sig.name = "target_weight"
        return sig
