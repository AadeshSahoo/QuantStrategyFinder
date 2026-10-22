from __future__ import annotations

import pandas as pd

from quantstrategyfinder.strategies.base import Strategy

from ._common import adapter_meta


class MACDCross(Strategy):
    meta = adapter_meta(
        id="macd_cross",
        name="MACD Signal Cross (adapter)",
        description="Long when MACD line > signal line; flat otherwise.",
        lookback=26,
        source_note="MACD crossover family.",
    )

    def __init__(self, fast: int = 12, slow: int = 26, signal: int = 9, **kwargs) -> None:
        super().__init__(fast=fast, slow=slow, signal=signal, **kwargs)
        self.fast, self.slow, self.signal = fast, slow, signal

    def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
        c = bars["Close"].astype(float)
        ema_fast = c.ewm(span=self.fast, adjust=False).mean()
        ema_slow = c.ewm(span=self.slow, adjust=False).mean()
        macd = ema_fast - ema_slow
        sig_line = macd.ewm(span=self.signal, adjust=False).mean()
        warm = macd.notna() & sig_line.notna()
        out = (macd > sig_line).astype(float).where(warm, 0.0)
        # zero until slow period
        out.iloc[: self.slow] = 0.0
        out.name = "target_weight"
        return out
