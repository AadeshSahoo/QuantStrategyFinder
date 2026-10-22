from .base import Strategy, StrategyMeta, Signal
from .donchian import DonchianBreakout
from .ma_trend import MovingAverageTrend
from .momentum import TimeSeriesMomentum

STRATEGY_REGISTRY: dict[str, type[Strategy]] = {
    MovingAverageTrend.meta.id: MovingAverageTrend,
    DonchianBreakout.meta.id: DonchianBreakout,
    TimeSeriesMomentum.meta.id: TimeSeriesMomentum,
}


def get_strategy(strategy_id: str, **params) -> Strategy:
    if strategy_id not in STRATEGY_REGISTRY:
        raise KeyError(f"Unknown strategy '{strategy_id}'. Known: {list(STRATEGY_REGISTRY)}")
    return STRATEGY_REGISTRY[strategy_id](**params)


__all__ = [
    "Strategy",
    "StrategyMeta",
    "Signal",
    "MovingAverageTrend",
    "DonchianBreakout",
    "TimeSeriesMomentum",
    "STRATEGY_REGISTRY",
    "get_strategy",
]
