"""Phase 2 market universe and instrument metadata."""

from __future__ import annotations

from typing import Any


ASSET_CLASS_BY_SYMBOL: dict[str, str] = {}


def build_symbol_map(cfg: dict[str, Any]) -> dict[str, str]:
    """Return symbol -> asset_class from phase2 config."""
    out: dict[str, str] = {}
    for cls, syms in (cfg.get("universe") or {}).items():
        for s in syms or []:
            out[s] = cls
    return out


def periods_per_year(asset_class: str, cfg: dict[str, Any]) -> float:
    ann = cfg.get("annualization") or {}
    return float(ann.get(asset_class, 252))


def feasibility_constraints(symbol: str, asset_class: str, cfg: dict[str, Any]) -> dict[str, Any]:
    """Cash-account $200 path constraints (no short/margin/futures)."""
    cons = cfg.get("constraints") or {}
    reasons: list[str] = []
    ok = True
    if cons.get("allow_short") is False:
        pass  # strategies are long/flat
    if asset_class == "fx":
        min_n = float(cons.get("fx_min_notional_usd", 1000.0))
        if min_n > float(cfg.get("starting_equity", 200.0)):
            ok = False
            reasons.append(
                f"FX standard lot / min notional ~${min_n:.0f} exceeds $200 cash account "
                "(micro-lot broker not assumed)."
            )
    if asset_class == "crypto":
        reasons.append("Crypto spot fractional OK in research model; exchange eligibility varies.")
    return {
        "feasible_200": ok,
        "reasons": reasons or ["Long-only cash path; fractional shares allowed for equity/ETF/crypto research."],
        "allow_short": bool(cons.get("allow_short", False)),
        "allow_margin": bool(cons.get("allow_margin", False)),
    }
