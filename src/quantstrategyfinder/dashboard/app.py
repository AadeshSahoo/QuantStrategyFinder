"""Streamlit dashboard — displays real run artifacts only."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

# Allow `streamlit run ... -- --reports-dir X`
def _parse_reports_dir() -> Path:
    if "--reports-dir" in sys.argv:
        i = sys.argv.index("--reports-dir")
        if i + 1 < len(sys.argv):
            return Path(sys.argv[i + 1])
    return Path("reports")


REPORTS_DIR = _parse_reports_dir()


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


def main() -> None:
    st.set_page_config(page_title="QuantStrategyFinder", layout="wide")
    st.title("QuantStrategyFinder")
    st.caption(
        "Research-only. Metrics come from recorded run artifacts — never hardcoded demo numbers."
    )

    runs = list_run_ids(REPORTS_DIR)
    if not runs:
        st.error(
            f"No runs found under `{REPORTS_DIR.resolve()}`. "
            "Run `qsf backtest` first to generate artifacts."
        )
        st.stop()

    run_id = st.sidebar.selectbox("Run ID", runs)
    summary = load_summary(REPORTS_DIR, run_id)
    artifact_dir = Path(summary.get("artifact_dir") or (REPORTS_DIR / run_id))

    st.sidebar.markdown(f"**Created:** {summary.get('created_at', 'N/A')}")
    st.sidebar.markdown(f"**Git:** `{summary.get('git_commit', 'N/A')}`")
    st.sidebar.markdown(f"**Equity:** ${summary.get('starting_equity', 200)}")

    if not summary.get("any_passed"):
        st.warning(summary.get("message") or "NO STRATEGY PASSED VALIDATION")

    tab_overview, tab_board, tab_detail, tab_data, tab_feas = st.tabs(
        ["Overview", "Leaderboard", "Strategy Detail", "Data Provenance", "$200 Feasibility"]
    )

    with tab_overview:
        st.subheader("Run overview")
        c1, c2, c3 = st.columns(3)
        c1.metric("Symbols", len(summary.get("symbols") or []))
        c2.metric("Strategies", len(summary.get("strategies") or []))
        n_pass = sum(1 for r in summary.get("leaderboard") or [] if r.get("status") == "PASS")
        c3.metric("PASS count", n_pass)
        st.write("Symbols:", ", ".join(summary.get("symbols") or []))
        for w in summary.get("warnings") or []:
            st.warning(w)
        report_path = artifact_dir / "report.md"
        if report_path.exists():
            with st.expander("Markdown report"):
                st.markdown(report_path.read_text(encoding="utf-8"))

    with tab_board:
        st.subheader("Validation leaderboard")
        rows = summary.get("leaderboard") or []
        if not rows:
            st.info("No candidates evaluated.")
        else:
            table = []
            for r in rows:
                mt = r.get("metrics_test") or {}
                mv = r.get("metrics_val") or {}
                fm = r.get("full_sample_metrics") or {}
                table.append(
                    {
                        "strategy": r.get("strategy_id"),
                        "symbol": r.get("symbol"),
                        "status": r.get("status"),
                        "eligible": r.get("eligible_for_ranking"),
                        "val_sharpe": mv.get("sharpe"),
                        "test_total_return": mt.get("total_return"),
                        "test_max_dd": mt.get("max_drawdown"),
                        "full_cagr": fm.get("cagr"),
                        "actual_mean_monthly": fm.get("actual_mean_monthly_return"),
                        "monthly_from_cagr": fm.get("monthly_compounded_equivalent"),
                        "n_trades_full": fm.get("n_trades"),
                    }
                )
            st.dataframe(pd.DataFrame(table), use_container_width=True)
            st.caption(
                "actual_mean_monthly = observed calendar-month returns; "
                "monthly_from_cagr = (1+CAGR)^(1/12)-1 (not observed)."
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
            stem = f"{r['strategy_id']}_{r['symbol']}"
            st.json({"status": r["status"], "reasons": r.get("reasons")})
            eq_path = artifact_dir / f"equity_{stem}.csv"
            if eq_path.exists():
                eq = pd.read_csv(eq_path, parse_dates=["Date"], index_col="Date")
                st.line_chart(eq["equity"], height=280)
                if "equity" in eq.columns:
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
            st.error("No provenance recorded for this run.")
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
        st.write(
            "MVP rejects orders that would require more cash than available or fall below "
            f"minimum notional. Starting equity for this run: "
            f"**${summary.get('starting_equity', 200)}**."
        )
        st.write(
            "Futures margin / crypto perpetual funding are **not** modeled yet (P2). "
            "Only long/flat ETF and BTC-USD spot baselines are ranked."
        )
        # Show rejection samples if any result files include them
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

        st.download_button(
            "Download summary.json",
            data=json.dumps(summary, indent=2, default=str),
            file_name=f"{run_id}_summary.json",
            mime="application/json",
        )


if __name__ == "__main__":
    main()
