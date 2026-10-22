#!/usr/bin/env python3
"""Cron/systemd entrypoint for Phase 3 paper trading (SIMULATED)."""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from quantstrategyfinder.phase3.paper_engine import register_config, run_paper_job  # noqa: E402


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = ROOT / "configs" / "phase3-forward-trading-config.yaml"
    register_config(cfg)
    detail = run_paper_job(cfg)
    print(json.dumps({"job_id": detail.get("job_id"), "exports": detail.get("exports"),
                      "summary": detail.get("performance_summary"),
                      "scheduler_note": detail.get("scheduler_note")}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
