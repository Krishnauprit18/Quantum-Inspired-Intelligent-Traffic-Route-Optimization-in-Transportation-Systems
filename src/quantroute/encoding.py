"""Continuous vector <-> routes: the ``Encoding`` layer from system-design.html §9.

QPSO / PSO search a real-valued space. An ``Encoding`` is the bridge between a particle's
position vector and a concrete :class:`~quantroute.routes.Routes`:

  * ``random(rng)``  — draw a fresh position;
  * ``bounds()``     — the box the optimizer clips to;
  * ``decode(keys)`` — position -> routes.

``RandomKeyGiantTour`` is the standard *route-first, split-second* scheme (Prins, 2004)
extended to a k-bounded multi-depot heterogeneous Bellman recurrence:

  1. **Giant tour** — sort the stops by their key value to get one ordering of every stop.
  2. **Split** — cut that ordering into consecutive segments, one per vehicle, by an
     optimal k-bounded Bellman recurrence that respects per-vehicle capacity, individual
     depot start/end nodes, and minimises the objective (travel time, distance, or makespan).

Supports:
  * Single-depot and Multi-depot VRP (MDVRP).
  * Homogeneous and Heterogeneous vehicle fleet capacities (HVRP).
  * Sum objectives (``MIN_TRAVEL_TIME``, ``MIN_DISTANCE``) and minimax ``MIN_MAKESPAN``.
  * Time-window aware segment evaluation during split when time windows are enabled.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import numpy as np

from quantroute.matrix import CostMatrix
from quantroute.problem import Objective, ProblemSpec
from quantroute.routes import Route, Routes

# Tolerance for "load fits capacity" so float rounding never spuriously rejects a segment
# whose demand equals capacity exactly.
_LOAD_EPS = 1e-9


@runtime_checkable
class Encoding(Protocol):
    """Maps a real position vector to routes and back to a search box."""

    @property
    def dimension(self) -> int:
        """Length of a position vector (one key per stop)."""
        ...

    def bounds(self) -> tuple[float, float]:
        """``(lo, hi)`` the optimizer clips every coordinate to."""
        ...

    def random(self, rng: np.random.Generator) -> np.ndarray:
        """A fresh, in-bounds position vector of length :attr:`dimension`."""
        ...

    def decode(self, keys: np.ndarray) -> Routes:
        """Position vector -> concrete routes (every stop visited exactly once)."""
        ...


@dataclass(frozen=True, slots=True)
class Decoded:
    """Result of a decode: the routes plus what the split knows about them."""

    routes: Routes
    cost: float
    """Cost of the produced routes under the instance objective."""
    feasible: bool
    """True iff every route is within capacity and no more than ``k`` vehicles are used."""


class RandomKeyGiantTour:
    """Random-key giant-tour encoding with a k-bounded capacity and depot-aware optimal split.

    Parameters
    ----------
    spec:
        The instance specification. Supports single/multi-depot, homogeneous/heterogeneous
        fleets, and travel time / distance / makespan objectives.
    matrix:
        Cost oracle covering every depot and stop node.
    """

    __slots__ = (
        "_n",
        "_stop_ids",
        "_stop_nodes",
        "_demand",
        "_tw_open",
        "_tw_close",
        "_service",
        "_vehicle_ids",
        "_k",
        "_veh_caps",
        "_veh_start_nodes",
        "_veh_end_nodes",
        "_veh_shift_starts",
        "_objective",
        "_enforce_tw",
        "_cost",
        "_travel_time",
    )

    def __init__(self, spec: ProblemSpec, matrix: CostMatrix) -> None:
        depots_by_id = {d.id: d for d in spec.depots}
        for v in spec.vehicles:
            if v.start_depot not in depots_by_id:
                raise ValueError(
                    f"vehicle {v.id!r} references unknown start depot {v.start_depot!r}"
                )
            if v.effective_end_depot not in depots_by_id:
                raise ValueError(
                    f"vehicle {v.id!r} references unknown end depot {v.effective_end_depot!r}"
                )

        known_nodes = set(matrix.nodes)
        need_nodes = {s.node for s in spec.stops} | {d.node for d in spec.depots}
        missing = sorted(need_nodes - known_nodes)
        if missing:
            raise ValueError(
                f"cost matrix is missing {len(missing)} node(s) from the instance: "
                f"{missing[:10]}{' ...' if len(missing) > 10 else ''}"
            )

        self._n = len(spec.stops)
        self._stop_ids: tuple[str, ...] = tuple(s.id for s in spec.stops)
        self._stop_nodes = np.array([s.node for s in spec.stops], dtype=np.int64)
        self._demand = np.array([s.demand for s in spec.stops], dtype=np.float64)
        self._tw_open = np.array([s.tw_open_s for s in spec.stops], dtype=np.float64)
        self._tw_close = np.array([s.tw_close_s for s in spec.stops], dtype=np.float64)
        self._service = np.array([s.service_s for s in spec.stops], dtype=np.float64)

        # Instance data is read-only after build
        self._stop_nodes.setflags(write=False)
        self._demand.setflags(write=False)
        self._tw_open.setflags(write=False)
        self._tw_close.setflags(write=False)
        self._service.setflags(write=False)

        self._vehicle_ids: tuple[str, ...] = tuple(v.id for v in spec.vehicles)
        self._k = len(spec.vehicles)
        self._veh_caps = np.array([float(v.capacity) for v in spec.vehicles], dtype=np.float64)
        self._veh_start_nodes = np.array(
            [depots_by_id[v.start_depot].node for v in spec.vehicles], dtype=np.int64
        )
        self._veh_end_nodes = np.array(
            [depots_by_id[v.effective_end_depot].node for v in spec.vehicles], dtype=np.int64
        )
        self._veh_shift_starts = np.array(
            [float(v.shift_start_s) for v in spec.vehicles], dtype=np.float64
        )
        self._veh_caps.setflags(write=False)
        self._veh_start_nodes.setflags(write=False)
        self._veh_end_nodes.setflags(write=False)
        self._veh_shift_starts.setflags(write=False)

        self._objective = spec.objective
        self._enforce_tw = spec.constraints.enforce_time_windows
        self._cost = (
            matrix.distance if spec.objective is Objective.MIN_DISTANCE else matrix.travel_time
        )
        self._travel_time = matrix.travel_time

    # -- Encoding protocol --------------------------------------------------

    @property
    def dimension(self) -> int:
        return self._n

    def bounds(self) -> tuple[float, float]:
        return (0.0, 1.0)

    def random(self, rng: np.random.Generator) -> np.ndarray:
        return rng.random(self._n)

    def decode(self, keys: np.ndarray) -> Routes:
        return self.decode_detailed(keys).routes

    # -- extras -----------------------------------------------------------

    def giant_tour(self, keys: np.ndarray) -> tuple[str, ...]:
        """The stop ordering implied by ``keys`` (stable on ties)."""
        order = self._order(self._validate_keys(keys))
        return tuple(self._stop_ids[int(t)] for t in order)

    def decode_detailed(self, keys: np.ndarray) -> Decoded:
        arr = self._validate_keys(keys)
        order = self._order(arr)

        assigned_routes, split_feasible = self._split(order)

        routes = tuple(
            Route(vehicle_id=vid, stop_ids=tuple(self._stop_ids[int(t)] for t in idxs))
            for vid, idxs in zip(self._vehicle_ids, assigned_routes, strict=False)
        )
        if self._objective is Objective.MIN_MAKESPAN:
            route_costs = [self._route_cost(m, idxs) for m, idxs in enumerate(assigned_routes)]
            total = max(route_costs, default=0.0)
        else:
            total = sum(self._route_cost(m, idxs) for m, idxs in enumerate(assigned_routes))

        return Decoded(
            routes=Routes(routes),
            cost=float(total),
            feasible=split_feasible,
        )

    # -- internals ------------------------------------------------------

    def _validate_keys(self, keys: np.ndarray) -> np.ndarray:
        arr = np.asarray(keys, dtype=np.float64)
        if arr.shape != (self._n,):
            raise ValueError(f"expected {self._n} keys, got shape {arr.shape}")
        if not np.isfinite(arr).all():
            raise ValueError("keys contain non-finite values (nan/inf)")
        return arr

    @staticmethod
    def _order(keys: np.ndarray) -> np.ndarray:
        return np.argsort(keys, kind="stable")

    def _split(self, order: np.ndarray) -> tuple[list[list[int]], bool]:
        """k-bounded capacity, depot, and time-window aware split of the giant tour.

        Returns ``(assigned_routes, feasible)`` where ``assigned_routes`` has length ``k``.
        """
        n, k = self._n, self._k
        if n == 0:
            return [[] for _ in range(k)], True

        is_makespan = self._objective is Objective.MIN_MAKESPAN
        cost_to = np.full((n + 1, k + 1), np.inf, dtype=np.float64)
        cost_to[0, 0] = 0.0
        pred_i = np.full((n + 1, k + 1), -1, dtype=np.int64)

        for m in range(1, k + 1):
            veh_idx = m - 1
            cap = self._veh_caps[veh_idx]
            d_start = int(self._veh_start_nodes[veh_idx])
            d_end = int(self._veh_end_nodes[veh_idx])
            shift_start = float(self._veh_shift_starts[veh_idx])

            # Idle vehicle option
            cost_to[:, m] = cost_to[:, m - 1]
            pred_i[:, m] = np.arange(n + 1)

            for i in range(n):
                c_prev = cost_to[i, m - 1]
                if not np.isfinite(c_prev):
                    continue
                load = 0.0
                curr_cost = 0.0
                t = shift_start
                prev_node = d_start
                tw_lateness = 0.0

                for j in range(i, n):
                    idx = int(order[j])
                    load += float(self._demand[idx])
                    if load > cap + _LOAD_EPS:
                        break

                    node = int(self._stop_nodes[idx])
                    curr_cost += self._cost(prev_node, node)

                    if self._enforce_tw:
                        t += self._travel_time(prev_node, node)
                        tw_open = self._tw_open[idx]
                        tw_close = self._tw_close[idx]
                        if t < tw_open:
                            t = tw_open
                        elif t > tw_close:
                            tw_lateness += t - tw_close
                        t += self._service[idx]

                    prev_node = node
                    full_route_cost = curr_cost + self._cost(prev_node, d_end)
                    score = full_route_cost + (tw_lateness * 100.0 if self._enforce_tw else 0.0)

                    cand = max(c_prev, score) if is_makespan else c_prev + score
                    if cand < cost_to[j + 1, m]:
                        cost_to[j + 1, m] = cand
                        pred_i[j + 1, m] = i

        if np.isfinite(cost_to[n, k]):
            assigned: list[list[int]] = [[] for _ in range(k)]
            j, m = n, k
            while m > 0:
                i = int(pred_i[j, m])
                if i < j:
                    assigned[m - 1] = [int(order[x]) for x in range(i, j)]
                    j = i
                m -= 1
            return assigned, True

        return self._greedy_assignment(order), False

    def _greedy_assignment(self, order: np.ndarray) -> list[list[int]]:
        """Fallback when no strictly capacity-feasible k-split exists (FR-7)."""
        n, k = self._n, self._k
        caps = self._veh_caps
        assigned: list[list[int]] = [[] for _ in range(k)]
        v = 0
        curr_load = 0.0
        for t in range(n):
            idx = int(order[t])
            d = float(self._demand[idx])
            if v < k - 1 and curr_load + d > caps[v] + _LOAD_EPS:
                v += 1
                curr_load = 0.0
            assigned[v].append(idx)
            curr_load += d
        return assigned

    def _route_cost(self, veh_idx: int, stop_indices: list[int]) -> float:
        if not stop_indices:
            return 0.0
        d_start = int(self._veh_start_nodes[veh_idx])
        d_end = int(self._veh_end_nodes[veh_idx])
        prev = d_start
        total = 0.0
        for t in stop_indices:
            node = int(self._stop_nodes[int(t)])
            total += self._cost(prev, node)
            prev = node
        total += self._cost(prev, d_end)
        return total
