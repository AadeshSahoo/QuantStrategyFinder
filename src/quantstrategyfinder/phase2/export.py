"""Write required Phase 2 output files (§11)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd


REQUIRED = [
    "phase2_strategy_results.csv",
    "phase2_validated_leaderboard.csv",
    "phase2_experimental_leaderboard.csv",
    "phase2_statistical_audit.csv",
    "phase2_data_provenance.csv",
    "phase2_200_account_simulations.csv",
    "phase2_research_summary.md",
]


def write_phase2_outputs(
    out_dir: Path,
    rows: list[dict[str, Any]],
    provenance: dict[str, Any],
    summary: dict[str, Any],
) -> dict[str, Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows)
    paths: dict[str, Path] = {}

    results_path = out_dir / "phase2_strategy_results.csv"
    df.to_csv(results_path, index=False)
    paths["results"] = results_path

    val = df[df.get("board") == "validated"].copy() if "board" in df.columns else df.iloc[0:0]
    if not val.empty:
        val = val.sort_values(
            by=["oos_sharpe", "excess_oos_cagr", "oos_max_drawdown"],
            ascending=[False, False, False],
        )
        val.insert(0, "rank", range(1, len(val) + 1))
    val_path = out_dir / "phase2_validated_leaderboard.csv"
    val.to_csv(val_path, index=False)
    paths["validated"] = val_path

    exp = df[df.get("board") == "experimental"].copy() if "board" in df.columns else df.copy()
    exp_path = out_dir / "phase2_experimental_leaderboard.csv"
    exp.to_csv(exp_path, index=False)
    paths["experimental"] = exp_path

    audit_cols = [
        c
        for c in [
            "strategy_id",
            "symbol",
            "asset_class",
            "board",
            "label",
            "failure_reasons",
            "bh_fdr_pass",
            "excess_bootstrap_p",
            "bootstrap_monthly_ci_low",
            "bootstrap_monthly_ci_high",
            "bootstrap_p_mean_le_0",
            "oos_cagr",
            "benchmark_cagr",
            "excess_oos_cagr",
            "oos_max_drawdown",
            "oos_sharpe",
            "oos_activity",
            "oos_n_bars",
            "cost_stress_2x_val_sharpe",
            "feasible_200",
            "fidelity",
            "source_url",
        ]
        if c in df.columns
    ]
    audit_path = out_dir / "phase2_statistical_audit.csv"
    df[audit_cols].to_csv(audit_path, index=False)
    paths["audit"] = audit_path

    prov_rows = []
    for sym, p in provenance.items():
        prov_rows.append(
            {
                "symbol": sym,
                "asset_class": p.get("asset_class"),
                "source": p.get("source"),
                "source_notes": p.get("source_notes"),
                "interval": p.get("interval"),
                "adjusted": p.get("adjusted"),
                "timezone": p.get("timezone"),
                "start": p.get("start"),
                "end": p.get("end"),
                "n_bars": p.get("n_bars"),
                "content_hash": p.get("content_hash"),
                "retrieved_at": p.get("retrieved_at"),
                "warnings": json.dumps(p.get("warnings") or []),
                "periods_per_year": p.get("periods_per_year"),
                "limitations": (
                    "Yahoo Finance via yfinance — best-effort free feed; not a licensed "
                    "institutional dataset. FX/crypto conventions simplified."
                ),
            }
        )
    prov_path = out_dir / "phase2_data_provenance.csv"
    pd.DataFrame(prov_rows).to_csv(prov_path, index=False)
    paths["provenance"] = prov_path

    sim_cols = [
        c
        for c in [
            "strategy_id",
            "symbol",
            "asset_class",
            "feasible_200",
            "feasibility_reasons",
            "sim_200_end_equity",
            "sim_200_worst_dd_usd",
            "oos_max_drawdown",
            "oos_cagr",
            "board",
            "label",
        ]
        if c in df.columns
    ]
    sim_path = out_dir / "phase2_200_account_simulations.csv"
    df[sim_cols].to_csv(sim_path, index=False)
    paths["sim200"] = sim_path

    md_path = out_dir / "phase2_research_summary.md"
    md_path.write_text(_research_summary_md(summary, df, val), encoding="utf-8")
    paths["summary_md"] = md_path

    # Also copy canonical names to reports/phase2/ root for easy discovery
    root = out_dir.parent
    for name in REQUIRED:
        src = out_dir / name
        if src.exists():
            (root / name).write_bytes(src.read_bytes())

    # Docs copy of research summary
    docs = Path("/cursor/stores/self/docs/phase2_research_summary.md")
    docs.parent.mkdir(parents=True, exist_ok=True)
    docs.write_text(md_path.read_text(encoding="utf-8"), encoding="utf-8")
    paths["docs_summary"] = docs

    return paths


def _pct(x: Any) -> str:
    try:
        if x is None or (isinstance(x, float) and pd.isna(x)):
            return "N/A"
        return f"{float(x):.2%}"
    except (TypeError, ValueError):
        return "N/A"


def _research_summary_md(summary: dict[str, Any], df: pd.DataFrame, val: pd.DataFrame) -> str:
    n_ok = int(summary.get("n_combinations_ok") or 0)
    n_val = int(summary.get("n_validated") or 0)
    lines = [
        "# Phase 2 Research Summary",
        "",
        f"**Run ID:** `{summary.get('run_id')}`  ",
        f"**Created:** {summary.get('created_at')}  ",
        f"**Git:** `{summary.get('git_commit')}`  ",
        "",
        "## Counts",
        "",
        f"- Strategies configured: **{summary.get('n_strategies')}**",
        f"- Symbols loaded: **{summary.get('n_symbols_loaded')}** / requested {summary.get('n_symbols_requested')}",
        f"- Combinations completed (ok): **{n_ok}**",
        f"- Statistically validated: **{n_val}**",
        f"- Experimental (UNVALIDATED — RESEARCH ONLY): **{summary.get('n_experimental')}**",
        "",
        "> Validated gates were **not** loosened to populate the leaderboard. "
        "PASS/validated ≠ guaranteed future profits.",
        "",
        f"**Holdout:** {summary.get('holdout_note')}",
        "",
    ]
    if n_val == 0:
        lines += [
            "## Finding",
            "",
            "**No strategy met the precommitted statistically validated criteria** "
            "(positive OOS after costs, CI support, beat buy-and-hold, activity/sample, "
            "drawdown, cost stress, $200 feasibility, and BH-FDR).",
            "",
        ]
    else:
        best_ret = val.sort_values("oos_cagr", ascending=False).iloc[0]
        best_dd = val.sort_values("oos_max_drawdown", ascending=False).iloc[0]
        best_sh = val.sort_values("oos_sharpe", ascending=False).iloc[0]
        lines += [
            "## Validated highlights",
            "",
            f"- Highest OOS CAGR: `{best_ret['strategy_id']}` @ `{best_ret['symbol']}` "
            f"({_pct(best_ret.get('oos_cagr'))})",
            f"- Lowest |drawdown|: `{best_dd['strategy_id']}` @ `{best_dd['symbol']}` "
            f"(DD {_pct(best_dd.get('oos_max_drawdown'))})",
            f"- Strongest Sharpe: `{best_sh['strategy_id']}` @ `{best_sh['symbol']}` "
            f"(Sharpe {best_sh.get('oos_sharpe')})",
            "",
        ]

    feas = df[(df.get("feasible_200") == True) & (df.get("status") == "ok")] if "feasible_200" in df.columns else df.iloc[0:0]  # noqa: E712
    lines += [
        "## $200 feasibility",
        "",
        f"- Combinations marked feasible under cash-account assumptions: **{len(feas)}**",
        "- FX majors are generally **not** feasible at $200 without assuming micro-lots.",
        "",
        "## Further evidence required before real capital",
        "",
        "1. A **new** untouched holdout or paper-trading window (this OOS is consumed).",
        "2. Broker-specific fees, borrow, and eligibility checks.",
        "3. Stronger multiple-testing controls if the strategy library expands further.",
        "4. Live/paper monitoring for regime shift and execution slippage.",
        "",
        "## Data limitations",
        "",
        "- Source: Yahoo Finance via `yfinance` (best-effort).",
        "- Survivorship: liquid surviving symbols only.",
        "- Crypto annualization uses 365; session markets use 252.",
        "- All strategies are **REIMPLEMENTATION** (first-party); upstream code not executed.",
        "",
    ]
    if summary.get("fetch_errors"):
        lines += ["### Fetch errors", "", "```json", json.dumps(summary["fetch_errors"], indent=2), "```", ""]
    return "\n".join(lines)
