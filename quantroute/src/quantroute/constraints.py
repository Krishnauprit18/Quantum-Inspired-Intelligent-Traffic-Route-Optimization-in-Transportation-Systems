"""Constraint checking: the ``ConstraintSet / Validator`` role from system-design.html §9.

``ConstraintValidator.evaluate(routes)`` walks each route once, in time, and returns a
:class:`SolutionMetrics` bundle: per-route travel time / distance / load / duration, the
soft-constraint breaches (capacity overflow, time-window lateness, duration overrun) and a
flat list of :class:`Violation` records. Nothing is hidden — an infeasible solution comes
back fully measured so the evaluator (piece 4) can price it (FR-7).

Time model for one route ``depot -> s1 -> ... -> sN -> depot``:
    * depart the start depot at ``vehicle.shift_start_s``;
    * at each stop, arrive = now + leg travel; if time windows are enforced, wait until
      ``tw_open`` before serving; lateness is always measured as
      ``max(0, arrive - tw_close)`` (served late, never skipped);
    * ``duration`` is return-time minus ``shift_start_s``; duration overrun folds together
      the ``constraints.max_route_seconds`` limit and any ``vehicle.shift_end_s`` overrun.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from quantroute.matrix import CostMatrix
from quantroute.problem import ProblemSpec, Stop, Vehicle
from quantroute.routes import Routes

VIOLATION_KINDS = (
    "capacity",
    "time_window",
    "duration",
    "unassigned",
    "duplicate",
    "unknown_vehicle",
    "unknown_stop",
)


@dataclass(frozen=True, slots=True)
class Violation:
    """A single broken constraint. ``amount`` is the magnitude of the breach."""

    kind: str
    amount: float
    detail: str
    route_index: int = -1
    vehicle_id: str | None = None


@dataclass(frozen=True, slots=True)
class RouteMetrics:
    vehicle_id: str
    stops: int
    travel_time_s: float
    distance_m: float
    load: float
    duration_s: float
    capacity_overflow: float
    lateness_s: float
    duration_overflow_s: float

    @property
    def is_feasible(self) -> bool:
        return (
            self.capacity_overflow <= 0.0
            and self.lateness_s <= 0.0
            and self.duration_overflow_s <= 0.0
        )


@dataclass(frozen=True, slots=True)
class SolutionMetrics:
    routes: tuple[RouteMetrics, ...]
    total_travel_time_s: float
    total_distance_m: float
    total_capacity_overflow: float
    total_lateness_s: float
    total_duration_overflow_s: float
    makespan_s: float
    unassigned: tuple[str, ...]
    duplicates: tuple[str, ...]
    violations: tuple[Violation, ...]

    @property
    def is_feasible(self) -> bool:
        return not self.violations

    @property
    def vehicles_used(self) -> int:
        return sum(1 for r in self.routes if r.stops > 0)


class ConstraintValidator:
    """Measures a :class:`~quantroute.routes.Routes` against a :class:`ProblemSpec`."""

    __slots__ = ("_spec", "_matrix", "_stop", "_vehicle", "_veh_depot", "_required")

    def __init__(self, spec: ProblemSpec, matrix: CostMatrix) -> None:
        known = set(matrix.nodes)
        need = {s.node for s in spec.stops} | {d.node for d in spec.depots}
        missing = sorted(need - known)
        if missing:
            raise ValueError(
                f"cost matrix is missing {len(missing)} instance node(s): "
                f"{missing[:10]}{' ...' if len(missing) > 10 else ''}"
            )

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
        self._required = frozenset(self._stop)

    # -- public ---------------------------------------------------------

    def evaluate(self, routes: Routes) -> SolutionMetrics:
        enforce_tw = self._spec.constraints.enforce_time_windows
        max_route_s = self._spec.constraints.max_route_seconds

        route_metrics: list[RouteMetrics] = []
        violations: list[Violation] = []
        visit_count: dict[str, int] = {}

        for idx, route in enumerate(routes):
            veh = self._vehicle.get(route.vehicle_id)
            if veh is None:
                violations.append(
                    Violation(
                        kind="unknown_vehicle",
                        amount=float(len(route.stop_ids)),
                        detail=f"route {idx} assigned to unknown vehicle {route.vehicle_id!r}",
                        route_index=idx,
                        vehicle_id=route.vehicle_id,
                    )
                )
                for sid in route.stop_ids:
                    visit_count[sid] = visit_count.get(sid, 0) + 1
                continue

            rm, rv = self._walk_route(idx, veh, route.stop_ids, enforce_tw, max_route_s, visit_count)
            route_metrics.append(rm)
            violations.extend(rv)

        # -- solution-level checks -----------------------------------
        unassigned = tuple(sorted(self._required - visit_count.keys()))
        duplicates = tuple(sorted(sid for sid, c in visit_count.items() if c > 1))
        for sid in unassigned:
            violations.append(
                Violation(kind="unassigned", amount=1.0, detail=f"stop {sid} is never visited")
            )
        for sid in duplicates:
            violations.append(
                Violation(
                    kind="duplicate",
                    amount=float(visit_count[sid] - 1),
                    detail=f"stop {sid} visited {visit_count[sid]} times",
                )
            )

        return SolutionMetrics(
            routes=tuple(route_metrics),
            total_travel_time_s=math.fsum(r.travel_time_s for r in route_metrics),
            total_distance_m=math.fsum(r.distance_m for r in route_metrics),
            total_capacity_overflow=math.fsum(r.capacity_overflow for r in route_metrics),
            total_lateness_s=math.fsum(r.lateness_s for r in route_metrics),
            total_duration_overflow_s=math.fsum(r.duration_overflow_s for r in route_metrics),
            makespan_s=max((r.duration_s for r in route_metrics), default=0.0),
            unassigned=unassigned,
            duplicates=duplicates,
            violations=tuple(violations),
        )

    def violations(self, routes: Routes) -> tuple[Violation, ...]:
        return self.evaluate(routes).violations

    # -- internals ----------------------------------------------------

    def _walk_route(
        self,
        idx: int,
        veh: Vehicle,
        stop_ids: tuple[str, ...],
        enforce_tw: bool,
        max_route_s: float | None,
        visit_count: dict[str, int],
    ) -> tuple[RouteMetrics, list[Violation]]:
        tt = self._matrix.travel_time
        dd = self._matrix.distance
        start_node, end_node = self._veh_depot[veh.id]

        clock = veh.shift_start_s
        prev = start_node
        load = 0.0
        travel = 0.0
        dist = 0.0
        lateness = 0.0
        local: list[Violation] = []

        for sid in stop_ids:
            visit_count[sid] = visit_count.get(sid, 0) + 1
            stop = self._stop.get(sid)
            if stop is None:
                local.append(
                    Violation(
                        kind="unknown_stop",
                        amount=1.0,
                        detail=f"route {idx} references unknown stop {sid!r}",
                        route_index=idx,
                        vehicle_id=veh.id,
                    )
                )
                continue

            leg_t = tt(prev, stop.node)
            leg_d = dd(prev, stop.node)
            travel += leg_t
            dist += leg_d
            arrive = clock + leg_t
            if enforce_tw:
                lateness += max(0.0, arrive - stop.tw_close_s)
                service_start = max(arrive, stop.tw_open_s)
            else:
                service_start = arrive  # time windows ignored entirely
            clock = service_start + stop.service_s
            load += stop.demand
            prev = stop.node

        travel += tt(prev, end_node)
        dist += dd(prev, end_node)
        clock += tt(prev, end_node)
        duration = clock - veh.shift_start_s

        cap_over = max(0.0, load - veh.capacity)
        dur_over = 0.0
        if max_route_s is not None:
            dur_over += max(0.0, duration - max_route_s)
        if math.isfinite(veh.shift_end_s):
            dur_over += max(0.0, clock - veh.shift_end_s)

        if cap_over > 0.0:
            local.append(
                Violation(
                    kind="capacity",
                    amount=cap_over,
                    detail=f"vehicle {veh.id}: load {load:g} over capacity {veh.capacity:g}",
                    route_index=idx,
                    vehicle_id=veh.id,
                )
            )
        if lateness > 0.0:
            local.append(
                Violation(
                    kind="time_window",
                    amount=lateness,
                    detail=f"vehicle {veh.id}: total lateness {lateness:g}s",
                    route_index=idx,
                    vehicle_id=veh.id,
                )
            )
        if dur_over > 0.0:
            local.append(
                Violation(
                    kind="duration",
                    amount=dur_over,
                    detail=f"vehicle {veh.id}: route duration/shift overrun {dur_over:g}s",
                    route_index=idx,
                    vehicle_id=veh.id,
                )
            )

        return (
            RouteMetrics(
                vehicle_id=veh.id,
                stops=len([s for s in stop_ids if s in self._stop]),
                travel_time_s=travel,
                distance_m=dist,
                load=load,
                duration_s=duration,
                capacity_overflow=cap_over,
                lateness_s=lateness,
                duration_overflow_s=dur_over,
            ),
            local,
        )
