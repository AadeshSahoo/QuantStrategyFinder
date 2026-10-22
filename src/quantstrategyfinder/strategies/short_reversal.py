"""Short-term reversal (1–5 day) long/flat REIMPLEMENTATION."""

from __future__ import annotations

import pandas as pd

from quantstrategyfinder.strategies.base import Strategy, StrategyMeta


class ShortReversal(Strategy):
    meta = StrategyMeta(
        id="short_reversal",
        version="1.0.0",
        name="Short-Term Reversal",
        market="multi",
        timeframe="1d",
        description=(
            "Long when prior N-day return is below -threshold (oversold bounce); "
            "flat after M days or when rebound exceeds exit. Simplified long/flat variant "
            "of short-term reversal anomalies."
        ),
        source_provenance=(
            "FIRST-PARTY REIMPLEMENTATION inspired by published short-term reversal literature "
            "(e.g. Jegadeesh 1990 family). Not a bit-exact paper reproduction."
        ),
        lookback=5,
    )

    def __init__(
        self,
        lookback: int = 5,
        entry_threshold: float = -0.03,
        hold_days: int = 5,
        **kwargs,
    ) -> None:
        super().__init__(
            lookback=lookback, entry_threshold=entry_threshold, hold_days=hold_days, **kwargs
        )
        self.lookback = lookback
        self.entry_threshold = entry_threshold
        self.hold_days = hold_days

    def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
        close = bars["Close"].astype(float)
        ret = close / close.shift(self.lookback) - 1.0
        out: list[float] = []
        hold_left = 0
        for i in range(len(bars)):
            r = ret.iloc[i]
            if hold_left > 0:
                hold_left -= 1
                out.append(1.0)
                continue
            if pd.isna(r):
                out.append(0.0)
                continue
            if r <= self.entry_threshold:
                hold_left = self.hold_days - 1
                out.append(1.0)
            else:
                out.append(0.0)
        return pd.Series(out, index=bars.index, name="target_weight")
