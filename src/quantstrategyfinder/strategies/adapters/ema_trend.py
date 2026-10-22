from __future__ import annotations

import pandas as pd

from quantstrategyfinder.strategies.base import Strategy

from ._common import adapter_meta


class EMATrend(Strategy):
    meta = adapter_meta(
        id="ema_trend",
        name="EMA Trend (adapter)",
        description="Long when close > EMA(span); flat otherwise.",
        lookback=50,
        source_note="Exponential moving-average trend filter family.",
    )

    def __init__(self, span: int = 50, **kwargs) -> None:
        super().__init__(span=span, **kwargs)
        self.span = span

    def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
        c = bars["Close"].astype(float)
        ema = c.ewm(span=self.span, adjust=False, min_periods=self.span).mean()
        sig = (c > ema).astype(float).where(ema.notna(), 0.0)
        sig.name = "target_weight"
        return sig
