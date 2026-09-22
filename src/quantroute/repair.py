"""Feasibility repair: the ``RepairOperator`` role from system-design.html §9.

``GreedyRepair`` targets the constraint the giant-tour split can still leave broken —
**capacity** — plus a cheap time-window tidy-up:

  1. while any route is over capacity, eject its largest-demand stop and reinsert it at the
     cheapest position in a route that has slack (a length-1 ejection chain);
  2. any stop that could not be placed feasibly, and any stop from an unknown-vehicle
     route, is dropped into the cheapest position overall (accepting overflow — the
     validator will still flag it);
  3. if time windows are enforced, stable-sort each route by ``tw_close`` then ``tw_open``
     — reduces lateness without changing which vehicle serves which stop.

Repair is total: it never raises on an infeasible instance, and a conservation check
(``RuntimeError`` on failure) guarantees it never loses or duplicates a stop. Multi-level
ejection chains and time-window-driven ejection are a later refinement.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from quantroute.matrix import CostMatrix
from quantroute.problem import ProblemSpec, Stop, Vehicle
from quantroute.routes import Route, Routes

_EPS = 1e-9


@runtime_checkable
class RepairOperator(Protocol):
    def repair(self, routes: Routes) -> Routes:
        """Return routes that break fewer constraints; same stop set, every stop once."""
        ...


class GreedyRepair:
    __slots__ = ("_spec", "_matrix", "_stop", "_vehicle", "_veh_depot", "_enforce_tw")

    def __init__(self, spec: ProblemSpec, matrix: CostMatrix) -> None:
        self._spec = spec
        self._matrix = matrix
        self._stop: dict[str, Stop] = {s.id: s for s in spec.stops}
        self._vehicle: dict[str, Vehicle] = {v.id: v for v in spec.vehicles}
        self._veh_depot: dict[str, tuple[int, int]] = {
            v.id: (
                spec.depot_by_id(v.start_depot).node,
                spec.depot_by_id(v.effective_end_depot).node,
            )
            for v in spec.vehicles
        }
        self._enforce_tw = spec.constraints.enforce_time_windows

    # -- RepairOperator -------------------------------------------------

    def repair(self, routes: Routes) -> Routes:
        order = list(self._vehicle)  # deterministic vehicle order
        plan: dict[str, list[str]] = {vid: [] for vid in order}
        loose: list[str] = []

        for route in routes:
            if route.vehicle_id in plan:
                plan[route.vehicle_id].extend(s for s in route.stop_ids if s in self._stop)
            else:
                loose.extend(s for s in route.stop_ids if s in self._stop)

        # conservation baseline: the known-stop multiset repair is allowed to rearrange
        original: dict[str, int] = {}
        for bucket in (*plan.values(), loose):
            for sid in bucket:
                original[sid] = original.get(sid, 0) + 1

        self._relieve_overloads(plan, loose)
        self._place_loose(plan, loose)

        if self._enforce_tw:
            for vid in order:
                plan[vid].sort(key=lambda s: (self._stop[s].tw_close_s, self._stop[s].tw_open_s))

        repaired = Routes(tuple(Route(vid, tuple(plan[vid])) for vid in order))

        # invariant: repair conserves the known-stop multiset. A mismatch is a bug in
        # repair itself (not bad input), so fail hard even under `python -O`.
        final: dict[str, int] = {}
        for vid in order:
            for sid in plan[vid]:
                final[sid] = final.get(sid, 0) + 1
        if final != original:
            raise RuntimeError(
                f"GreedyRepair lost or duplicated stops: before={original} after={final}"
            )
        return repaired

    # -- steps -------------------------------------------------------

    def _relieve_overloads(self, plan: dict[str, list[str]], loose: list[str]) -> None:
        guard = sum(len(v) for v in plan.values()) + len(loose) + 1
        for _ in range(guard):
            vid = self._most_overloaded(plan)
            if vid is None:
                return
            victim = max(plan[vid], key=lambda s: (self._stop[s].demand, s))
            plan[vid].remove(victim)
            target, pos = self._cheapest_feasible_insertion(plan, victim, exclude=vid)
            if target is None:
                loose.append(victim)
            else:
                plan[target].insert(pos, victim)

    def _place_loose(self, plan: dict[str, list[str]], loose: list[str]) -> None:
        for sid in sorted(loose, key=lambda s: (-self._stop[s].demand, s)):
            target, pos = self._cheapest_feasible_insertion(plan, sid, exclude=None)
            if target is None:
                target = min(plan, key=lambda vid: (self._load(plan[vid]), vid))
                pos = len(plan[target])
            plan[target].insert(pos, sid)
        loose.clear()

    # -- helpers ---------------------------------------------------

    def _most_overloaded(self, plan: dict[str, list[str]]) -> str | None:
        worst_vid, worst_over = None, _EPS
        for vid, stops in plan.items():
            over = self._load(stops) - self._vehicle[vid].capacity
            if over > worst_over:
                worst_vid, worst_over = vid, over
        return worst_vid

    def _cheapest_feasible_insertion(
        self, plan: dict[str, list[str]], sid: str, *, exclude: str | None
    ) -> tuple[str | None, int]:
        demand = self._stop[sid].demand
        node = self._stop[sid].node
        tt = self._matrix.travel_time
        best: tuple[float, str, int] | None = None  # (insertion delta, vehicle id, position)

        for vid, stops in plan.items():
            if vid == exclude:
                continue
            if self._load(stops) + demand > self._vehicle[vid].capacity + _EPS:
                continue
            start_node, end_node = self._veh_depot[vid]
            seq_nodes = [start_node, *(self._stop[s].node for s in stops), end_node]
            for pos in range(len(stops) + 1):
                a, b = seq_nodes[pos], seq_nodes[pos + 1]
                delta = tt(a, node) + tt(node, b) - tt(a, b)
                candidate = (delta, vid, pos)
                if best is None or candidate < best:  # delta, then vid, then pos — deterministic
                    best = candidate

        if best is None:
            return None, 0
        return best[1], best[2]

    def _load(self, stop_ids: list[str]) -> float:
        return sum(self._stop[s].demand for s in stop_ids)
