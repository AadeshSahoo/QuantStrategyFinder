"""Plot helpers for reports/dashboard (optional matplotlib)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd


def save_equity_csv(equity: pd.Series, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    equity.to_csv(path, header=["equity"])
