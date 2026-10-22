from __future__ import annotations

import pandas as pd

from quantstrategyfinder.strategies.base import Strategy

from ._common import adapter_meta


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, pd.NA)
    return 100 - (100 / (1 + rs))


class RSIReversion(Strategy):
    meta = adapter_meta(
        id="rsi_reversion",
        name="RSI Mean Reversion (adapter)",
        description="Long when RSI < oversold; exit when RSI > exit level. Long/flat.",
        lookback=14,
        source_note="RSI mean-reversion family.",
    )

    def __init__(
        self, period: int = 14, oversold: float = 30.0, exit_level: float = 50.0, **kwargs
    ) -> None:
        super().__init__(period=period, oversold=oversold, exit_level=exit_level, **kwargs)
        self.period, self.oversold, self.exit_level = period, oversold, exit_level

    def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
        rsi = _rsi(bars["Close"].astype(float), self.period)
        pos = 0.0
        out: list[float] = []
        for v in rsi:
            if pd.isna(v):
                out.append(0.0)
                continue
            if pos == 0.0 and v < self.oversold:
                pos = 1.0
            elif pos == 1.0 and v > self.exit_level:
                pos = 0.0
            out.append(pos)
        return pd.Series(out, index=bars.index, name="target_weight")
