from __future__ import annotations

import pandas as pd

from quantstrategyfinder.strategies.base import Strategy

from ._common import adapter_meta


class TurtleBreakout(Strategy):
    meta = adapter_meta(
        id="turtle_breakout",
        name="Turtle-style Breakout (adapter)",
        description="Enter on N-day high breakout; exit on M-day low. Long/flat.",
        lookback=55,
        source_note="Donchian/Turtle channel-breakout family.",
    )

    def __init__(self, entry: int = 55, exit_: int = 20, **kwargs) -> None:
        super().__init__(entry=entry, exit=exit_, **kwargs)
        self.entry, self.exit_ = entry, exit_

    def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
        high, low, close = bars["High"].astype(float), bars["Low"].astype(float), bars["Close"].astype(float)
        entry_lvl = high.shift(1).rolling(self.entry, min_periods=self.entry).max()
        exit_lvl = low.shift(1).rolling(self.exit_, min_periods=self.exit_).min()
        pos = 0.0
        out: list[float] = []
        for i in range(len(bars)):
            e, x, c = entry_lvl.iloc[i], exit_lvl.iloc[i], close.iloc[i]
            if pd.isna(e) or pd.isna(x):
                out.append(0.0)
                continue
            if pos == 0.0 and c > e:
                pos = 1.0
            elif pos == 1.0 and c < x:
                pos = 0.0
            out.append(pos)
        return pd.Series(out, index=bars.index, name="target_weight")
