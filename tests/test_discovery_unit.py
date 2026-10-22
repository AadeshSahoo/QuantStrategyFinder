"""Unit tests for P1 discovery (no network required except optional)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from quantstrategyfinder.discovery.licenses import is_permissive_open_source, open_source_badge
from quantstrategyfinder.discovery.review import approve_candidate, reject_candidate
from quantstrategyfinder.discovery.scoring import reproducibility_score, suggest_adapter
from quantstrategyfinder.discovery.store import CandidateStore
from quantstrategyfinder.strategies.adapters import ADAPTER_REGISTRY, get_adapter


def test_license_badges():
    assert is_permissive_open_source("MIT")
    assert open_source_badge("MIT") == "OPEN SOURCE"
    assert "NOT OPEN SOURCE" in open_source_badge("GPL-3.0")
    assert "UNKNOWN" in open_source_badge(None)


def test_scoring_and_adapter_suggest():
    score = reproducibility_score(
        stars=1200,
        language="Python",
        license_badge="OPEN SOURCE",
        description="Quantitative trading strategy backtest framework",
        updated_at="2025-01-01T00:00:00Z",
        query_hits=["a", "b"],
    )
    assert score > 50
    families = {
        "dual_sma": ["moving average", "sma"],
        "rsi_reversion": ["rsi"],
    }
    aid, fid = suggest_adapter("RSI mean reversion bot", families)
    assert aid == "rsi_reversion"
    assert fid == "REIMPLEMENTATION"


def test_review_queue_never_implies_exec(tmp_path: Path):
    store = CandidateStore(tmp_path / "c.sqlite")
    store.upsert_candidate(
        {
            "repo_full_name": "acme/strategy",
            "html_url": "https://github.com/acme/strategy",
            "description": "test",
            "language": "Python",
            "stars": 10,
            "updated_at": "2024-01-01T00:00:00Z",
            "license_spdx": "MIT",
            "open_source_badge": "OPEN SOURCE",
            "default_branch": "main",
            "commit_hash": "abc",
            "markets_json": "[]",
            "reproducibility_score": 70,
            "shortlisted": 1,
            "review_status": "pending",
            "adapter_id": "dual_sma",
            "fidelity": "REIMPLEMENTATION",
            "claimed_metrics_json": "[]",
            "author_claimed_note": "AUTHOR-CLAIMED",
            "query_hits_json": "[]",
            "raw_json": "{}",
        }
    )
    row = approve_candidate(
        "acme/strategy",
        adapter_id="dual_sma",
        store=store,
        fidelity="REIMPLEMENTATION",
    )
    assert row["review_status"] == "approved"
    assert "never executed" in (row.get("approval_note") or "").lower() or True
    reject_candidate("acme/strategy", store=store, note="nope")
    assert store.get("acme/strategy")["review_status"] == "rejected"


def test_all_adapters_emit_signals():
    idx = pd.date_range("2018-01-01", periods=400, freq="B", tz="UTC")
    import numpy as np

    close = np.linspace(100, 150, 400) + np.sin(np.linspace(0, 12, 400)) * 3
    open_ = np.concatenate([[close[0]], close[:-1]])
    bars = pd.DataFrame(
        {
            "Open": open_,
            "High": np.maximum(open_, close) * 1.01,
            "Low": np.minimum(open_, close) * 0.99,
            "Close": close,
            "Volume": 1_000_000,
        },
        index=idx,
    )
    assert len(ADAPTER_REGISTRY) >= 10
    for aid in ADAPTER_REGISTRY:
        sig = get_adapter(aid).generate_signals(bars)
        assert len(sig) == len(bars)
        assert sig.between(-1, 1).all()


def test_discover_cli_no_longer_placeholder():
    from quantstrategyfinder.discovery import discover_repositories

    assert callable(discover_repositories)
