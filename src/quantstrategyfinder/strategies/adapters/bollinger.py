from __future__ import annotations

import pandas as pd

from quantstrategyfinder.strategies.base import Strategy

from ._common import adapter_meta


class BollingerReversion(Strategy):
    meta = adapter_meta(
        id="bollinger_reversion",
        name="Bollinger Mean Reversion (adapter)",
        description="Long when close < lower band; flat when close > mid. Long/flat.",
        lookback=20,
        source_note="Bollinger-band mean-reversion family.",
    )

    def __init__(self, window: int = 20, n_std: float = 2.0, **kwargs) -> None:
        super().__init__(window=window, n_std=n_std, **kwargs)
        self.window, self.n_std = window, n_std

    def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
        c = bars["Close"].astype(float)
        mid = c.rolling(self.window, min_periods=self.window).mean()
        std = c.rolling(self.window, min_periods=self.window).std(ddof=0)
        lower = mid - self.n_std * std
        pos = 0.0
        out: list[float] = []
        for i in range(len(c)):
            if pd.isna(lower.iloc[i]) or pd.isna(mid.iloc[i]):
                out.append(0.0)
                continue
            if pos == 0.0 and c.iloc[i] < lower.iloc[i]:
                pos = 1.0
            elif pos == 1.0 and c.iloc[i] > mid.iloc[i]:
                pos = 0.0
            out.append(pos)
        return pd.Series(out, index=bars.index, name="target_weight")
