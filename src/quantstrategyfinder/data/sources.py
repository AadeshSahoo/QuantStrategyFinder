"""Market data download with explicit provenance (no fabricated bars)."""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import yfinance as yf

from .cache import cache_paths, load_cached_bars, save_cached_bars
from .validation import DataValidationError, validate_bars

logger = logging.getLogger(__name__)

SOURCE_NAME = "yfinance"
SOURCE_NOTES = (
    "Yahoo Finance via yfinance. Adjusted close used when adjusted=True. "
    "GLD is a gold ETF proxy, not XAUUSD or GC futures. "
    "BTC-USD is spot crypto quoted USD, not perpetual futures."
)


@dataclass
class DataProvenance:
    """Attribution metadata for a downloaded series."""

    symbol: str
    source: str
    source_notes: str
    interval: str
    adjusted: bool
    timezone: str
    retrieved_at: str
    start: str
    end: str
    n_bars: int
    content_hash: str
    columns: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _content_hash(df: pd.DataFrame) -> str:
    payload = df.to_csv(index=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _normalize_ohlcv(raw: pd.DataFrame, symbol: str, adjusted: bool) -> pd.DataFrame:
    if raw is None or raw.empty:
        raise DataValidationError(f"No bars returned for {symbol}")

    df = raw.copy()
    if isinstance(df.columns, pd.MultiIndex):
        # yfinance multi-ticker shape; take this symbol level if present
        if symbol in df.columns.get_level_values(-1):
            df = df.xs(symbol, axis=1, level=-1)
        else:
            df.columns = df.columns.get_level_values(0)

    df = df.rename(columns=str.title)
    required = ["Open", "High", "Low", "Close", "Volume"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise DataValidationError(f"{symbol}: missing columns {missing}")

    if adjusted and "Adj Close" in df.columns:
        # Scale OHLC to Adj Close so returns reflect dividends/splits consistently
        scale = df["Adj Close"] / df["Close"].replace(0, pd.NA)
        for col in ("Open", "High", "Low", "Close"):
            df[col] = df[col] * scale
        df = df.drop(columns=["Adj Close"], errors="ignore")

    out = df[required].copy()
    out.index = pd.to_datetime(out.index, utc=True).tz_convert("UTC")
    out.index.name = "Date"
    out = out.sort_index()
    out = out[~out.index.duplicated(keep="last")]
    out = out.dropna(subset=["Open", "High", "Low", "Close"])
    return out


def fetch_daily_ohlcv(
    symbol: str,
    *,
    lookback_years: int = 10,
    adjusted: bool = True,
    cache_dir: str | Path = "data/cache",
    force_refresh: bool = False,
) -> tuple[pd.DataFrame, DataProvenance]:
    """Download or load cached daily OHLCV with provenance."""
    cache_dir = Path(cache_dir)
    bars_path, prov_path = cache_paths(cache_dir, symbol, "1d")

    if not force_refresh and bars_path.exists() and prov_path.exists():
        df, prov = load_cached_bars(bars_path, prov_path)
        validate_bars(df, symbol=symbol)
        logger.info("Loaded cached %s (%d bars)", symbol, len(df))
        return df, prov

    period = f"{lookback_years}y"
    logger.info("Downloading %s daily bars from %s (period=%s)", symbol, SOURCE_NAME, period)
    ticker = yf.Ticker(symbol)
    raw = ticker.history(period=period, interval="1d", auto_adjust=False)
    df = _normalize_ohlcv(raw, symbol, adjusted=adjusted)
    warnings = validate_bars(df, symbol=symbol)

    retrieved_at = datetime.now(timezone.utc).isoformat()
    prov = DataProvenance(
        symbol=symbol,
        source=SOURCE_NAME,
        source_notes=SOURCE_NOTES,
        interval="1d",
        adjusted=adjusted,
        timezone="UTC",
        retrieved_at=retrieved_at,
        start=str(df.index[0].date()),
        end=str(df.index[-1].date()),
        n_bars=len(df),
        content_hash=_content_hash(df),
        columns=list(df.columns),
        warnings=warnings,
    )
    save_cached_bars(df, prov, bars_path, prov_path)
    return df, prov


def fetch_universe(
    symbols: list[str],
    *,
    lookback_years: int = 10,
    adjusted: bool = True,
    cache_dir: str | Path = "data/cache",
    force_refresh: bool = False,
) -> dict[str, tuple[pd.DataFrame, DataProvenance]]:
    """Fetch multiple symbols; fail per-symbol with clear errors (no silent substitutes)."""
    results: dict[str, tuple[pd.DataFrame, DataProvenance]] = {}
    errors: dict[str, str] = {}
    for symbol in symbols:
        try:
            results[symbol] = fetch_daily_ohlcv(
                symbol,
                lookback_years=lookback_years,
                adjusted=adjusted,
                cache_dir=cache_dir,
                force_refresh=force_refresh,
            )
        except Exception as exc:  # noqa: BLE001 — surface per-symbol failures
            errors[symbol] = str(exc)
            logger.error("Failed to fetch %s: %s", symbol, exc)
    if errors and not results:
        raise DataValidationError(
            "All downloads failed:\n" + "\n".join(f"  {k}: {v}" for k, v in errors.items())
        )
    if errors:
        # Persist error report next to cache for auditability
        err_path = Path(cache_dir) / "fetch_errors.json"
        err_path.parent.mkdir(parents=True, exist_ok=True)
        err_path.write_text(json.dumps(errors, indent=2), encoding="utf-8")
    return results
