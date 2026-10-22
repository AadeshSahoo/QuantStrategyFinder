"""Persist run artifacts to disk + SQLite index."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import pandas as pd


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_run_id() -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{ts}_{uuid.uuid4().hex[:8]}"


class RunRepository:
    def __init__(self, reports_dir: str | Path = "reports") -> None:
        self.reports_dir = Path(reports_dir)
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.reports_dir / "runs.sqlite"
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    git_commit TEXT,
                    status TEXT,
                    artifact_dir TEXT,
                    summary_json TEXT
                )
                """
            )

    def create_run(self, *, git_commit: Optional[str] = None) -> tuple[str, Path]:
        run_id = new_run_id()
        artifact_dir = self.reports_dir / run_id
        artifact_dir.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO runs(run_id, created_at, git_commit, status, artifact_dir, summary_json) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (run_id, _utc_now(), git_commit, "created", str(artifact_dir), "{}"),
            )
        return run_id, artifact_dir

    def save_json(self, artifact_dir: Path, name: str, payload: Any) -> Path:
        path = artifact_dir / name
        path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        return path

    def save_df(self, artifact_dir: Path, name: str, df: pd.DataFrame) -> Path:
        path = artifact_dir / name
        df.to_csv(path, index=True)
        return path

    def finalize(self, run_id: str, status: str, summary: dict[str, Any]) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE runs SET status=?, summary_json=? WHERE run_id=?",
                (status, json.dumps(summary, default=str), run_id),
            )

    def list_runs(self) -> list[dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT run_id, created_at, git_commit, status, artifact_dir, summary_json "
                "FROM runs ORDER BY created_at DESC"
            ).fetchall()
        out = []
        for r in rows:
            out.append(
                {
                    "run_id": r[0],
                    "created_at": r[1],
                    "git_commit": r[2],
                    "status": r[3],
                    "artifact_dir": r[4],
                    "summary": json.loads(r[5] or "{}"),
                }
            )
        return out

    def load_summary(self, run_id: str) -> dict[str, Any]:
        path = self.reports_dir / run_id / "summary.json"
        if not path.exists():
            raise FileNotFoundError(f"No summary for run {run_id}")
        return json.loads(path.read_text(encoding="utf-8"))
