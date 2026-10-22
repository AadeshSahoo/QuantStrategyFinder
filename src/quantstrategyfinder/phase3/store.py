"""SQLite persistence — authoritative paper-trading ledger."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class PaperStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS registration (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    registered_at TEXT NOT NULL,
                    config_hash TEXT NOT NULL,
                    config_json TEXT NOT NULL,
                    code_version TEXT,
                    forward_start_date TEXT NOT NULL,
                    n_candidates INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS candidates (
                    candidate_id TEXT PRIMARY KEY,
                    strategy_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    asset_class TEXT NOT NULL,
                    benchmark_symbol TEXT NOT NULL,
                    params_json TEXT NOT NULL,
                    limitations TEXT,
                    starting_equity REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS accounts (
                    candidate_id TEXT PRIMARY KEY REFERENCES candidates(candidate_id),
                    cash REAL NOT NULL,
                    position_qty REAL NOT NULL DEFAULT 0,
                    avg_entry REAL NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    candidate_id TEXT NOT NULL,
                    signal_date TEXT NOT NULL,
                    asof_bar TEXT NOT NULL,
                    target_weight REAL NOT NULL,
                    UNIQUE(candidate_id, signal_date)
                );

                CREATE TABLE IF NOT EXISTS orders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    candidate_id TEXT NOT NULL,
                    order_key TEXT NOT NULL UNIQUE,
                    signal_date TEXT NOT NULL,
                    exec_date TEXT NOT NULL,
                    side TEXT NOT NULL,
                    target_weight REAL NOT NULL,
                    status TEXT NOT NULL,
                    reason TEXT
                );

                CREATE TABLE IF NOT EXISTS fills (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_key TEXT NOT NULL UNIQUE,
                    candidate_id TEXT NOT NULL,
                    exec_date TEXT NOT NULL,
                    side TEXT NOT NULL,
                    qty REAL NOT NULL,
                    mid_price REAL NOT NULL,
                    fill_price REAL NOT NULL,
                    notional REAL NOT NULL,
                    commission REAL NOT NULL,
                    spread_slippage_cost REAL NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS equity_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    candidate_id TEXT NOT NULL,
                    asof_date TEXT NOT NULL,
                    cash REAL NOT NULL,
                    position_qty REAL NOT NULL,
                    mark_price REAL NOT NULL,
                    equity REAL NOT NULL,
                    UNIQUE(candidate_id, asof_date)
                );

                CREATE TABLE IF NOT EXISTS job_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    status TEXT NOT NULL,
                    detail_json TEXT
                );
                """
            )

    def is_registered(self) -> bool:
        with self._connect() as conn:
            row = conn.execute("SELECT 1 FROM registration WHERE id=1").fetchone()
        return row is not None

    def register(self, cfg: dict[str, Any], *, config_text: str, code_version: str) -> str:
        if self.is_registered():
            with self._connect() as conn:
                row = conn.execute("SELECT config_hash FROM registration WHERE id=1").fetchone()
            return row["config_hash"]
        config_hash = hashlib.sha256(config_text.encode("utf-8")).hexdigest()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO registration(id, registered_at, config_hash, config_json, "
                "code_version, forward_start_date, n_candidates) VALUES (1,?,?,?,?,?,?)",
                (
                    _utc_now(),
                    config_hash,
                    json.dumps(cfg, default=str),
                    code_version,
                    cfg["forward_start_date"],
                    int(cfg["n_candidates_registered"]),
                ),
            )
            for c in cfg["candidates"]:
                conn.execute(
                    "INSERT INTO candidates(candidate_id, strategy_id, symbol, asset_class, "
                    "benchmark_symbol, params_json, limitations, starting_equity) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (
                        c["candidate_id"],
                        c["strategy_id"],
                        c["symbol"],
                        c["asset_class"],
                        c["benchmark_symbol"],
                        json.dumps(c.get("params") or {}),
                        c.get("phase2_limitations"),
                        float(cfg["starting_equity_per_strategy"]),
                    ),
                )
                conn.execute(
                    "INSERT INTO accounts(candidate_id, cash, position_qty, avg_entry, updated_at) "
                    "VALUES (?,?,0,0,?)",
                    (c["candidate_id"], float(cfg["starting_equity_per_strategy"]), _utc_now()),
                )
        return config_hash

    def list_candidates(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM candidates ORDER BY candidate_id").fetchall()
        return [dict(r) for r in rows]

    def get_account(self, candidate_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM accounts WHERE candidate_id=?", (candidate_id,)
            ).fetchone()
        if not row:
            raise KeyError(candidate_id)
        return dict(row)

    def update_account(
        self, candidate_id: str, *, cash: float, position_qty: float, avg_entry: float
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE accounts SET cash=?, position_qty=?, avg_entry=?, updated_at=? "
                "WHERE candidate_id=?",
                (cash, position_qty, avg_entry, _utc_now(), candidate_id),
            )

    def insert_signal(
        self, candidate_id: str, signal_date: str, asof_bar: str, target_weight: float
    ) -> bool:
        """Return True if inserted, False if duplicate."""
        with self._connect() as conn:
            try:
                conn.execute(
                    "INSERT INTO signals(candidate_id, signal_date, asof_bar, target_weight) "
                    "VALUES (?,?,?,?)",
                    (candidate_id, signal_date, asof_bar, float(target_weight)),
                )
                return True
            except sqlite3.IntegrityError:
                return False

    def order_exists(self, order_key: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM orders WHERE order_key=?", (order_key,)
            ).fetchone()
        return row is not None

    def insert_order(self, **fields: Any) -> bool:
        with self._connect() as conn:
            try:
                conn.execute(
                    "INSERT INTO orders(candidate_id, order_key, signal_date, exec_date, side, "
                    "target_weight, status, reason) VALUES (?,?,?,?,?,?,?,?)",
                    (
                        fields["candidate_id"],
                        fields["order_key"],
                        fields["signal_date"],
                        fields["exec_date"],
                        fields["side"],
                        fields["target_weight"],
                        fields["status"],
                        fields.get("reason"),
                    ),
                )
                return True
            except sqlite3.IntegrityError:
                return False

    def insert_fill(self, **fields: Any) -> bool:
        with self._connect() as conn:
            try:
                conn.execute(
                    "INSERT INTO fills(order_key, candidate_id, exec_date, side, qty, mid_price, "
                    "fill_price, notional, commission, spread_slippage_cost, created_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        fields["order_key"],
                        fields["candidate_id"],
                        fields["exec_date"],
                        fields["side"],
                        fields["qty"],
                        fields["mid_price"],
                        fields["fill_price"],
                        fields["notional"],
                        fields["commission"],
                        fields["spread_slippage_cost"],
                        _utc_now(),
                    ),
                )
                return True
            except sqlite3.IntegrityError:
                return False

    def upsert_equity(
        self,
        candidate_id: str,
        asof_date: str,
        *,
        cash: float,
        position_qty: float,
        mark_price: float,
        equity: float,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO equity_snapshots(candidate_id, asof_date, cash, position_qty, "
                "mark_price, equity) VALUES (?,?,?,?,?,?) "
                "ON CONFLICT(candidate_id, asof_date) DO UPDATE SET "
                "cash=excluded.cash, position_qty=excluded.position_qty, "
                "mark_price=excluded.mark_price, equity=excluded.equity",
                (candidate_id, asof_date, cash, position_qty, mark_price, equity),
            )

    def start_job(self) -> int:
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO job_runs(started_at, status, detail_json) VALUES (?,?,?)",
                (_utc_now(), "running", "{}"),
            )
            return int(cur.lastrowid)

    def finish_job(self, job_id: int, status: str, detail: dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE job_runs SET finished_at=?, status=?, detail_json=? WHERE id=?",
                (_utc_now(), status, json.dumps(detail, default=str), job_id),
            )

    def export_fills(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM fills ORDER BY exec_date, candidate_id"
            ).fetchall()
        return [dict(r) for r in rows]

    def export_equity(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM equity_snapshots ORDER BY asof_date, candidate_id"
            ).fetchall()
        return [dict(r) for r in rows]

    def export_orders(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM orders ORDER BY exec_date, candidate_id").fetchall()
        return [dict(r) for r in rows]

    def registration_meta(self) -> Optional[dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM registration WHERE id=1").fetchone()
        return dict(row) if row else None

    def latest_job(self) -> Optional[dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM job_runs ORDER BY id DESC LIMIT 1"
            ).fetchone()
        return dict(row) if row else None
