"""In-process state for the service — network registry and a background job store.

This deliberately avoids Kafka / Redis / a database: the design doc's §8 infrastructure is
the *production-scale* story; for a single-node demonstration a dict plus a thread pool is
correct and keeps the platform to one ``pip install``.
"""

from __future__ import annotations

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from quantroute.roadgraph import RoadGraph, WeightModel


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
    def __init__(self) -> None:
        self._items: dict[str, NetworkEntry] = {}
        self._lock = threading.Lock()

    def add(self, name: str, graph: RoadGraph, coords: dict[int, tuple[float, float]]) -> NetworkEntry:
        entry = NetworkEntry(
            network_id=uuid.uuid4().hex[:12],
            name=name,
            graph=graph,
            weights=WeightModel(graph),
            coords=coords,
        )
        with self._lock:
            self._items[entry.network_id] = entry
        return entry

    def get(self, network_id: str) -> NetworkEntry:
        with self._lock:
            if network_id not in self._items:
                raise KeyError(network_id)
            return self._items[network_id]

    def list(self) -> list[NetworkEntry]:
        with self._lock:
            return list(self._items.values())


class JobStore:
    def __init__(self, max_workers: int = 4) -> None:
        self._items: dict[str, JobEntry] = {}
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="qr-solve")

    def create(self) -> JobEntry:
        entry = JobEntry(job_id=uuid.uuid4().hex[:12])
        with self._lock:
            self._items[entry.job_id] = entry
        return entry

    def get(self, job_id: str) -> JobEntry:
        with self._lock:
            if job_id not in self._items:
                raise KeyError(job_id)
            return self._items[job_id]

    def submit(self, entry: JobEntry, fn, *args) -> None:
        def _run() -> None:
            with self._lock:
                entry.status = "running"
            try:
                result = fn(*args)
                with self._lock:
                    entry.result = result
                    entry.status = "done"
            except Exception as exc:  # noqa: BLE001 - the job carries the failure to the client
                with self._lock:
                    entry.error = f"{type(exc).__name__}: {exc}"
                    entry.status = "failed"

        self._pool.submit(_run)

    def run_sync(self, entry: JobEntry, fn, *args) -> None:
        entry.status = "running"
        try:
            entry.result = fn(*args)
            entry.status = "done"
        except Exception as exc:  # noqa: BLE001
            entry.error = f"{type(exc).__name__}: {exc}"
            entry.status = "failed"

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)
