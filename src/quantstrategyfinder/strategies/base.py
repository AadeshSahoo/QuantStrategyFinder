"""Stable strategy contract for baseline implementations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class StrategyMeta:
    id: str
    version: str
    name: str
    market: str
    timeframe: str
    description: str
    source_provenance: str
    lookback: int
    order_timing: str = "next_bar_open"
    position_sizing: str = "full_equity_long_flat"
    leverage: float = 1.0
    stop_exit_rules: str = "signal_flip"
    cost_model: str = "config_costs"
    data_requirements: str = "daily OHLCV"


@dataclass
class Signal:
    """Target position weight in [-1, 1]; fill occurs next bar open by engine."""

    timestamp: pd.Timestamp
    target_weight: float
    reason: str = ""


class Strategy(ABC):
    meta: StrategyMeta

    def __init__(self, **params: Any) -> None:
        self.params = params

    @abstractmethod
    def generate_signals(self, bars: pd.DataFrame) -> pd.Series:
        """
        Return a Series indexed like bars with target weight after close observation.
        Values in {-1, 0, 1} for MVP long/flat (or short if strategy supports it).
        Engine fills at the next bar's open.
        """

    def describe(self) -> dict[str, Any]:
        return {
            "id": self.meta.id,
            "version": self.meta.version,
            "name": self.meta.name,
            "market": self.meta.market,
            "timeframe": self.meta.timeframe,
            "description": self.meta.description,
            "source_provenance": self.meta.source_provenance,
            "lookback": self.meta.lookback,
            "order_timing": self.meta.order_timing,
            "position_sizing": self.meta.position_sizing,
            "leverage": self.meta.leverage,
            "stop_exit_rules": self.meta.stop_exit_rules,
            "cost_model": self.meta.cost_model,
            "data_requirements": self.meta.data_requirements,
            "params": self.params,
        }
