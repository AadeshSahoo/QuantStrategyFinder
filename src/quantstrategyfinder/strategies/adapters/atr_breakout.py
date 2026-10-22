from __future__ import annotations

import pandas as pd

from quantstrategyfinder.strategies.base import Strategy

from ._common import adapter_meta


def _atr(bars: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = bars["High"].astype(float), bars["Low"].astype(float), bars["Close"].astype(float)
    prev = close.shift(1)
    tr = pd.concat(
        [(high - low), (high - prev).abs(), (low - prev).abs()],
        axis=1,
    ).max(axis=1)
    return tr.rolling(period, min_periods=period).mean()


class ATRBreakout(Strategy):
    meta = adapter_meta(
        id="atr_breakout",
        name="ATR Volatility Breakout (adapter)",
        description="Long when close > prior close + k*ATR; exit on close < prior close - k*ATR.",
        lookback=20,
        source_note="ATR / volatility-breakout family.",
    )

    def __init__(self, atr_period: int = 14, k: float = 2.0, **kwargs) -> None:
        super().__init__(atr_period=atr_period, k=k, **kwargs)
        self.atr_period, self.k = atr_period, k

    def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
        close = bars["Close"].astype(float)
        atr = _atr(bars, self.atr_period)
        pos = 0.0
        out: list[float] = []
        for i in range(len(bars)):
            if i == 0 or pd.isna(atr.iloc[i]):
                out.append(0.0)
                continue
            up = close.iloc[i - 1] + self.k * atr.iloc[i]
            dn = close.iloc[i - 1] - self.k * atr.iloc[i]
            c = close.iloc[i]
            if pos == 0.0 and c > up:
                pos = 1.0
            elif pos == 1.0 and c < dn:
                pos = 0.0
            out.append(pos)
        return pd.Series(out, index=bars.index, name="target_weight")
