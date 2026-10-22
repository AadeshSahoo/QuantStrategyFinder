"""Lightweight run metadata models (SQLite-backed via repository)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RunRecord:
    run_id: str
    created_at: str
    git_commit: str | None
    config: dict[str, Any]
    symbols: list[str]
    strategies: list[str]
    status: str
    warnings: list[str] = field(default_factory=list)
    artifact_dir: str = ""
