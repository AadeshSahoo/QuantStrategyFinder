from __future__ import annotations

import pandas as pd

from quantstrategyfinder.strategies.base import Strategy

from ._common import adapter_meta


class ZScoreReversion(Strategy):
    meta = adapter_meta(
        id="zscore_reversion",
        name="Z-Score Mean Reversion (adapter)",
        description="Long when z-score < -entry; exit when z-score > -exit. Long/flat.",
        lookback=20,
        source_note="Rolling z-score mean-reversion family.",
    )

    def __init__(
        self, window: int = 20, entry_z: float = 1.5, exit_z: float = 0.25, **kwargs
    ) -> None:
        super().__init__(window=window, entry_z=entry_z, exit_z=exit_z, **kwargs)
        self.window, self.entry_z, self.exit_z = window, entry_z, exit_z

    def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
        c = bars["Close"].astype(float)
        mu = c.rolling(self.window, min_periods=self.window).mean()
        sd = c.rolling(self.window, min_periods=self.window).std(ddof=0)
        z = (c - mu) / sd.replace(0, pd.NA)
        pos = 0.0
        out: list[float] = []
        for v in z:
            if pd.isna(v):
                out.append(0.0)
                continue
            if pos == 0.0 and v < -self.entry_z:
                pos = 1.0
            elif pos == 1.0 and v > -self.exit_z:
                pos = 0.0
            out.append(pos)
        return pd.Series(out, index=bars.index, name="target_weight")
