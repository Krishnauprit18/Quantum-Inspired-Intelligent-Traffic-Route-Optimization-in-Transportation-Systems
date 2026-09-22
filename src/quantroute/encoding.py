"""Continuous vector <-> routes: the ``Encoding`` layer from system-design.html §9.

QPSO / PSO search a real-valued space. An ``Encoding`` is the bridge between a particle's
position vector and a concrete :class:`~quantroute.routes.Routes`:

  * ``random(rng)``  — draw a fresh position;
  * ``bounds()``     — the box the optimizer clips to;
  * ``decode(keys)`` — position -> routes.

``RandomKeyGiantTour`` is the standard *route-first, split-second* scheme (Prins, 2004):

  1. **Giant tour** — sort the stops by their key value to get one ordering of every stop.
  2. **Split** — cut that ordering into consecutive segments, one per vehicle, by an
     optimal O(n * W) Bellman recurrence that respects vehicle capacity and minimises the
     sum of route costs (``W`` = max stops that fit in one vehicle).

The split here is the *unbounded* Bellman recurrence (minimise total cost over any number
of capacity-feasible routes), then a fold: if it yields more than ``k`` routes the surplus
stops go into the last vehicle and the result is flagged ``feasible=False`` — never hidden
(FR-7); the evaluator (piece 4) turns that into a penalty. Known limitation: for a given
ordering the unbounded optimum can use more than ``k`` routes even when a costlier split
into ``<= k`` routes is feasible, so such orderings are reported infeasible here; a true
``k``-bounded split DP is a later refinement. In practice, with a realistically sized fleet
the unbounded optimum almost always uses ``<= k`` routes (extra routes cost extra depot
legs). Complexity per decode: ``O(n * W)`` (``W`` = stops that fit one vehicle).

Scope for this piece: **single depot, homogeneous capacity, sum objective** (travel time
or distance). Multi-depot, heterogeneous fleets and a makespan split are later pieces and
raise :class:`NotImplementedError` rather than silently mis-solving.
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
    """Sum of the produced routes' costs under the instance objective."""
    feasible: bool
    """True iff every route is within capacity and no more than ``k`` vehicles are used."""


class RandomKeyGiantTour:
    """Random-key giant-tour encoding with a capacity-aware optimal split.

    Parameters
    ----------
    spec:
        The instance. Must be single-depot with a homogeneous fleet capacity and a
        sum objective (``MIN_TRAVEL_TIME`` or ``MIN_DISTANCE``).
    matrix:
        Cost oracle covering the depot and every stop node.
    """

    __slots__ = (
        "_n",
        "_stop_ids",
        "_stop_nodes",
        "_demand",
        "_vehicle_ids",
        "_k",
        "_cap",
        "_depot_node",
        "_cost",
    )

    def __init__(self, spec: ProblemSpec, matrix: CostMatrix) -> None:
        if spec.objective is Objective.MIN_MAKESPAN:
            raise NotImplementedError(
                "RandomKeyGiantTour supports sum objectives (travel time / distance); "
                "a makespan split is a later piece"
            )
        if len(spec.depots) != 1:
            raise NotImplementedError(
                f"single-depot instances only for now; spec '{spec.name}' has "
                f"{len(spec.depots)} depots"
            )
        capacities = {v.capacity for v in spec.vehicles}
        if len(capacities) != 1:
            raise NotImplementedError(
                "homogeneous fleet capacity only for now; "
                f"spec '{spec.name}' has capacities {sorted(capacities)}"
            )

        depot = spec.depots[0]
        for v in spec.vehicles:
            if v.start_depot != depot.id or v.effective_end_depot != depot.id:
                raise NotImplementedError(
                    "every vehicle must start and end at the single depot for now "
                    f"(vehicle {v.id!r} does not)"
                )

        known_nodes = set(matrix.nodes)
        missing = sorted(
            {s.node for s in spec.stops if s.node not in known_nodes}
            | ({depot.node} if depot.node not in known_nodes else set())
        )
        if missing:
            raise ValueError(
                f"cost matrix is missing {len(missing)} node(s) from the instance: "
                f"{missing[:10]}{' ...' if len(missing) > 10 else ''}"
            )

        self._n = len(spec.stops)
        self._stop_ids: tuple[str, ...] = tuple(s.id for s in spec.stops)
        self._stop_nodes = np.array([s.node for s in spec.stops], dtype=np.int64)
        self._demand = np.array([s.demand for s in spec.stops], dtype=np.float64)
        self._stop_nodes.setflags(write=False)  # instance data is read-only after build
        self._demand.setflags(write=False)
        self._vehicle_ids: tuple[str, ...] = tuple(v.id for v in spec.vehicles)
        self._k = len(spec.vehicles)
        self._cap = float(capacities.pop())
        self._depot_node = int(depot.node)
        self._cost = (
            matrix.distance if spec.objective is Objective.MIN_DISTANCE else matrix.travel_time
        )

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

        segments, split_feasible = self._split(order)

        num_routes = len(segments)
        if num_routes <= self._k:
            route_idx = [list(order[a:b]) for (a, b) in segments]
            route_idx.extend([] for _ in range(self._k - num_routes))
            over_k = False
        else:
            route_idx = [list(order[a:b]) for (a, b) in segments[: self._k - 1]]
            tail_start = segments[self._k - 1][0]
            route_idx.append(list(order[tail_start:]))
            over_k = True

        routes = tuple(
            Route(vehicle_id=vid, stop_ids=tuple(self._stop_ids[int(t)] for t in idxs))
            for vid, idxs in zip(self._vehicle_ids, route_idx, strict=False)
        )
        total = sum(self._route_cost(idxs) for idxs in route_idx)
        return Decoded(
            routes=Routes(routes),
            cost=float(total),
            feasible=split_feasible and not over_k,
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

    def _leg(self, a: int, b: int) -> float:
        return self._cost(a, b)

    def _split(self, order: np.ndarray) -> tuple[list[tuple[int, int]], bool]:
        """Optimal capacity-constrained split of the giant tour.

        Returns ``(segments, feasible)`` where each segment is a half-open
        ``(start, end)`` slice into ``order``. ``feasible`` is False only when some
        stop's demand alone exceeds capacity (no split can work); then a greedy
        next-fit partition is returned so the caller still has routes to score.
        """
        n = self._n
        nodes = [int(x) for x in self._stop_nodes[order]]
        dem = self._demand[order]
        cap = self._cap

        # cumulative intra-tour cost so a segment's middle stretch is an O(1) lookup
        prefix = np.zeros(n, dtype=np.float64)
        for t in range(1, n):
            prefix[t] = prefix[t - 1] + self._leg(nodes[t - 1], nodes[t])
        d_out = np.array([self._leg(self._depot_node, c) for c in nodes], dtype=np.float64)
        d_in = np.array([self._leg(c, self._depot_node) for c in nodes], dtype=np.float64)

        cost_to = np.full(n + 1, np.inf, dtype=np.float64)
        cost_to[0] = 0.0
        pred = np.full(n + 1, -1, dtype=np.int64)

        for i in range(n):
            if not np.isfinite(cost_to[i]):
                continue
            load = 0.0
            for j in range(i, n):
                load += dem[j]
                if load > cap + _LOAD_EPS:
                    break
                route_cost = d_out[i] + (prefix[j] - prefix[i]) + d_in[j]
                candidate = cost_to[i] + route_cost
                if candidate < cost_to[j + 1]:
                    cost_to[j + 1] = candidate
                    pred[j + 1] = i

        if np.isfinite(cost_to[n]):
            segments: list[tuple[int, int]] = []
            j = n
            while j > 0:
                i = int(pred[j])
                segments.append((i, j))
                j = i
            segments.reverse()
            return segments, True

        return self._greedy_segments(dem), False

    def _greedy_segments(self, dem_in_order: np.ndarray) -> list[tuple[int, int]]:
        n = self._n
        cap = self._cap
        segments: list[tuple[int, int]] = []
        i = 0
        while i < n:
            load = 0.0
            j = i
            while j < n:
                nxt = load + float(dem_in_order[j])
                if j > i and nxt > cap + _LOAD_EPS:
                    break
                load = nxt
                j += 1
                if load > cap + _LOAD_EPS:  # a single stop larger than capacity
                    break
            segments.append((i, j))
            i = j
        return segments

    def _route_cost(self, stop_indices: list[int]) -> float:
        if not stop_indices:
            return 0.0
        prev = self._depot_node
        total = 0.0
        for t in stop_indices:
            node = int(self._stop_nodes[int(t)])
            total += self._leg(prev, node)
            prev = node
        total += self._leg(prev, self._depot_node)
        return total
