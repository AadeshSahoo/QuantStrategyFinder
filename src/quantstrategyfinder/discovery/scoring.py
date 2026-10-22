"""Reproducibility heuristics for shortlisting (metadata only — no code exec)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional


def infer_markets(text: str, market_keywords: dict[str, list[str]]) -> list[str]:
    t = (text or "").lower()
    hits: list[str] = []
    for market, kws in (market_keywords or {}).items():
        if any(kw.lower() in t for kw in kws):
            hits.append(market)
    return hits or ["unspecified"]


def reproducibility_score(
    *,
    stars: int,
    language: Optional[str],
    license_badge: str,
    description: str,
    updated_at: Optional[str],
    query_hits: list[str],
) -> float:
    """
    Heuristic 0–100 for research-quality shortlisting.
    Higher = more likely worth manual review / adapter mapping.
    """
    score = 0.0
    if license_badge == "OPEN SOURCE":
        score += 35.0
    elif "UNKNOWN" in license_badge:
        score += 5.0

    if (language or "").lower() == "python":
        score += 15.0
    elif language:
        score += 5.0

    # Stars (log-ish)
    if stars >= 5000:
        score += 20.0
    elif stars >= 1000:
        score += 15.0
    elif stars >= 100:
        score += 10.0
    elif stars >= 20:
        score += 6.0
    elif stars >= 5:
        score += 3.0

    desc = (description or "").lower()
    for kw, pts in (
        ("backtest", 8.0),
        ("strategy", 4.0),
        ("quant", 3.0),
        ("trading", 3.0),
        ("documentation", 2.0),
        ("reproduc", 5.0),
        ("notebook", 2.0),
    ):
        if kw in desc:
            score += pts

    # Recency
    if updated_at:
        try:
            ts = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
            age_days = (datetime.now(timezone.utc) - ts).days
            if age_days <= 365:
                score += 8.0
            elif age_days <= 365 * 3:
                score += 4.0
        except ValueError:
            pass

    score += min(6.0, 2.0 * len(set(query_hits or [])))
    return round(min(100.0, score), 2)


def suggest_adapter(
    text: str, adapter_families: dict[str, list[str]]
) -> tuple[Optional[str], str]:
    """
    Map description keywords to a first-party adapter family.
    Fidelity is always REIMPLEMENTATION until a human verifies bit-exact reproduction.
    """
    t = (text or "").lower()
    best: Optional[str] = None
    best_hits = 0
    for family, kws in (adapter_families or {}).items():
        hits = sum(1 for kw in kws if kw.lower() in t)
        if hits > best_hits:
            best_hits = hits
            best = family
    if best is None:
        return None, "UNMAPPED"
    return best, "REIMPLEMENTATION"
