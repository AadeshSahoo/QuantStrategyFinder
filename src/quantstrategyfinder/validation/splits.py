"""Chronological train/validation/test splits (no shuffling)."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass
class SplitResult:
    train: pd.DataFrame
    val: pd.DataFrame
    test: pd.DataFrame
    train_frac: float
    val_frac: float
    test_frac: float

    def summary(self) -> dict:
        def _range(df: pd.DataFrame) -> dict:
            if df.empty:
                return {"n": 0, "start": None, "end": None}
            return {
                "n": int(len(df)),
                "start": str(df.index[0].date()),
                "end": str(df.index[-1].date()),
            }

        return {
            "train": _range(self.train),
            "val": _range(self.val),
            "test": _range(self.test),
            "fractions": {
                "train": self.train_frac,
                "val": self.val_frac,
                "test": self.test_frac,
            },
        }


def chronological_split(
    bars: pd.DataFrame,
    *,
    train_frac: float = 0.50,
    val_frac: float = 0.25,
    test_frac: float = 0.25,
) -> SplitResult:
    if abs(train_frac + val_frac + test_frac - 1.0) > 1e-9:
        raise ValueError("train_frac + val_frac + test_frac must equal 1.0")
    n = len(bars)
    if n < 3:
        raise ValueError(f"Need at least 3 bars to split; got {n}")

    i_train = int(n * train_frac)
    i_val = i_train + int(n * val_frac)
    # Ensure each slice has at least one bar when possible
    i_train = max(1, min(i_train, n - 2))
    i_val = max(i_train + 1, min(i_val, n - 1))

    train = bars.iloc[:i_train].copy()
    val = bars.iloc[i_train:i_val].copy()
    test = bars.iloc[i_val:].copy()
    return SplitResult(
        train=train,
        val=val,
        test=test,
        train_frac=train_frac,
        val_frac=val_frac,
        test_frac=test_frac,
    )
