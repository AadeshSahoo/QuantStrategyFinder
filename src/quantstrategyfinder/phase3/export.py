"""Export Phase 3 CSV/MD deliverables from SQLite."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from quantstrategyfinder.phase3.store import PaperStore


def export_phase3_deliverables(
    store: PaperStore,
    cfg: dict[str, Any],
    perf: dict[str, Any],
    job_detail: dict[str, Any],
) -> dict[str, Path]:
    exports_dir = Path(cfg["persistence"]["exports_dir"])
    exports_dir.mkdir(parents=True, exist_ok=True)
    docs = Path("/cursor/stores/self/docs")
    docs.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}

    fills = pd.DataFrame(store.export_fills())
    trades_path = exports_dir / "phase3-paper-trades.csv"
    fills.to_csv(trades_path, index=False)
    (docs / "phase3-paper-trades.csv").write_bytes(trades_path.read_bytes())
    paths["paper_trades"] = trades_path

    perf_df = pd.DataFrame(perf.get("rows") or [])
    perf_path = exports_dir / "phase3-forward-performance.csv"
    perf_df.to_csv(perf_path, index=False)
    (docs / "phase3-forward-performance.csv").write_bytes(perf_path.read_bytes())
    paths["forward_performance"] = perf_path

    # Mirror config into docs
    cfg_src = Path("configs/phase3-forward-trading-config.yaml")
    if cfg_src.exists():
        (docs / "phase3-forward-trading-config.yaml").write_text(
            cfg_src.read_text(encoding="utf-8"), encoding="utf-8"
        )
        paths["docs_config"] = docs / "phase3-forward-trading-config.yaml"

    meta = store.registration_meta() or {}
    job = store.latest_job() or {}
    md = _validation_report_md(cfg, meta, job, perf, job_detail)
    md_path = exports_dir / "phase3-validation-report.md"
    md_path.write_text(md, encoding="utf-8")
    (docs / "phase3-validation-report.md").write_text(md, encoding="utf-8")
    paths["validation_report"] = md_path
    paths["docs_validation_report"] = docs / "phase3-validation-report.md"

    # Also dump orders/equity for dashboard
    pd.DataFrame(store.export_orders()).to_csv(exports_dir / "phase3-orders.csv", index=False)
    pd.DataFrame(store.export_equity()).to_csv(exports_dir / "phase3-equity.csv", index=False)
    (exports_dir / "last_job.json").write_text(json.dumps(job_detail, indent=2, default=str), encoding="utf-8")
    return paths


def _validation_report_md(
    cfg: dict[str, Any],
    meta: dict[str, Any],
    job: dict[str, Any],
    perf: dict[str, Any],
    detail: dict[str, Any],
) -> str:
    summary = perf.get("summary") or {}
    lines = [
        "# Phase 3 Forward Validation Report",
        "",
        "**Label:** SIMULATED PAPER TRADING — NOT LIVE BROKERAGE",
        "",
        f"- Config hash: `{meta.get('config_hash')}`",
        f"- Code version pin: `{meta.get('code_version')}`",
        f"- Registered at: {meta.get('registered_at')}",
        f"- Forward start: **{cfg.get('forward_start_date')}** (after Phase 2 OOS consumption)",
        f"- Candidates registered: **{meta.get('n_candidates')}**",
        f"- Latest job: id={job.get('id')} status=`{job.get('status')}` finished={job.get('finished_at')}",
        "",
        "## Integrity",
        "",
        "- Shortlist frozen before forward processing; parameters not re-optimized.",
        "- Phase 1/2 holdouts are **not** reused as fresh evidence.",
        "- Multiple-testing correction: Benjamini–Hochberg over **n=5** registered candidates.",
        "- No strategy is labeled STATISTICALLY VALIDATED on a short forward sample.",
        "",
        "## Summary counts",
        "",
        f"- Insufficient evidence: **{summary.get('n_insufficient_evidence')}**",
        f"- Forward running (unvalidated): **{summary.get('n_forward_running_unvalidated')}**",
        f"- Statistically validated: **{summary.get('n_statistically_validated', 0)}**",
        "",
        f"> {summary.get('message')}",
        "",
        "## Per-candidate",
        "",
        "| Candidate | Symbol | Days | Fills | Total return | vs BAH | Status |",
        "|---|---|---:|---:|---:|---:|---|",
    ]
    for r in perf.get("rows") or []:
        lines.append(
            f"| {r.get('candidate_id')} | {r.get('symbol')} | {r.get('n_equity_days')} | "
            f"{r.get('n_fills')} | {_pct(r.get('total_return'))} | "
            f"{_pct(r.get('excess_total_return_vs_bah'))} | `{r.get('validation_status')}` |"
        )
    lines += [
        "",
        "## Warnings / data notes",
        "",
    ]
    for w in detail.get("warnings") or []:
        lines.append(f"- {w}")
    if not detail.get("warnings"):
        lines.append("- (none)")
    lines += [
        "",
        "## Scheduler / hosting",
        "",
        detail.get(
            "scheduler_note",
            "See docs/phase3-scheduler.md — Cursor VM is not a continuous host.",
        ),
        "",
        "## Candidates & limitations",
        "",
    ]
    for c in cfg.get("candidates") or []:
        lines.append(f"### `{c['candidate_id']}`")
        lines.append(f"- Params: `{c.get('params')}`")
        lines.append(f"- Limitations: {c.get('phase2_limitations')}")
        lines.append("")
    return "\n".join(lines)


def _pct(x: Any) -> str:
    try:
        if x is None or (isinstance(x, float) and pd.isna(x)):
            return "N/A"
        return f"{float(x):.2%}"
    except (TypeError, ValueError):
        return "N/A"
