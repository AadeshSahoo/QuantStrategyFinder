"""Streamlit dashboard — real run artifacts + discovery queue (never executes upstream)."""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pandas as pd
import streamlit as st


def _parse_reports_dir() -> Path:
    if "--reports-dir" in sys.argv:
        i = sys.argv.index("--reports-dir")
        if i + 1 < len(sys.argv):
            return Path(sys.argv[i + 1])
    return Path("reports")


REPORTS_DIR = _parse_reports_dir()
PHASE2_DIR = Path("reports/phase2")
DISCOVERY_DB = Path("data/discovery/candidates.sqlite")


def list_phase2_runs(phase2_dir: Path = PHASE2_DIR) -> list[str]:
    if not phase2_dir.exists():
        return []
    runs = []
    for p in sorted(phase2_dir.iterdir(), reverse=True):
        if p.is_dir() and (p / "summary.json").exists() and p.name.startswith("phase2_"):
            runs.append(p.name)
    return runs


def render_phase2(phase2_dir: Path = PHASE2_DIR) -> None:
    """Phase 2 pages: Overview, Leaderboard, Details, $200 Simulator, Research Audit."""
    st.title("QuantStrategyFinder — Phase 2")
    st.caption(
        "Multi-market research. Dual boards never merge. "
        "UNVALIDATED — RESEARCH ONLY is not a live recommendation. No fabricated metrics."
    )
    runs = list_phase2_runs(phase2_dir)
    if not runs:
        st.error(
            f"No Phase 2 runs under `{phase2_dir.resolve()}`. "
            "Run `qsf phase2 smoke` then `qsf phase2 run`."
        )
        return
    run_id = st.sidebar.selectbox("Phase 2 run", runs)
    art = phase2_dir / run_id
    summary = json.loads((art / "summary.json").read_text(encoding="utf-8"))
    results_path = art / "phase2_strategy_results.csv"
    if not results_path.exists():
        st.error("Missing phase2_strategy_results.csv")
        return
    df = pd.read_csv(results_path)

    tab_ov, tab_lb, tab_det, tab_sim, tab_audit = st.tabs(
        ["Overview", "Leaderboard", "Strategy Details", "$200 Simulator", "Research Audit"]
    )

    with tab_ov:
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Strategies", summary.get("n_strategies"))
        c2.metric("Symbols loaded", summary.get("n_symbols_loaded"))
        c3.metric("Combinations OK", summary.get("n_combinations_ok"))
        c4.metric("Validated", summary.get("n_validated"))
        c5.metric("Experimental", summary.get("n_experimental"))
        if summary.get("n_validated", 0) == 0:
            st.warning("No strategy met statistically validated criteria.")
        else:
            val = df[df["board"] == "validated"]
            if not val.empty and "oos_sharpe" in val.columns:
                best = val.sort_values("oos_sharpe", ascending=False).iloc[0]
                st.success(
                    f"Best validated Sharpe: `{best['strategy_id']}` @ `{best['symbol']}` "
                    f"= {best['oos_sharpe']:.3f}"
                )
        st.json(
            {
                k: summary.get(k)
                for k in (
                    "run_id",
                    "created_at",
                    "git_commit",
                    "holdout_note",
                    "gates",
                )
            }
        )

    with tab_lb:
        st.subheader("Dual leaderboards")
        board = st.radio(
            "Board",
            ["Statistically Validated", "Experimental (UNVALIDATED — RESEARCH ONLY)"],
            horizontal=True,
        )
        view = df[df["board"] == ("validated" if board.startswith("Stat") else "experimental")].copy()
        ac = st.multiselect(
            "Asset class",
            sorted(view["asset_class"].dropna().unique()) if "asset_class" in view.columns else [],
        )
        if ac:
            view = view[view["asset_class"].isin(ac)]
        max_dd = st.slider("Max |drawdown| filter", 0.05, 1.0, 1.0, 0.05)
        if "oos_max_drawdown" in view.columns:
            view = view[view["oos_max_drawdown"].abs().fillna(1) <= max_dd]
        min_cagr = st.number_input("Min OOS CAGR", value=-1.0, step=0.01)
        if "oos_cagr" in view.columns:
            view = view[view["oos_cagr"].fillna(-9) >= min_cagr]
        min_sh = st.number_input("Min OOS Sharpe", value=-5.0, step=0.1)
        if "oos_sharpe" in view.columns:
            view = view[view["oos_sharpe"].fillna(-9) >= min_sh]
        only_200 = st.checkbox("$200 feasible only", value=False)
        if only_200 and "feasible_200" in view.columns:
            view = view[view["feasible_200"] == True]  # noqa: E712
        if board.startswith("Stat") and view.empty:
            st.info("Validated board is empty — gates were not loosened.")
        st.dataframe(view, use_container_width=True, height=420)
        if board.startswith("Exp"):
            st.caption("Experimental rows are UNVALIDATED — RESEARCH ONLY.")

    with tab_det:
        ok = df[df.get("status", "ok") == "ok"] if "status" in df.columns else df
        if ok.empty:
            st.info("No completed rows.")
        else:
            labels = [f"{r.strategy_id} @ {r.symbol} [{r.board}]" for r in ok.itertuples()]
            choice = st.selectbox("Combination", labels)
            r = ok.iloc[labels.index(choice)]
            st.write(
                f"**{r.get('label', '')}** · fidelity `{r.get('fidelity')}` · "
                f"[source]({r.get('source_url')})"
            )
            st.json(
                {
                    "params": r.get("strategy_params"),
                    "failure_reasons": r.get("failure_reasons"),
                    "oos_cagr": r.get("oos_cagr"),
                    "benchmark_cagr": r.get("benchmark_cagr"),
                    "oos_sharpe": r.get("oos_sharpe"),
                    "oos_max_drawdown": r.get("oos_max_drawdown"),
                    "bootstrap_ci": [
                        r.get("bootstrap_monthly_ci_low"),
                        r.get("bootstrap_monthly_ci_high"),
                    ],
                }
            )
            stem = r.get("stem") or f"{r['strategy_id']}_{str(r['symbol']).replace('=', '_')}"
            eq_path = art / f"equity_{stem}.csv"
            if eq_path.exists():
                eq = pd.read_csv(eq_path, parse_dates=["Date"], index_col="Date")
                st.line_chart(eq["equity"], height=260)
                dd = eq["equity"] / eq["equity"].cummax() - 1.0
                st.line_chart(dd.rename("drawdown"), height=180)
            trades = art / f"trades_{stem}.csv"
            if trades.exists():
                st.write("Trade ledger")
                st.dataframe(pd.read_csv(trades), use_container_width=True)

    with tab_sim:
        st.subheader("$200 account simulator (historical path)")
        feas = df[df.get("feasible_200") == True] if "feasible_200" in df.columns else df  # noqa: E712
        st.metric("Feasible combinations", len(feas))
        show = df[
            [
                c
                for c in [
                    "strategy_id",
                    "symbol",
                    "asset_class",
                    "feasible_200",
                    "sim_200_end_equity",
                    "sim_200_worst_dd_usd",
                    "oos_max_drawdown",
                    "board",
                    "label",
                    "feasibility_reasons",
                ]
                if c in df.columns
            ]
        ]
        st.dataframe(show, use_container_width=True, height=400)
        st.caption(
            "Dollar paths are historical simulations under research cost assumptions — "
            "not guaranteed income."
        )

    with tab_audit:
        st.subheader("Research audit")
        for name in (
            "phase2_statistical_audit.csv",
            "phase2_data_provenance.csv",
            "phase2_research_summary.md",
        ):
            p = art / name
            if not p.exists():
                st.warning(f"Missing {name}")
                continue
            st.markdown(f"**{name}**")
            if name.endswith(".md"):
                st.markdown(p.read_text(encoding="utf-8"))
            else:
                st.dataframe(pd.read_csv(p), use_container_width=True, height=320)
        st.info(summary.get("holdout_note", ""))


def list_run_ids(reports_dir: Path) -> list[str]:
    if not reports_dir.exists():
        return []
    runs = []
    for p in sorted(reports_dir.iterdir(), reverse=True):
        if p.is_dir() and (p / "summary.json").exists():
            runs.append(p.name)
    return runs


def load_summary(reports_dir: Path, run_id: str) -> dict:
    path = reports_dir / run_id / "summary.json"
    return json.loads(path.read_text(encoding="utf-8"))


def load_discovery_rows(db_path: Path = DISCOVERY_DB) -> list[dict]:
    if not db_path.exists():
        return []
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM candidates ORDER BY shortlisted DESC, reproducibility_score DESC, stars DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def equity_stem(row: dict) -> str:
    sid, sym = row.get("strategy_id"), row.get("symbol")
    if row.get("kind") == "adapter" or (row.get("attribution") or {}).get("adapter_id"):
        return f"adapter_{sid}_{sym}"
    return f"{sid}_{sym}"


def main() -> None:
    st.set_page_config(page_title="QuantStrategyFinder", layout="wide")
    mode = st.sidebar.radio("Mode", ["Phase 1", "Phase 2"], index=1)
    if mode == "Phase 2":
        render_phase2()
        return

    st.title("QuantStrategyFinder")
    st.caption(
        "Research-only. Metrics come from recorded run artifacts — never hardcoded demo numbers. "
        "Discovery never executes third-party GitHub code."
    )

    runs = list_run_ids(REPORTS_DIR)
    discovery_rows = load_discovery_rows()

    tab_overview, tab_discover, tab_board, tab_audit, tab_detail, tab_data, tab_feas = st.tabs(
        [
            "Overview",
            "Discovery Queue",
            "Leaderboard",
            "P1 Audit",
            "Strategy Detail",
            "Data Provenance",
            "$200 Feasibility",
        ]
    )

    run_id = None
    summary: dict = {}
    artifact_dir = REPORTS_DIR

    with st.sidebar:
        st.subheader("Backtest run")
        if runs:
            run_id = st.selectbox("Run ID", runs)
            summary = load_summary(REPORTS_DIR, run_id)
            artifact_dir = Path(summary.get("artifact_dir") or (REPORTS_DIR / run_id))
            st.markdown(f"**Created:** {summary.get('created_at', 'N/A')}")
            st.markdown(f"**Git:** `{summary.get('git_commit', 'N/A')}`")
            st.markdown(f"**Equity:** ${summary.get('starting_equity', 200)}")
            st.markdown(f"**Kind:** `{summary.get('kind', 'baseline')}`")
            if not summary.get("any_passed"):
                st.warning(summary.get("message") or "NO STRATEGY PASSED VALIDATION")
            counts = summary.get("counts") or {}
            if counts:
                st.json(counts)
        else:
            st.info("No backtest runs yet. Discovery queue still available.")

    with tab_discover:
        st.subheader("GitHub discovery queue")
        st.write(
            "Metadata-only search results. Upstream repositories are **never executed**. "
            "Approved items authorize first-party adapters only (`REIMPLEMENTATION` by default)."
        )
        if not discovery_rows:
            st.warning(
                f"No candidates in `{DISCOVERY_DB}`. Run `qsf discover` then "
                "`qsf review approve-mapped` / `qsf evaluate-discovered`."
            )
        else:
            short = [r for r in discovery_rows if r.get("shortlisted")]
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Discovered", len(discovery_rows))
            c2.metric("Shortlisted", len(short))
            c3.metric(
                "OPEN SOURCE",
                sum(1 for r in discovery_rows if r.get("open_source_badge") == "OPEN SOURCE"),
            )
            c4.metric(
                "Approved",
                sum(1 for r in discovery_rows if r.get("review_status") == "approved"),
            )
            view = st.radio("Show", ["Shortlist", "All"], horizontal=True)
            rows = short if view == "Shortlist" else discovery_rows
            table = pd.DataFrame(
                [
                    {
                        "repo": r.get("repo_full_name"),
                        "stars": r.get("stars"),
                        "license": r.get("license_spdx"),
                        "badge": r.get("open_source_badge"),
                        "score": r.get("reproducibility_score"),
                        "adapter": r.get("adapter_id"),
                        "fidelity": r.get("fidelity"),
                        "status": r.get("review_status"),
                        "url": r.get("html_url"),
                    }
                    for r in rows
                ]
            )
            st.dataframe(table, use_container_width=True)
            st.caption("Claimed upstream README metrics are AUTHOR-CLAIMED only — not verified here.")

    with tab_overview:
        st.subheader("Run overview")
        if not summary:
            st.info("Select a run in the sidebar (after `qsf backtest` or `qsf evaluate-discovered`).")
        else:
            c1, c2, c3 = st.columns(3)
            c1.metric("Symbols", len(summary.get("symbols") or []))
            c2.metric("Strategies", len(summary.get("strategies") or []))
            n_pass = sum(1 for r in summary.get("leaderboard") or [] if r.get("status") == "PASS")
            c3.metric("PASS count", n_pass)
            st.write("Symbols:", ", ".join(summary.get("symbols") or []))
            for w in summary.get("warnings") or []:
                st.warning(w)
            if summary.get("safety"):
                st.info(f"Safety: {summary['safety']}")
            report_path = artifact_dir / "report.md"
            if report_path.exists():
                with st.expander("Markdown report"):
                    st.markdown(report_path.read_text(encoding="utf-8"))

    with tab_board:
        st.subheader("Validation leaderboard")
        rows = summary.get("leaderboard") or []
        if not rows:
            st.info("No candidates evaluated in the selected run.")
        else:
            table = []
            for r in rows:
                mt = r.get("metrics_test") or {}
                mv = r.get("metrics_val") or {}
                fm = r.get("full_sample_metrics") or {}
                attr = r.get("attribution") or {}
                table.append(
                    {
                        "rank": r.get("rank"),
                        "strategy": r.get("strategy_id"),
                        "symbol": r.get("symbol"),
                        "status": r.get("status"),
                        "eligible": r.get("eligible_for_ranking"),
                        "val_sharpe": mv.get("sharpe"),
                        "oos_cagr": mt.get("cagr"),
                        "oos_total_return": mt.get("total_return"),
                        "oos_max_dd": mt.get("max_drawdown"),
                        "actual_mean_monthly": fm.get("actual_mean_monthly_return"),
                        "monthly_from_cagr": fm.get("monthly_compounded_equivalent"),
                        "feasibility_200": r.get("feasibility_200"),
                        "fidelity": attr.get("fidelity"),
                        "source_repo": attr.get("source_repo"),
                        "n_trades": fm.get("n_trades"),
                    }
                )
            st.dataframe(pd.DataFrame(table), use_container_width=True)
            st.caption(
                "Ranking uses validation Sharpe, then OOS (test) CAGR, then lower |max DD|. "
                "actual_mean_monthly is observed; monthly_from_cagr is derived from CAGR."
            )
            eligible = summary.get("eligible_ranked") or []
            if not eligible:
                st.warning(summary.get("message") or "NO STRATEGY PASSED VALIDATION")

    with tab_audit:
        st.subheader("P1 comprehensive audit")
        st.caption(
            "Frozen-artifact audit (no re-optimization). "
            "PASS ≠ proven profitability. Monthly compounded equivalent is derived from CAGR, "
            "not an observed monthly return."
        )
        audit_csv = None
        if run_id:
            cand = artifact_dir / "p1_audit_report.csv"
            if cand.exists():
                audit_csv = cand
        if audit_csv is None:
            root_csv = REPORTS_DIR / "p1_audit_report.csv"
            if root_csv.exists():
                audit_csv = root_csv
        if audit_csv is None or not audit_csv.exists():
            st.warning(
                "No audit CSV found. Run `qsf audit-p1 --run-id <RUN>` to generate "
                "`reports/<run>/p1_audit_report.csv`."
            )
        else:
            adf = pd.read_csv(audit_csv)
            meta_path = audit_csv.parent / "p1_audit_meta.json"
            if meta_path.exists():
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                if meta.get("message"):
                    st.error(meta["message"])
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Rows", meta.get("n_rows"))
                c2.metric("PASS", meta.get("n_pass"))
                c3.metric("PASS justified", meta.get("n_pass_justified"))
                c4.metric("Credible +OOS vs BAH", meta.get("n_credible_positive_oos"))
            st.write("Comparison table (all strategy/symbol pairs)")
            show_cols = [
                c
                for c in [
                    "audit_rank",
                    "strategy_id",
                    "symbol",
                    "github_url",
                    "fidelity",
                    "validation_status",
                    "oos_cagr",
                    "oos_monthly_compounded_equivalent",
                    "oos_actual_mean_monthly_return",
                    "oos_actual_median_monthly_return",
                    "oos_max_drawdown",
                    "oos_sharpe",
                    "oos_sortino",
                    "oos_profit_factor",
                    "oos_win_rate",
                    "oos_n_trades",
                    "oos_activity_count",
                    "estimated_oos_trading_costs_usd",
                    "benchmark_cagr",
                    "benchmark_max_dd",
                    "excess_oos_cagr_vs_bah",
                    "cost_stress_2x_val_sharpe",
                    "cost_stress_3x_val_sharpe",
                    "bootstrap_monthly_mean_ci_low",
                    "bootstrap_monthly_mean_ci_high",
                    "feasibility_200",
                    "credible_positive_oos",
                    "credible_reason",
                    "insufficient_sample_flags",
                ]
                if c in adf.columns
            ]
            st.dataframe(adf[show_cols], use_container_width=True, height=480)
            st.download_button(
                "Download audit CSV",
                data=audit_csv.read_bytes(),
                file_name="p1_audit_report.csv",
                mime="text/csv",
            )
            with st.expander("Trading rules & bias notes (per row sample)"):
                st.dataframe(
                    adf[
                        [
                            c
                            for c in [
                                "strategy_id",
                                "symbol",
                                "trading_rules",
                                "rule_match_notes",
                                "cost_assumptions",
                                "bias_findings",
                                "pass_disclaimer",
                            ]
                            if c in adf.columns
                        ]
                    ],
                    use_container_width=True,
                )

    with tab_detail:
        st.subheader("Strategy detail")
        rows = summary.get("leaderboard") or []
        labels = [f"{r['strategy_id']} @ {r['symbol']} [{r['status']}]" for r in rows]
        if not labels:
            st.info("Nothing to show.")
        else:
            choice = st.selectbox("Candidate", labels)
            r = rows[labels.index(choice)]
            stem = equity_stem(r)
            if r.get("attribution"):
                st.markdown("**Attribution / fidelity**")
                st.json(r["attribution"])
            st.json({"status": r["status"], "reasons": r.get("reasons")})
            if r.get("cost_stress_val"):
                st.write("Cost stress (validation window)")
                st.json(r["cost_stress_val"])
            if r.get("walkforward"):
                st.write("Walk-forward diagnostic")
                st.json(r["walkforward"])
            eq_path = artifact_dir / f"equity_{stem}.csv"
            if eq_path.exists():
                eq = pd.read_csv(eq_path, parse_dates=["Date"], index_col="Date")
                st.line_chart(eq["equity"], height=280)
                peak = eq["equity"].cummax()
                dd = eq["equity"] / peak - 1.0
                st.line_chart(dd.rename("drawdown"), height=200)
                fm = r.get("full_sample_metrics") or {}
                months = fm.get("actual_monthly_returns") or {}
                if months:
                    st.write("Actual monthly returns")
                    st.dataframe(
                        pd.Series(months, name="actual_monthly_return").to_frame(),
                        use_container_width=True,
                    )
            else:
                st.warning(f"Equity file missing: {eq_path.name}")
            trades_path = artifact_dir / f"trades_{stem}.csv"
            if trades_path.exists():
                st.write("Trade ledger")
                st.dataframe(pd.read_csv(trades_path), use_container_width=True)
            result_path = artifact_dir / f"result_{stem}.json"
            if result_path.exists():
                with st.expander("Full result JSON"):
                    st.json(json.loads(result_path.read_text(encoding="utf-8")))

    with tab_data:
        st.subheader("Data provenance")
        prov = summary.get("provenance") or {}
        if not prov:
            st.info("No provenance on selected run.")
        else:
            for sym, p in prov.items():
                st.markdown(
                    f"**{sym}** — source `{p.get('source')}`, "
                    f"{p.get('start')} → {p.get('end')}, bars={p.get('n_bars')}, "
                    f"adjusted={p.get('adjusted')}, tz={p.get('timezone')}"
                )
                st.code(p.get("content_hash", ""), language=None)
                st.caption(p.get("source_notes", ""))
                for w in p.get("warnings") or []:
                    st.warning(w)

    with tab_feas:
        st.subheader("$200 account feasibility")
        if not summary:
            st.info("Select a run to inspect feasibility diagnostics.")
        else:
            st.write(
                "Orders that need more cash than available or fall below min notional are rejected. "
                f"Starting equity: **${summary.get('starting_equity', 200)}**."
            )
            st.write(
                "Futures margin / crypto perpetual funding are **not** modeled (P2). "
                "GLD is a gold ETF proxy, not XAUUSD."
            )
            found = False
            for path in sorted(artifact_dir.glob("result_*.json")):
                data = json.loads(path.read_text(encoding="utf-8"))
                rejs = data.get("rejections") or []
                if rejs:
                    found = True
                    st.write(f"Rejections in `{path.name}`: {len(rejs)}")
                    st.dataframe(pd.DataFrame(rejs), use_container_width=True)
            if not found:
                st.info("No order rejections recorded in this run.")
            if run_id:
                st.download_button(
                    "Download summary.json",
                    data=json.dumps(summary, indent=2, default=str),
                    file_name=f"{run_id}_summary.json",
                    mime="application/json",
                )


if __name__ == "__main__":
    main()
