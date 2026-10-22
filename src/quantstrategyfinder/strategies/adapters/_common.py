"""Shared helpers for adapter strategies."""

from __future__ import annotations

from quantstrategyfinder.strategies.base import StrategyMeta


def adapter_meta(
    *,
    id: str,
    name: str,
    description: str,
    lookback: int,
    source_note: str,
) -> StrategyMeta:
    return StrategyMeta(
        id=id,
        version="1.0.0",
        name=name,
        market="multi",
        timeframe="1d",
        description=description,
        source_provenance=(
            f"FIRST-PARTY ADAPTER / REIMPLEMENTATION. {source_note} "
            "Upstream repository code is never executed."
        ),
        lookback=lookback,
    )
