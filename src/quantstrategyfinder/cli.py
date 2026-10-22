"""Command-line interface for QuantStrategyFinder."""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from pathlib import Path

import click

from quantstrategyfinder import __version__


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@click.group()
@click.version_option(__version__, prog_name="qsf")
@click.option("--verbose", is_flag=True, help="Debug logging")
@click.pass_context
def main(ctx: click.Context, verbose: bool) -> None:
    """QuantStrategyFinder — research-only backtesting and validation."""
    _setup_logging(verbose)
    ctx.ensure_object(dict)


@main.command("fetch-data")
@click.option("--config", "config_path", default="configs/default.yaml", show_default=True)
@click.option("--symbol", multiple=True, help="Override universe (repeatable)")
@click.option("--force-refresh", is_flag=True, help="Ignore cache")
def fetch_data(config_path: str, symbol: tuple[str, ...], force_refresh: bool) -> None:
    """Download real daily OHLCV with provenance."""
    from quantstrategyfinder.data.sources import fetch_universe
    from quantstrategyfinder.pipeline import load_config

    cfg = load_config(config_path)
    symbols = list(symbol) if symbol else list(cfg["universe"])
    data_cfg = cfg.get("data") or {}
    results = fetch_universe(
        symbols,
        lookback_years=int(data_cfg.get("lookback_years", 10)),
        adjusted=bool(data_cfg.get("adjusted", True)),
        cache_dir=data_cfg.get("cache_dir", "data/cache"),
        force_refresh=force_refresh,
    )
    for sym, (bars, prov) in results.items():
        click.echo(
            f"{sym}: {prov.n_bars} bars {prov.start}→{prov.end} "
            f"source={prov.source} hash={prov.content_hash[:12]}…"
        )
        if prov.warnings:
            for w in prov.warnings:
                click.echo(f"  warning: {w}")


@main.command("backtest")
@click.option("--config", "config_path", default="configs/default.yaml", show_default=True)
@click.option("--symbol", multiple=True)
@click.option("--strategy", "strategy_ids", multiple=True)
@click.option("--force-refresh", is_flag=True)
@click.option("--cost-stress", default=1.0, show_default=True, type=float)
@click.option("--reports-dir", default="reports", show_default=True)
def backtest_cmd(
    config_path: str,
    symbol: tuple[str, ...],
    strategy_ids: tuple[str, ...],
    force_refresh: bool,
    cost_stress: float,
    reports_dir: str,
) -> None:
    """Run baseline backtests with chronological validation."""
    from quantstrategyfinder.pipeline import run_mvp_pipeline

    summary = run_mvp_pipeline(
        config_path=config_path,
        symbols=list(symbol) if symbol else None,
        strategy_ids=list(strategy_ids) if strategy_ids else None,
        force_refresh=force_refresh,
        reports_dir=reports_dir,
        cost_stress=cost_stress,
    )
    click.echo(f"run_id={summary['run_id']}")
    click.echo(f"artifacts={summary['artifact_dir']}")
    if summary.get("message"):
        click.echo(summary["message"])
    for row in summary.get("leaderboard") or []:
        click.echo(
            f"  {row['strategy_id']:12} {row['symbol']:8} {row['status']:12} "
            f"eligible={row['eligible_for_ranking']}"
        )


@main.command("validate")
@click.argument("run_id")
@click.option("--reports-dir", default="reports", show_default=True)
def validate_cmd(run_id: str, reports_dir: str) -> None:
    """Print validation summary for an existing run."""
    from quantstrategyfinder.persistence.repository import RunRepository

    repo = RunRepository(reports_dir)
    summary = repo.load_summary(run_id)
    click.echo(json.dumps({
        "run_id": summary.get("run_id"),
        "any_passed": summary.get("any_passed"),
        "message": summary.get("message"),
        "leaderboard": [
            {
                "strategy_id": r["strategy_id"],
                "symbol": r["symbol"],
                "status": r["status"],
                "reasons": r.get("reasons"),
            }
            for r in summary.get("leaderboard") or []
        ],
    }, indent=2))


@main.command("report")
@click.argument("run_id")
@click.option("--reports-dir", default="reports", show_default=True)
def report_cmd(run_id: str, reports_dir: str) -> None:
    """Show path to Markdown report for a run."""
    path = Path(reports_dir) / run_id / "report.md"
    if not path.exists():
        raise click.ClickException(f"Report not found: {path}")
    click.echo(path.read_text(encoding="utf-8"))


@main.command("dashboard")
@click.option("--reports-dir", default="reports", show_default=True)
@click.option("--port", default=8507, show_default=True, type=int)
@click.option("--host", default="0.0.0.0", show_default=True)
def dashboard_cmd(reports_dir: str, port: int, host: str) -> None:
    """Launch Streamlit dashboard on real run artifacts."""
    app = Path(__file__).resolve().parent / "dashboard" / "app.py"
    env_reports = str(Path(reports_dir).resolve())
    cmd = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(app),
        "--server.port",
        str(port),
        "--server.address",
        host,
        "--server.headless",
        "true",
        "--browser.gatherUsageStats",
        "false",
        "--",
        "--reports-dir",
        env_reports,
    ]
    import os

    env = os.environ.copy()
    env.setdefault("STREAMLIT_BROWSER_GATHER_USAGE_STATS", "false")
    click.echo(f"Starting dashboard: {' '.join(cmd)}")
    raise SystemExit(subprocess.call(cmd, env=env))


@main.command("discover")
@click.option("--config", "config_path", default="configs/discovery.yaml", show_default=True)
@click.option("--store", "store_path", default="data/discovery/candidates.sqlite", show_default=True)
@click.option("--no-commits", is_flag=True, help="Skip per-repo commit SHA fetch (faster)")
@click.option("--no-wait", is_flag=True, help="Fail instead of sleeping on rate limit")
def discover_cmd(config_path: str, store_path: str, no_commits: bool, no_wait: bool) -> None:
    """Search GitHub for strategy repos (metadata only — never executes upstream code)."""
    from quantstrategyfinder.discovery.github import discover_repositories

    summary = discover_repositories(
        config_path=config_path,
        store_path=store_path,
        fetch_commits=not no_commits,
        wait_on_rate_limit=not no_wait,
    )
    click.echo(json.dumps(summary, indent=2))


@main.group("review")
def review_group() -> None:
    """Candidate review queue (approve first-party adapters only)."""


@review_group.command("list")
@click.option("--store", "store_path", default="data/discovery/candidates.sqlite", show_default=True)
@click.option("--all", "show_all", is_flag=True, help="Include non-shortlisted")
def review_list(store_path: str, show_all: bool) -> None:
    from quantstrategyfinder.discovery.review import review_queue
    from quantstrategyfinder.discovery.store import CandidateStore

    rows = review_queue(CandidateStore(store_path), shortlisted_only=not show_all)
    for r in rows:
        click.echo(
            f"{r['review_status']:10} score={r['reproducibility_score']!s:>6} "
            f"stars={r['stars']:<6} {r['open_source_badge']:<28} "
            f"adapter={r.get('adapter_id') or '-':16} {r['repo_full_name']}"
        )
    click.echo(f"count={len(rows)}")


@review_group.command("approve")
@click.argument("repo_full_name")
@click.option("--adapter", "adapter_id", required=True, help="First-party adapter id")
@click.option("--fidelity", default="REIMPLEMENTATION", show_default=True,
              type=click.Choice(["REIMPLEMENTATION", "REPRODUCED ORIGINAL"]))
@click.option("--note", default="")
@click.option("--store", "store_path", default="data/discovery/candidates.sqlite", show_default=True)
def review_approve(
    repo_full_name: str, adapter_id: str, fidelity: str, note: str, store_path: str
) -> None:
    from quantstrategyfinder.discovery.review import approve_candidate
    from quantstrategyfinder.discovery.store import CandidateStore

    row = approve_candidate(
        repo_full_name,
        adapter_id=adapter_id,
        fidelity=fidelity,
        note=note,
        store=CandidateStore(store_path),
    )
    click.echo(json.dumps({k: row.get(k) for k in (
        "repo_full_name", "review_status", "adapter_id", "fidelity", "approval_note"
    )}, indent=2))


@review_group.command("approve-mapped")
@click.option("--store", "store_path", default="data/discovery/candidates.sqlite", show_default=True)
def review_approve_mapped(store_path: str) -> None:
    """Approve shortlisted OPEN SOURCE candidates that already have adapter mappings."""
    from quantstrategyfinder.discovery.review import approve_shortlist_mapped
    from quantstrategyfinder.discovery.store import CandidateStore

    rows = approve_shortlist_mapped(store=CandidateStore(store_path))
    click.echo(f"approved={len(rows)}")
    for r in rows:
        click.echo(f"  {r['repo_full_name']} -> {r['adapter_id']} ({r['fidelity']})")


@main.command("evaluate-discovered")
@click.option("--config", "config_path", default="configs/default.yaml", show_default=True)
@click.option("--store", "store_path", default="data/discovery/candidates.sqlite", show_default=True)
@click.option("--reports-dir", default="reports", show_default=True)
@click.option("--auto-approve-mapped", is_flag=True,
              help="Approve shortlisted mapped OPEN SOURCE adapters before eval")
def evaluate_discovered_cmd(
    config_path: str, store_path: str, reports_dir: str, auto_approve_mapped: bool
) -> None:
    """Backtest approved first-party adapters (never executes upstream repos)."""
    from quantstrategyfinder.discovery.evaluate import evaluate_approved_adapters

    summary = evaluate_approved_adapters(
        config_path=config_path,
        store_path=store_path,
        reports_dir=reports_dir,
        auto_approve_mapped=auto_approve_mapped,
    )
    click.echo(f"run_id={summary['run_id']}")
    click.echo(json.dumps(summary.get("counts"), indent=2))
    if summary.get("message"):
        click.echo(summary["message"])
    for row in summary.get("eligible_ranked") or []:
        click.echo(
            f"  rank={row.get('rank')} {row['strategy_id']:16} {row['symbol']:8} "
            f"{row['status']} fidelity={row['attribution'].get('fidelity')}"
        )


@main.command("audit-p1")
@click.option("--run-id", default="20261022T011911Z_9bbd8eb2", show_default=True)
@click.option("--reports-dir", default="reports", show_default=True)
def audit_p1_cmd(run_id: str, reports_dir: str) -> None:
    """Post-hoc audit of a frozen P1 eval run (no strategy/param changes)."""
    from quantstrategyfinder.reporting.p1_audit import write_p1_audit_outputs

    out = write_p1_audit_outputs(run_id=run_id, reports_dir=reports_dir)
    click.echo(json.dumps({k: out[k] for k in (
        "run_id", "n_rows", "n_pass", "n_pass_justified", "n_credible_positive_oos",
        "message", "csv_path", "docs_csv", "docs_md",
    ) if k in out}, indent=2))
    if out.get("message"):
        click.echo(out["message"])


@main.command("test")
@click.option("--e2e", is_flag=True, help="Include real-data end-to-end tests")
def test_cmd(e2e: bool) -> None:
    """Run pytest suite."""
    args = [sys.executable, "-m", "pytest", "-q"]
    if e2e:
        args += ["-m", "e2e"]
    else:
        args += ["-m", "not e2e"]
    raise SystemExit(subprocess.call(args))


if __name__ == "__main__":
    main()
