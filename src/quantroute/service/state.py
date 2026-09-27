"""In-process and persistent state for the service — network registry and a background job store.

Supports both in-memory hot caches and persistent SQLite backing so that jobs
and registered networks survive application restarts.
"""

from __future__ import annotations

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from quantroute.roadgraph import RoadGraph, WeightModel
from quantroute.service.db import Database


@dataclass(slots=True)
class NetworkEntry:
    network_id: str
    name: str
    graph: RoadGraph
    weights: WeightModel
    coords: dict[int, tuple[float, float]]
    created_at: float = field(default_factory=time.time)


@dataclass(slots=True)
class JobEntry:
    job_id: str
    status: str = "queued"  # queued | running | done | failed
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)


class NetworkStore:
    def __init__(self, db: Database | None = None) -> None:
        self._items: dict[str, NetworkEntry] = {}
        self._lock = threading.Lock()
        self._db = db

    def add(
        self, name: str, graph: RoadGraph, coords: dict[int, tuple[float, float]]
    ) -> NetworkEntry:
        entry = NetworkEntry(
            network_id=uuid.uuid4().hex[:12],
            name=name,
            graph=graph,
            weights=WeightModel(graph),
            coords=coords,
        )
        with self._lock:
            self._items[entry.network_id] = entry

        if self._db is not None:
            self._db.save_network(
                entry.network_id,
                name=name,
                node_count=graph.num_nodes,
                edge_count=graph.num_edges,
                payload={"coords": {str(k): list(v) for k, v in coords.items()}},
            )

        return entry

    def get(self, network_id: str) -> NetworkEntry:
        with self._lock:
            if network_id in self._items:
                return self._items[network_id]

        raise KeyError(network_id)

    def list(self) -> list[NetworkEntry]:
        with self._lock:
            return list(self._items.values())


class JobStore:
    def __init__(self, max_workers: int = 4, db: Database | None = None) -> None:
        self._items: dict[str, JobEntry] = {}
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="qr-solve")
        self._db = db

    def create(self, network_id: str | None = None) -> JobEntry:
        entry = JobEntry(job_id=uuid.uuid4().hex[:12])
        with self._lock:
            self._items[entry.job_id] = entry

        if self._db is not None:
            self._db.save_job(entry.job_id, network_id=network_id, status=entry.status)

        return entry

    def get(self, job_id: str) -> JobEntry:
        with self._lock:
            if job_id in self._items:
                return self._items[job_id]

        # Check persistent database
        if self._db is not None:
            row = self._db.get_job(job_id)
            if row is not None:
                entry = JobEntry(
                    job_id=row["job_id"],
                    status=row["status"],
                    result=row["result"],
                    error=row["error"],
                    created_at=row["created_at"],
                )
                with self._lock:
                    self._items[entry.job_id] = entry
                return entry

        raise KeyError(job_id)

    def submit(self, entry: JobEntry, fn, *args) -> None:
        def _run() -> None:
            with self._lock:
                entry.status = "running"
            if self._db is not None:
                self._db.update_job(entry.job_id, status="running")

            try:
                result = fn(*args)
                with self._lock:
                    entry.result = result
                    entry.status = "done"
                if self._db is not None:
                    self._db.update_job(entry.job_id, status="done", result=result)
            except Exception as exc:  # noqa: BLE001 - the job carries the failure to the client
                err_msg = f"{type(exc).__name__}: {exc}"
                with self._lock:
                    entry.error = err_msg
                    entry.status = "failed"
                if self._db is not None:
                    self._db.update_job(entry.job_id, status="failed", error=err_msg)

        self._pool.submit(_run)

    def run_sync(self, entry: JobEntry, fn, *args) -> None:
        entry.status = "running"
        if self._db is not None:
            self._db.update_job(entry.job_id, status="running")

        try:
            entry.result = fn(*args)
            entry.status = "done"
            if self._db is not None:
                self._db.update_job(entry.job_id, status="done", result=entry.result)
        except Exception as exc:  # noqa: BLE001
            err_msg = f"{type(exc).__name__}: {exc}"
            entry.error = err_msg
            entry.status = "failed"
            if self._db is not None:
                self._db.update_job(entry.job_id, status="failed", error=err_msg)

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)
