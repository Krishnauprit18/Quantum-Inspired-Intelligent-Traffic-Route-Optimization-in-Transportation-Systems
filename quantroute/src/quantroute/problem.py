"""Domain model for a vehicle-routing problem instance.

Mirrors `ProblemSpec` / `ConstraintSet` from system-design.html §9. Kept deliberately
small and free of algorithm concerns: an instance describes *what* to solve, not *how*.

Units: time in seconds, distance in metres, demand and capacity in abstract load units.
Graph nodes are integer ids (OSM node ids later; arbitrary ints for benchmark instances).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Objective(str, Enum):
    """What the optimizer minimises (FR-3). Start with travel time."""

    MIN_TRAVEL_TIME = "min_total_travel_time"
    MIN_DISTANCE = "min_total_distance"
    MIN_MAKESPAN = "min_makespan"  # longest single route


@dataclass(frozen=True, slots=True)
class Depot:
    """A start/end location for vehicles."""

    id: str
    node: int


@dataclass(frozen=True, slots=True)
class Stop:
    """A customer/visit that must be served exactly once (FR-3)."""

    id: str
    node: int
    demand: float = 0.0
    service_s: float = 0.0
    tw_open_s: float = 0.0
    tw_close_s: float = float("inf")

    def __post_init__(self) -> None:
        if self.demand < 0:
            raise ValueError(f"stop {self.id}: demand must be >= 0")
        if self.service_s < 0:
            raise ValueError(f"stop {self.id}: service_s must be >= 0")
        if self.tw_close_s < self.tw_open_s:
            raise ValueError(f"stop {self.id}: time window closes before it opens")

    @property
    def has_time_window(self) -> bool:
        return self.tw_open_s > 0.0 or self.tw_close_s != float("inf")


@dataclass(frozen=True, slots=True)
class Vehicle:
    """One vehicle with a capacity and a shift (FR-3, FR-7)."""

    id: str
    capacity: float
    start_depot: str
    end_depot: str | None = None  # None -> same as start_depot
    shift_start_s: float = 0.0
    shift_end_s: float = float("inf")

    def __post_init__(self) -> None:
        if self.capacity <= 0:
            raise ValueError(f"vehicle {self.id}: capacity must be > 0")
        if self.shift_end_s < self.shift_start_s:
            raise ValueError(f"vehicle {self.id}: shift ends before it starts")

    @property
    def effective_end_depot(self) -> str:
        return self.end_depot if self.end_depot is not None else self.start_depot


@dataclass(frozen=True, slots=True)
class ConstraintSet:
    """Limits the solver must respect or flag (FR-7).

    `enforce_time_windows`:
      * True  — vehicles wait for `tw_open` before serving, and arriving after `tw_close`
        is measured as lateness and reported as a soft `time_window` violation.
      * False — time windows are ignored entirely (no waiting, no lateness). Useful for
        pure CVRP instances and for isolating capacity behaviour when comparing algorithms.
    """

    max_route_seconds: float | None = None
    enforce_time_windows: bool = True
    allow_open_routes: bool = False  # if True, a vehicle need not return to a depot


@dataclass(frozen=True, slots=True)
class ProblemSpec:
    """A complete routing instance.

    `dimension()` is the search-space size the encoding works over: one key per stop
    (see system-design.html §9, random-key giant tour).
    """

    name: str
    depots: tuple[Depot, ...]
    stops: tuple[Stop, ...]
    vehicles: tuple[Vehicle, ...]
    objective: Objective = Objective.MIN_TRAVEL_TIME
    constraints: ConstraintSet = field(default_factory=ConstraintSet)
    time_budget_ms: int = 3000

    def __post_init__(self) -> None:
        if not self.depots:
            raise ValueError(f"{self.name}: at least one depot required")
        if not self.stops:
            raise ValueError(f"{self.name}: at least one stop required")
        if not self.vehicles:
            raise ValueError(f"{self.name}: at least one vehicle required")
        if self.time_budget_ms <= 0:
            raise ValueError(f"{self.name}: time_budget_ms must be > 0")

        depot_ids = {d.id for d in self.depots}
        for v in self.vehicles:
            if v.start_depot not in depot_ids:
                raise ValueError(f"vehicle {v.id}: unknown start_depot {v.start_depot!r}")
            if v.end_depot is not None and v.end_depot not in depot_ids:
                raise ValueError(f"vehicle {v.id}: unknown end_depot {v.end_depot!r}")

        if len({s.id for s in self.stops}) != len(self.stops):
            raise ValueError(f"{self.name}: duplicate stop ids")
        if len({v.id for v in self.vehicles}) != len(self.vehicles):
            raise ValueError(f"{self.name}: duplicate vehicle ids")

    def dimension(self) -> int:
        return len(self.stops)

    @property
    def total_demand(self) -> float:
        return sum(s.demand for s in self.stops)

    @property
    def total_capacity(self) -> float:
        return sum(v.capacity for v in self.vehicles)

    def stop_index(self) -> dict[str, int]:
        """Stable stop-id -> position map; the encoding's key order follows this."""
        return {s.id: i for i, s in enumerate(self.stops)}

    def depot_by_id(self, depot_id: str) -> Depot:
        for d in self.depots:
            if d.id == depot_id:
                return d
        raise KeyError(depot_id)

    def is_trivially_infeasible(self) -> tuple[bool, str]:
        """Cheap pre-check before any search runs."""
        if self.total_demand > self.total_capacity:
            return True, (
                f"total demand {self.total_demand:g} exceeds fleet capacity "
                f"{self.total_capacity:g}"
            )
        max_cap = max(v.capacity for v in self.vehicles)
        for s in self.stops:
            if s.demand > max_cap:
                return True, f"stop {s.id} demand {s.demand:g} exceeds largest vehicle {max_cap:g}"
        return False, ""
