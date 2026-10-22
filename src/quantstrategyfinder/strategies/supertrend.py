"""Supertrend-style ATR trail (first-party REIMPLEMENTATION)."""

from __future__ import annotations

import pandas as pd

from quantstrategyfinder.strategies.base import Strategy, StrategyMeta


def _atr(bars: pd.DataFrame, period: int) -> pd.Series:
    high, low, close = bars["High"].astype(float), bars["Low"].astype(float), bars["Close"].astype(float)
    prev = close.shift(1)
    tr = pd.concat([(high - low), (high - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)
    return tr.rolling(period, min_periods=period).mean()


class Supertrend(Strategy):
    meta = StrategyMeta(
        id="supertrend",
        version="1.0.0",
        name="Supertrend ATR Trail",
        market="multi",
        timeframe="1d",
        description=(
            "Long when close is above Supertrend line (HL2 - multiplier*ATR trail); "
            "flat when below. Classic Supertrend long/flat variant."
        ),
        source_provenance=(
            "FIRST-PARTY REIMPLEMENTATION of publicly documented Supertrend/ATR trail family "
            "(e.g. TradingView Supertrend concept). Upstream code not executed."
        ),
        lookback=10,
    )

    def __init__(self, atr_period: int = 10, multiplier: float = 3.0, **kwargs) -> None:
        super().__init__(atr_period=atr_period, multiplier=multiplier, **kwargs)
        self.atr_period = atr_period
        self.multiplier = multiplier

    def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
        high = bars["High"].astype(float)
        low = bars["Low"].astype(float)
        close = bars["Close"].astype(float)
        atr = _atr(bars, self.atr_period)
        hl2 = (high + low) / 2.0
        basic_ub = hl2 + self.multiplier * atr
        basic_lb = hl2 - self.multiplier * atr
        final_ub = basic_ub.copy()
        final_lb = basic_lb.copy()
        for i in range(1, len(bars)):
            if pd.isna(basic_ub.iloc[i]) or pd.isna(basic_lb.iloc[i]):
                continue
            final_ub.iloc[i] = (
                basic_ub.iloc[i]
                if basic_ub.iloc[i] < final_ub.iloc[i - 1] or close.iloc[i - 1] > final_ub.iloc[i - 1]
                else final_ub.iloc[i - 1]
            )
            final_lb.iloc[i] = (
                basic_lb.iloc[i]
                if basic_lb.iloc[i] > final_lb.iloc[i - 1] or close.iloc[i - 1] < final_lb.iloc[i - 1]
                else final_lb.iloc[i - 1]
            )
        st = pd.Series(index=bars.index, dtype=float)
        direction = 1.0
        for i in range(len(bars)):
            if pd.isna(final_lb.iloc[i]) or pd.isna(final_ub.iloc[i]):
                st.iloc[i] = float("nan")
                continue
            if i == 0:
                st.iloc[i] = final_lb.iloc[i]
                continue
            prev = st.iloc[i - 1]
            if direction == 1.0:
                if close.iloc[i] < final_lb.iloc[i]:
                    direction = -1.0
                    st.iloc[i] = final_ub.iloc[i]
                else:
                    st.iloc[i] = final_lb.iloc[i]
            else:
                if close.iloc[i] > final_ub.iloc[i]:
                    direction = 1.0
                    st.iloc[i] = final_lb.iloc[i]
                else:
                    st.iloc[i] = final_ub.iloc[i]
        sig = (close > st).astype(float).where(st.notna(), 0.0)
        sig.name = "target_weight"
        return sig
