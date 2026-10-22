"""CSV/JSON/Markdown export of run artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd


def export_run_bundle(artifact_dir: Path, summary: dict[str, Any]) -> dict[str, Path]:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    summary_path = artifact_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    paths["summary_json"] = summary_path

    # Flatten leaderboard if present
    lb = summary.get("leaderboard") or []
    if lb:
        df = pd.json_normalize(lb)
        p = artifact_dir / "leaderboard.csv"
        df.to_csv(p, index=False)
        paths["leaderboard_csv"] = p

    md = write_markdown_report(artifact_dir / "report.md", summary)
    paths["report_md"] = md
    return paths


def write_markdown_report(path: Path, summary: dict[str, Any]) -> Path:
    lines = [
        f"# QuantStrategyFinder Run `{summary.get('run_id', '')}`",
        "",
        f"- Created: {summary.get('created_at', 'N/A')}",
        f"- Git commit: `{summary.get('git_commit', 'N/A')}`",
        f"- Starting equity: ${summary.get('starting_equity', 200)}",
        "",
        "## Data provenance",
        "",
    ]
    for sym, prov in (summary.get("provenance") or {}).items():
        lines.append(
            f"- **{sym}**: source=`{prov.get('source')}`, "
            f"{prov.get('start')}→{prov.get('end')}, "
            f"n={prov.get('n_bars')}, hash=`{prov.get('content_hash', '')[:12]}…`"
        )
    lines += ["", "## Validation leaderboard", ""]
    lb = summary.get("leaderboard") or []
    if not lb:
        lines.append("**NO STRATEGY PASSED VALIDATION** (or no candidates evaluated).")
    else:
        any_pass = any(r.get("status") == "PASS" for r in lb)
        if not any_pass:
            lines.append("**NO STRATEGY PASSED VALIDATION**")
            lines.append("")
        lines.append("| Strategy | Symbol | Status | Val Sharpe | Test Total Return | Eligible |")
        lines.append("|---|---|---|---|---|---|")
        for r in lb:
            mt = (r.get("metrics_test") or {})
            mv = (r.get("metrics_val") or {})
            tr = mt.get("total_return")
            vs = mv.get("sharpe")
            lines.append(
                f"| {r.get('strategy_id')} | {r.get('symbol')} | {r.get('status')} | "
                f"{'N/A' if vs is None else f'{vs:.3f}'} | "
                f"{'N/A' if tr is None else f'{tr:.2%}'} | "
                f"{r.get('eligible_for_ranking')} |"
            )

    lines += [
        "",
        "## Notes",
        "",
        "- Research-only; not live trading advice.",
        "- Actual monthly returns are distinct from CAGR-derived monthly equivalents.",
        "",
    ]
    for w in summary.get("warnings") or []:
        lines.append(f"- Warning: {w}")

    path.write_text("\n".join(lines), encoding="utf-8")
    return path
