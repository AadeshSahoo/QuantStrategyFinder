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
def discover_cmd() -> None:
    """P1 placeholder — GitHub discovery not in MVP."""
    raise click.ClickException(
        "GitHub discovery is P1 and not implemented. MVP uses first-party baselines only."
    )


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
