"""Donchian channel breakout baseline (first-party)."""

from __future__ import annotations

import pandas as pd

from .base import Strategy, StrategyMeta


class DonchianBreakout(Strategy):
    meta = StrategyMeta(
        id="donchian",
        version="1.0.0",
        name="Donchian Breakout",
        market="multi",
        timeframe="1d",
        description=(
            "Enter long when close breaks above prior N-day high; "
            "exit when close breaks below prior M-day low. Long/flat only."
        ),
        source_provenance="first-party baseline inspired by classic Donchian/Turtle rules",
        lookback=20,
    )

    def __init__(self, entry_lookback: int = 20, exit_lookback: int = 10, **kwargs) -> None:
        super().__init__(entry_lookback=entry_lookback, exit_lookback=exit_lookback, **kwargs)
        self.entry_lookback = entry_lookback
        self.exit_lookback = exit_lookback

    def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
        high = bars["High"].astype(float)
        low = bars["Low"].astype(float)
        close = bars["Close"].astype(float)

        # Prior channel (exclude current bar to avoid same-bar look-ahead)
        entry_level = high.shift(1).rolling(self.entry_lookback, min_periods=self.entry_lookback).max()
        exit_level = low.shift(1).rolling(self.exit_lookback, min_periods=self.exit_lookback).min()

        position = 0.0
        weights: list[float] = []
        for i in range(len(bars)):
            e = entry_level.iloc[i]
            x = exit_level.iloc[i]
            c = close.iloc[i]
            if pd.isna(e) or pd.isna(x):
                weights.append(0.0)
                continue
            if position == 0.0 and c > e:
                position = 1.0
            elif position == 1.0 and c < x:
                position = 0.0
            weights.append(position)

        return pd.Series(weights, index=bars.index, name="target_weight")
