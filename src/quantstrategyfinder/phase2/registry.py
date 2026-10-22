"""Phase 2 strategy registry (first-party only)."""

from __future__ import annotations

from typing import Any

from quantstrategyfinder.strategies.adapters import ADAPTER_REGISTRY, get_adapter
from quantstrategyfinder.strategies.base import Strategy
from quantstrategyfinder.strategies.short_reversal import ShortReversal
from quantstrategyfinder.strategies.supertrend import Supertrend
from quantstrategyfinder.strategies.vol_target_trend import VolTargetTrend

PHASE2_EXTRA: dict[str, type[Strategy]] = {
    Supertrend.meta.id: Supertrend,
    ShortReversal.meta.id: ShortReversal,
    VolTargetTrend.meta.id: VolTargetTrend,
}

# Citation URLs for research audit (conceptual sources — not executed)
SOURCE_CITATIONS: dict[str, dict[str, str]] = {
    "dual_sma": {
        "source": "Classic dual moving-average cross (public domain concept)",
        "url": "https://en.wikipedia.org/wiki/Moving_average_crossover",
        "fidelity": "REIMPLEMENTATION",
    },
    "ema_trend": {
        "source": "EMA trend filter family",
        "url": "https://www.investopedia.com/terms/e/ema.asp",
        "fidelity": "REIMPLEMENTATION",
    },
    "tsmom": {
        "source": "Time-series momentum (Moskowitz, Ooi, Pedersen 2012 family)",
        "url": "https://doi.org/10.1016/j.jfineco.2011.11.003",
        "fidelity": "REIMPLEMENTATION",
    },
    "turtle_breakout": {
        "source": "Donchian/Turtle channel breakout family",
        "url": "https://en.wikipedia.org/wiki/Turtle_trading",
        "fidelity": "REIMPLEMENTATION",
    },
    "atr_breakout": {
        "source": "ATR volatility breakout family",
        "url": "https://www.investopedia.com/terms/a/atr.asp",
        "fidelity": "REIMPLEMENTATION",
    },
    "rsi_reversion": {
        "source": "RSI mean reversion family (Wilder)",
        "url": "https://www.investopedia.com/terms/r/rsi.asp",
        "fidelity": "REIMPLEMENTATION",
    },
    "bollinger_reversion": {
        "source": "Bollinger Band mean reversion family",
        "url": "https://www.investopedia.com/terms/b/bollingerbands.asp",
        "fidelity": "REIMPLEMENTATION",
    },
    "zscore_reversion": {
        "source": "Rolling z-score mean reversion",
        "url": "https://en.wikipedia.org/wiki/Standard_score",
        "fidelity": "REIMPLEMENTATION",
    },
    "macd_cross": {
        "source": "MACD signal-line cross (Appel)",
        "url": "https://www.investopedia.com/terms/m/macd.asp",
        "fidelity": "REIMPLEMENTATION",
    },
    "roc_momentum": {
        "source": "Rate-of-change momentum",
        "url": "https://www.investopedia.com/terms/p/pricerateofchange.asp",
        "fidelity": "REIMPLEMENTATION",
    },
    "supertrend": {
        "source": "Supertrend ATR trail (public TradingView-style concept)",
        "url": "https://www.tradingview.com/support/solutions/43000616964-supertrend/",
        "fidelity": "REIMPLEMENTATION",
    },
    "short_reversal": {
        "source": "Short-term reversal anomaly literature (Jegadeesh family)",
        "url": "https://doi.org/10.1111/j.1540-6261.1990.tb02428.x",
        "fidelity": "REIMPLEMENTATION",
    },
    "vol_target_trend": {
        "source": "Volatility targeting + trend filter (CTA/risk literature)",
        "url": "https://www.aqr.com/Insights/Research",
        "fidelity": "REIMPLEMENTATION",
    },
}


def get_phase2_strategy(strategy_id: str, **params: Any) -> Strategy:
    if strategy_id in PHASE2_EXTRA:
        return PHASE2_EXTRA[strategy_id](**params)
    if strategy_id in ADAPTER_REGISTRY:
        return get_adapter(strategy_id, **params)
    raise KeyError(f"Unknown Phase 2 strategy '{strategy_id}'")


def list_phase2_strategies() -> list[str]:
    return sorted(set(ADAPTER_REGISTRY) | set(PHASE2_EXTRA))
