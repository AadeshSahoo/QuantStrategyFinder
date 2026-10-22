"""Local cache for OHLCV bars and provenance JSON."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pandas as pd

if TYPE_CHECKING:
    from .sources import DataProvenance


def cache_paths(cache_dir: Path, symbol: str, interval: str) -> tuple[Path, Path]:
    safe = symbol.replace("/", "_").replace("^", "_")
    base = Path(cache_dir) / f"{safe}_{interval}"
    return base.with_suffix(".csv"), Path(str(base) + ".provenance.json")


def save_cached_bars(
    df: pd.DataFrame,
    provenance: "DataProvenance",
    bars_path: Path,
    prov_path: Path,
) -> None:
    bars_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(bars_path, index=True)
    prov_path.write_text(json.dumps(provenance.to_dict(), indent=2), encoding="utf-8")


def load_cached_bars(
    bars_path: Path,
    prov_path: Path,
) -> tuple[pd.DataFrame, "DataProvenance"]:
    from .sources import DataProvenance

    df = pd.read_csv(bars_path, index_col=0, parse_dates=True)
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    else:
        df.index = df.index.tz_convert("UTC")
    raw: dict[str, Any] = json.loads(prov_path.read_text(encoding="utf-8"))
    prov = DataProvenance(**raw)
    return df, prov
