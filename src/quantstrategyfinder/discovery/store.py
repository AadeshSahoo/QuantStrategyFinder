"""SQLite persistence for discovered GitHub candidates (metadata only)."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class CandidateStore:
    def __init__(self, db_path: str | Path = "data/discovery/candidates.sqlite") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS candidates (
                    repo_full_name TEXT PRIMARY KEY,
                    html_url TEXT NOT NULL,
                    description TEXT,
                    language TEXT,
                    stars INTEGER,
                    updated_at TEXT,
                    license_spdx TEXT,
                    open_source_badge TEXT,
                    default_branch TEXT,
                    commit_hash TEXT,
                    markets_json TEXT,
                    reproducibility_score REAL,
                    shortlisted INTEGER DEFAULT 0,
                    review_status TEXT DEFAULT 'pending',
                    adapter_id TEXT,
                    fidelity TEXT,
                    claimed_metrics_json TEXT,
                    author_claimed_note TEXT,
                    query_hits_json TEXT,
                    raw_json TEXT,
                    discovered_at TEXT,
                    approved_at TEXT,
                    approval_note TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS discovery_runs (
                    run_id TEXT PRIMARY KEY,
                    created_at TEXT,
                    n_discovered INTEGER,
                    n_shortlisted INTEGER,
                    n_open_source INTEGER,
                    summary_json TEXT
                )
                """
            )

    def upsert_candidate(self, row: dict[str, Any]) -> None:
        cols = [
            "repo_full_name",
            "html_url",
            "description",
            "language",
            "stars",
            "updated_at",
            "license_spdx",
            "open_source_badge",
            "default_branch",
            "commit_hash",
            "markets_json",
            "reproducibility_score",
            "shortlisted",
            "review_status",
            "adapter_id",
            "fidelity",
            "claimed_metrics_json",
            "author_claimed_note",
            "query_hits_json",
            "raw_json",
            "discovered_at",
            "approved_at",
            "approval_note",
        ]
        payload = {c: row.get(c) for c in cols}
        payload.setdefault("discovered_at", _utc_now())
        placeholders = ", ".join("?" for _ in cols)
        updates = ", ".join(f"{c}=excluded.{c}" for c in cols if c != "repo_full_name")
        with self._connect() as conn:
            conn.execute(
                f"""
                INSERT INTO candidates ({', '.join(cols)}) VALUES ({placeholders})
                ON CONFLICT(repo_full_name) DO UPDATE SET {updates}
                """,
                [payload[c] for c in cols],
            )

    def list_candidates(
        self,
        *,
        shortlisted_only: bool = False,
        status: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        q = "SELECT * FROM candidates WHERE 1=1"
        args: list[Any] = []
        if shortlisted_only:
            q += " AND shortlisted=1"
        if status:
            q += " AND review_status=?"
            args.append(status)
        q += " ORDER BY reproducibility_score DESC, stars DESC"
        with self._connect() as conn:
            rows = conn.execute(q, args).fetchall()
        return [dict(r) for r in rows]

    def get(self, repo_full_name: str) -> Optional[dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM candidates WHERE repo_full_name=?", (repo_full_name,)
            ).fetchone()
        return dict(row) if row else None

    def set_review(
        self,
        repo_full_name: str,
        *,
        status: str,
        adapter_id: Optional[str] = None,
        fidelity: Optional[str] = None,
        note: str = "",
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE candidates
                SET review_status=?, adapter_id=COALESCE(?, adapter_id),
                    fidelity=COALESCE(?, fidelity),
                    approved_at=?, approval_note=?
                WHERE repo_full_name=?
                """,
                (
                    status,
                    adapter_id,
                    fidelity,
                    _utc_now() if status == "approved" else None,
                    note,
                    repo_full_name,
                ),
            )

    def mark_shortlisted(self, names: list[str]) -> None:
        with self._connect() as conn:
            conn.execute("UPDATE candidates SET shortlisted=0")
            for name in names:
                conn.execute(
                    "UPDATE candidates SET shortlisted=1 WHERE repo_full_name=?", (name,)
                )

    def save_discovery_run(self, run_id: str, summary: dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO discovery_runs(run_id, created_at, n_discovered,
                  n_shortlisted, n_open_source, summary_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    _utc_now(),
                    int(summary.get("n_discovered", 0)),
                    int(summary.get("n_shortlisted", 0)),
                    int(summary.get("n_open_source", 0)),
                    json.dumps(summary, default=str),
                ),
            )

    def counts(self) -> dict[str, int]:
        with self._connect() as conn:
            total = conn.execute("SELECT COUNT(*) FROM candidates").fetchone()[0]
            short = conn.execute(
                "SELECT COUNT(*) FROM candidates WHERE shortlisted=1"
            ).fetchone()[0]
            approved = conn.execute(
                "SELECT COUNT(*) FROM candidates WHERE review_status='approved'"
            ).fetchone()[0]
            open_src = conn.execute(
                "SELECT COUNT(*) FROM candidates WHERE open_source_badge='OPEN SOURCE'"
            ).fetchone()[0]
        return {
            "discovered": int(total),
            "shortlisted": int(short),
            "approved": int(approved),
            "open_source": int(open_src),
        }
