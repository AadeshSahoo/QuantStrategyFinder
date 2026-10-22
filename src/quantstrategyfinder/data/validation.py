"""OHLCV integrity checks — flag issues; never invent bars."""

from __future__ import annotations

import pandas as pd


class DataValidationError(Exception):
    """Raised when bars are unusable for backtesting."""


def validate_bars(df: pd.DataFrame, *, symbol: str, min_bars: int = 60) -> list[str]:
    """Validate OHLCV frame. May drop a few bad rows in-place. Returns warnings; raises on fatal issues."""
    warnings: list[str] = []
    if df is None or df.empty:
        raise DataValidationError(f"{symbol}: empty frame")

    required = ["Open", "High", "Low", "Close", "Volume"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise DataValidationError(f"{symbol}: missing columns {missing}")

    if df.index.has_duplicates:
        raise DataValidationError(f"{symbol}: duplicate timestamps")

    if not df.index.is_monotonic_increasing:
        raise DataValidationError(f"{symbol}: index not sorted ascending")

    prices = df[["Open", "High", "Low", "Close"]]
    if (prices <= 0).any().any():
        raise DataValidationError(f"{symbol}: non-positive prices present")

    # Relative epsilon: Yahoo sometimes emits a partial in-progress daily bar
    # (e.g. crypto Close > High). Drop those rows; never invent replacements.
    rel = 1e-8
    bad_ohlc = (
        (df["High"] * (1 + rel) < df["Low"])
        | (df["High"] * (1 + rel) < df["Open"])
        | (df["High"] * (1 + rel) < df["Close"])
        | (df["Low"] * (1 - rel) > df["Open"])
        | (df["Low"] * (1 - rel) > df["Close"])
    )
    n_bad = int(bad_ohlc.sum())
    if n_bad:
        # Allow dropping up to 5% of bars (FX/Yahoo quirks); never invent replacements.
        max_drop = max(3, int(0.05 * len(df)))
        if n_bad > max_drop:
            raise DataValidationError(
                f"{symbol}: {n_bad} bars with inconsistent OHLC (limit {max_drop})"
            )
        bad_dates = [str(ts.date()) for ts in df.index[bad_ohlc]]
        preview = bad_dates[:8] + (["…"] if len(bad_dates) > 8 else [])
        warnings.append(
            f"{symbol}: dropped {n_bad} inconsistent OHLC bar(s) "
            f"(often in-progress/bad Yahoo prints): {preview}"
        )
        df.drop(df.index[bad_ohlc], inplace=True)

    if len(df) < min_bars:
        raise DataValidationError(f"{symbol}: only {len(df)} bars (need >= {min_bars})")

    if (df["Volume"] < 0).any():
        raise DataValidationError(f"{symbol}: negative volume")

    zero_vol = int((df["Volume"] == 0).sum())
    if zero_vol:
        warnings.append(f"{symbol}: {zero_vol} zero-volume bars")

    # Gap heuristic: large calendar gaps (e.g., missing sessions for equities)
    deltas = df.index.to_series().diff().dt.days.dropna()
    if not deltas.empty:
        large = int((deltas > 10).sum())
        if large:
            warnings.append(f"{symbol}: {large} gaps > 10 calendar days (may be holidays/weekends)")

    return warnings

