"""A candidate solution: one ordered route per vehicle.

`Routes` is pure structure — the sequence of stops each vehicle serves. Cost and
constraint violations are computed elsewhere (piece 4, the evaluator), so the same
`Routes` object can be scored against different weight epochs (system-design.html §7).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from quantroute.problem import ProblemSpec


@dataclass(frozen=True, slots=True)
class Route:
    """One vehicle's plan: depot -> stops in order -> depot.

    `stop_ids` holds only the customer stops; the depots are implied from the
    vehicle definition and added when the route is walked.
    """

    vehicle_id: str
    stop_ids: tuple[str, ...]

    @property
    def is_empty(self) -> bool:
        return len(self.stop_ids) == 0

    def __len__(self) -> int:
        return len(self.stop_ids)


@dataclass(frozen=True, slots=True)
class Routes:
    """A full assignment of every stop to exactly one vehicle route."""

    routes: tuple[Route, ...] = field(default_factory=tuple)

    @classmethod
    def from_lists(cls, assignment: dict[str, list[str]]) -> "Routes":
        """Build from a {vehicle_id: [stop_id, ...]} mapping."""
        return cls(tuple(Route(v, tuple(s)) for v, s in assignment.items()))

    def all_stop_ids(self) -> list[str]:
        out: list[str] = []
        for r in self.routes:
            out.extend(r.stop_ids)
        return out

    @property
    def vehicles_used(self) -> int:
        return sum(1 for r in self.routes if not r.is_empty)

    def covers(self, spec: ProblemSpec) -> tuple[bool, str]:
        """Every stop served exactly once, no unknown stops (FR-3, FR-7)."""
        seen = self.all_stop_ids()
        required = {s.id for s in spec.stops}
        seen_set = set(seen)

        if len(seen) != len(seen_set):
            dupes = sorted({x for x in seen if seen.count(x) > 1})
            return False, f"stops visited more than once: {dupes}"
        missing = required - seen_set
        if missing:
            return False, f"stops never visited: {sorted(missing)}"
        extra = seen_set - required
        if extra:
            return False, f"unknown stops in routes: {sorted(extra)}"
        return True, ""

    def __iter__(self):
        return iter(self.routes)

    def __len__(self) -> int:
        return len(self.routes)
