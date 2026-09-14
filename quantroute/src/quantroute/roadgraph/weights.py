"""Dynamic edge weights — the "dynamic weight update mechanism" of PDF Deliverable 1 and
system-design.html §8.2.

A :class:`WeightEpoch` is an immutable snapshot of every edge's travel time, tagged with an
id and a timestamp. :class:`WeightModel` produces new epochs from live/simulated data:

  * blend, don't overwrite — ``new = (1-a)*current + a*observed`` (EWMA), then floored at
    the free-flow time so an edge never goes *faster* than physically possible;
  * gap fill — edges with no observation optionally take a class-wide congestion factor;
  * atomic — a run pins one epoch start to finish, so results are reproducible.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np

from quantroute.roadgraph.graph import RoadGraph


@dataclass(frozen=True, slots=True)
class WeightEpoch:
    """An immutable per-edge travel-time snapshot (seconds)."""

    epoch_id: int
    created_at: float  # unix timestamp
    travel_time_s: np.ndarray  # read-only, one value per graph edge
    source: str

    def age_s(self, now: float | None = None) -> float:
        return (time.time() if now is None else now) - self.created_at

    def is_stale(self, max_age_s: float, now: float | None = None) -> bool:
        return self.age_s(now) > max_age_s


class WeightModel:
    """Holds the current per-edge travel times and turns observations into new epochs."""

    __slots__ = ("_graph", "_free_flow", "_current", "_epoch_id", "_smoothing")

    def __init__(self, graph: RoadGraph, *, smoothing: float = 0.3) -> None:
        if not 0.0 < smoothing <= 1.0:
            raise ValueError("smoothing must be in (0, 1]")
        self._graph = graph
        self._free_flow = np.array(graph.edge_free_flow_s, dtype=np.float64, copy=True)
        self._current = self._free_flow.copy()
        self._epoch_id = 0
        self._smoothing = smoothing

    def free_flow_epoch(self) -> WeightEpoch:
        """Epoch 0 — every edge at its free-flow time."""
        return self._epoch(self._free_flow, epoch_id=0, source="free_flow")

    @property
    def current_epoch(self) -> WeightEpoch:
        return self._epoch(self._current, epoch_id=self._epoch_id, source="current")

    def update(
        self,
        *,
        edge_speeds_kph: Mapping[int, float] | None = None,
        edge_times_s: Mapping[int, float] | None = None,
        congestion_factor: Mapping[int, float] | None = None,
        unobserved_factor: float | None = None,
        source: str = "probes",
    ) -> WeightEpoch:
        """Fold observations into the current weights and return a new epoch.

        Provide observations any of three ways (all keyed by edge id):
        measured speeds, measured times, or a multiplier on free-flow. ``unobserved_factor``
        applies a blanket multiplier to every edge that got no observation.
        """
        e = self._graph.num_edges
        observed = np.full(e, np.nan, dtype=np.float64)

        if edge_times_s:
            for raw_eid, t in edge_times_s.items():
                eid = _check_eid(raw_eid, e)
                if not np.isfinite(t) or t <= 0:
                    raise ValueError(f"edge {eid}: travel time must be finite and > 0")
                observed[eid] = t
        if edge_speeds_kph:
            lengths = self._graph.edge_len_m
            for raw_eid, kph in edge_speeds_kph.items():
                eid = _check_eid(raw_eid, e)
                if not np.isfinite(kph) or kph <= 0:
                    raise ValueError(f"edge {eid}: speed must be finite and > 0")
                observed[eid] = lengths[eid] / (kph / 3.6)
        if congestion_factor:
            for raw_eid, factor in congestion_factor.items():
                eid = _check_eid(raw_eid, e)
                if not np.isfinite(factor) or factor <= 0:
                    raise ValueError(f"edge {eid}: congestion factor must be finite and > 0")
                observed[eid] = self._free_flow[eid] * factor

        have = ~np.isnan(observed)
        a = self._smoothing
        new = self._current.copy()
        new[have] = (1.0 - a) * self._current[have] + a * observed[have]

        if unobserved_factor is not None:
            if not np.isfinite(unobserved_factor) or unobserved_factor <= 0:
                raise ValueError("unobserved_factor must be finite and > 0")
            new[~have] = self._free_flow[~have] * unobserved_factor

        np.maximum(new, self._free_flow, out=new)  # never faster than free-flow

        self._current = new
        self._epoch_id += 1
        return self._epoch(new, epoch_id=self._epoch_id, source=source)

    # -- internals ----------------------------------------------

    def _epoch(self, values: np.ndarray, *, epoch_id: int, source: str) -> WeightEpoch:
        arr = np.array(values, dtype=np.float64, copy=True)
        arr.setflags(write=False)
        return WeightEpoch(
            epoch_id=epoch_id, created_at=time.time(), travel_time_s=arr, source=source
        )


def _check_eid(eid, num_edges: int) -> int:
    try:
        eid = int(eid)
    except (TypeError, ValueError):
        raise ValueError(f"edge id {eid!r} is not an integer") from None
    if not 0 <= eid < num_edges:
        raise ValueError(f"edge id {eid} out of range [0, {num_edges})")
    return eid
