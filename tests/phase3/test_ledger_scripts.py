"""Tests for durable ledger restore/persist helpers (no remote push)."""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

import yaml


EXPECTED = "774936e63dedec57f05aac1831aee23f3e3ddcdc634ef9ff4c9b1d6b58f3fd8f"


def test_frozen_config_hash_unchanged():
    raw = Path("configs/phase3-forward-trading-config.yaml").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == EXPECTED
    cfg = yaml.safe_load(raw)
    assert cfg["n_candidates_registered"] == 5
    ids = [c["candidate_id"] for c in cfg["candidates"]]
    assert ids == [
        "atr_breakout_ETH-USD",
        "tsmom_NVDA",
        "zscore_reversion_META",
        "bollinger_reversion_AMZN",
        "dual_sma_SHY",
    ]


def test_verify_hash_script():
    env = os.environ.copy()
    env["PHASE3_EXPECTED_CONFIG_HASH"] = EXPECTED
    r = subprocess.run(
        ["bash", "scripts/phase3_ledger.sh", "verify-hash"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert r.returncode == 0, r.stdout + r.stderr
