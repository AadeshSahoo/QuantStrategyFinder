"""Volatility-targeted trend (SMA filter + inverse-vol weight cap at 1)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from quantstrategyfinder.strategies.base import Strategy, StrategyMeta


class VolTargetTrend(Strategy):
    meta = StrategyMeta(
        id="vol_target_trend",
        version="1.0.0",
        name="Vol-Targeted Trend",
        market="multi",
        timeframe="1d",
        description=(
            "Long when close > SMA; position weight = min(1, target_vol / realized_vol). "
            "Long/flat cash otherwise."
        ),
        source_provenance=(
            "FIRST-PARTY REIMPLEMENTATION of volatility-targeting + trend filter concepts "
            "common in CTA/risk-parity literature. Not a licensed proprietary model."
        ),
        lookback=60,
    )

    def __init__(
        self,
        sma: int = 100,
        vol_lookback: int = 20,
        target_vol: float = 0.15,
        **kwargs,
    ) -> None:
        super().__init__(sma=sma, vol_lookback=vol_lookback, target_vol=target_vol, **kwargs)
        self.sma = sma
        self.vol_lookback = vol_lookback
        self.target_vol = target_vol

    def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
        close = bars["Close"].astype(float)
        ma = close.rolling(self.sma, min_periods=self.sma).mean()
        rets = close.pct_change()
        # Annualize with 252 by default in signal; engine marks daily
        vol = rets.rolling(self.vol_lookback, min_periods=self.vol_lookback).std() * np.sqrt(252)
        raw = (self.target_vol / vol.replace(0, np.nan)).clip(upper=1.0)
        sig = raw.where(close > ma, 0.0).fillna(0.0)
        sig.name = "target_weight"
        return sig
