"""First-party adapters for approved discovery mappings.

Upstream GitHub code is NEVER imported or executed.
All adapters are REIMPLEMENTATION unless a human upgrades fidelity.
"""

from __future__ import annotations

from quantstrategyfinder.strategies.base import Strategy

from .atr_breakout import ATRBreakout
from .bollinger import BollingerReversion
from .dual_sma import DualSMA
from .ema_trend import EMATrend
from .macd_cross import MACDCross
from .roc_momentum import ROCMomentum
from .rsi_reversion import RSIReversion
from .tsmom import TSMOM12
from .turtle_breakout import TurtleBreakout
from .zscore_reversion import ZScoreReversion

ADAPTER_REGISTRY: dict[str, type[Strategy]] = {
    DualSMA.meta.id: DualSMA,
    EMATrend.meta.id: EMATrend,
    RSIReversion.meta.id: RSIReversion,
    BollingerReversion.meta.id: BollingerReversion,
    TurtleBreakout.meta.id: TurtleBreakout,
    TSMOM12.meta.id: TSMOM12,
    MACDCross.meta.id: MACDCross,
    ROCMomentum.meta.id: ROCMomentum,
    ZScoreReversion.meta.id: ZScoreReversion,
    ATRBreakout.meta.id: ATRBreakout,
}


def get_adapter(adapter_id: str, **params) -> Strategy:
    if adapter_id not in ADAPTER_REGISTRY:
        raise KeyError(
            f"Unknown adapter '{adapter_id}'. Known: {sorted(ADAPTER_REGISTRY)}"
        )
    return ADAPTER_REGISTRY[adapter_id](**params)


__all__ = [
    "ADAPTER_REGISTRY",
    "get_adapter",
    "DualSMA",
    "EMATrend",
    "RSIReversion",
    "BollingerReversion",
    "TurtleBreakout",
    "TSMOM12",
    "MACDCross",
    "ROCMomentum",
    "ZScoreReversion",
    "ATRBreakout",
]
