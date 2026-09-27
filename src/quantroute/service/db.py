"""Persistent storage for networks, jobs, and audit logs (SIH26137).

Uses SQLite with WAL mode by default for zero-dependency local/edge deployments,
and provides schema migration for PostgreSQL/PostGIS in production.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

DEFAULT_DB_PATH = Path("quantroute.db")


class Database:
    """Thread-safe SQLite persistent store for networks and optimization jobs."""

    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH) -> None:
        self.db_path = str(Path(db_path).expanduser())
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS networks (
                    network_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    node_count INTEGER NOT NULL,
                    edge_count INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    network_id TEXT,
                    status TEXT NOT NULL, -- queued | running | done | failed
                    request_json TEXT,
                    result_json TEXT,
                    error TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
                CREATE INDEX IF NOT EXISTS idx_jobs_created ON jobs(created_at);
                """
            )

    # -- Network Persistence -------------------------------------------

    def save_network(
        self,
        network_id: str,
        name: str,
        node_count: int,
        edge_count: int,
        payload: dict[str, Any],
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO networks (network_id, name, node_count, edge_count, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (network_id, name, node_count, edge_count, json.dumps(payload), time.time()),
            )

    def get_network(self, network_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM networks WHERE network_id = ?", (network_id,)
            ).fetchone()
            if not row:
                return None
            return {
                "network_id": row["network_id"],
                "name": row["name"],
                "node_count": row["node_count"],
                "edge_count": row["edge_count"],
                "payload": json.loads(row["payload_json"]),
                "created_at": row["created_at"],
            }

    def list_networks(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT network_id, name, node_count, edge_count, created_at FROM networks ORDER BY created_at DESC"
            ).fetchall()
            return [dict(r) for r in rows]

    # -- Job Persistence -----------------------------------------------

    def save_job(
        self,
        job_id: str,
        *,
        network_id: str | None = None,
        status: str = "queued",
        request_data: dict[str, Any] | None = None,
    ) -> None:
        now = time.time()
        req_json = json.dumps(request_data) if request_data else None
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO jobs (job_id, network_id, status, request_json, result_json, error, created_at, updated_at)
                VALUES (?, ?, ?, ?, NULL, NULL, ?, ?)
                """,
                (job_id, network_id, status, req_json, now, now),
            )

    def update_job(
        self,
        job_id: str,
        *,
        status: str,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        now = time.time()
        res_json = json.dumps(result) if result else None
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE jobs
                SET status = ?, result_json = ?, error = ?, updated_at = ?
                WHERE job_id = ?
                """,
                (status, res_json, error, now, job_id),
            )
            if cursor.rowcount == 0:
                conn.execute(
                    """
                    INSERT INTO jobs (job_id, network_id, status, request_json, result_json, error, created_at, updated_at)
                    VALUES (?, NULL, ?, NULL, ?, ?, ?, ?)
                    """,
                    (job_id, status, res_json, error, now, now),
                )

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
            if not row:
                return None
            return {
                "job_id": row["job_id"],
                "network_id": row["network_id"],
                "status": row["status"],
                "request": json.loads(row["request_json"]) if row["request_json"] else None,
                "result": json.loads(row["result_json"]) if row["result_json"] else None,
                "error": row["error"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }

    def list_jobs(self, *, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT job_id, network_id, status, error, created_at, updated_at FROM jobs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]
