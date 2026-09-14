"""Fitness: the ``FitnessEvaluator`` role from system-design.html §9.

For a particle position vector the evaluator does: **decode -> (optional) repair -> measure
-> price**. The price follows §9:

    fitness = base_objective
              + scale * ( w_cap * capacity_overflow
                        + w_tw  * time_window_lateness
                        + w_dur * duration_overflow )
              + w_unassigned * (missing_stops + duplicate_visits)

``base_objective`` is total travel time, total distance or makespan per
``spec.objective``. ``scale`` is supplied per iteration by the optimizer so early search
can explore infeasible regions cheaply and late search is driven to feasibility
(structural errors — unassigned / duplicate stops — are never discounted).

``cost_batch`` returns a plain ``float`` array (the hot-loop contract, §9). It is written
as a simple ``map`` so a later piece can swap in a Ray / multiprocessing pool without
touching the maths: the per-vector work is a pure function of the vector plus the shared,
read-only spec and matrix.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace

import numpy as np

from quantroute.constraints import ConstraintValidator, SolutionMetrics
from quantroute.encoding import Encoding
from quantroute.matrix import CostMatrix
from quantroute.problem import Objective, ProblemSpec
from quantroute.repair import RepairOperator
from quantroute.routes import Routes


@dataclass(frozen=True, slots=True)
class PenaltyWeights:
    """Multipliers for the soft-constraint terms of the fitness."""

    capacity: float = 1_000.0
    time_window: float = 1.0
    duration: float = 1.0
    unassigned: float = 1_000_000.0

    def __post_init__(self) -> None:
        for name in ("capacity", "time_window", "duration", "unassigned"):
            if getattr(self, name) < 0:
                raise ValueError(f"PenaltyWeights.{name} must be >= 0")

    def ramped(self, scale: float) -> "PenaltyWeights":
        """Scale the soft terms (capacity / TW / duration); keep ``unassigned`` fixed."""
        if scale < 0:
            raise ValueError("penalty scale must be >= 0")
        return replace(
            self,
            capacity=self.capacity * scale,
            time_window=self.time_window * scale,
            duration=self.duration * scale,
        )


@dataclass(frozen=True, slots=True)
class FitnessResult:
    vector: np.ndarray
    """The position vector that produced this result (owned copy)."""
    fitness: float
    base_cost: float
    penalty: float
    feasible: bool
    routes: Routes
    metrics: SolutionMetrics


class FitnessEvaluator:
    """Scores particle positions for the optimizer (§9)."""

    __slots__ = ("_spec", "_encoding", "_validator", "_repair", "_weights", "_base")

    def __init__(
        self,
        spec: ProblemSpec,
        matrix: CostMatrix,
        encoding: Encoding,
        *,
        repair: RepairOperator | None = None,
        weights: PenaltyWeights | None = None,
    ) -> None:
        self._spec = spec
        self._encoding = encoding
        self._validator = ConstraintValidator(spec, matrix)
        self._repair = repair
        self._weights = weights or PenaltyWeights()
        self._base = {
            Objective.MIN_TRAVEL_TIME: lambda m: m.total_travel_time_s,
            Objective.MIN_DISTANCE: lambda m: m.total_distance_m,
            Objective.MIN_MAKESPAN: lambda m: m.makespan_s,
        }[spec.objective]

    @property
    def weights(self) -> PenaltyWeights:
        return self._weights

    def cost_one(self, vector: np.ndarray, *, penalty_scale: float = 1.0) -> float:
        return self.evaluate_one(vector, penalty_scale=penalty_scale).fitness

    def evaluate_one(self, vector: np.ndarray, *, penalty_scale: float = 1.0) -> FitnessResult:
        routes = self._encoding.decode(vector)
        if self._repair is not None:
            routes = self._repair.repair(routes)
        metrics = self._validator.evaluate(routes)

        w = self._weights.ramped(penalty_scale)
        base = float(self._base(metrics))
        soft = (
            w.capacity * metrics.total_capacity_overflow
            + w.time_window * metrics.total_lateness_s
            + w.duration * metrics.total_duration_overflow_s
        )
        structural = self._weights.unassigned * (
            len(metrics.unassigned) + len(metrics.duplicates)
        )
        penalty = soft + structural
        return FitnessResult(
            vector=np.array(vector, dtype=np.float64, copy=True),
            fitness=base + penalty,
            base_cost=base,
            penalty=penalty,
            feasible=metrics.is_feasible,
            routes=routes,
            metrics=metrics,
        )

    def cost_batch(
        self, vectors: Sequence[np.ndarray] | np.ndarray, *, penalty_scale: float = 1.0
    ) -> np.ndarray:
        return np.fromiter(
            (self.cost_one(v, penalty_scale=penalty_scale) for v in vectors),
            dtype=np.float64,
            count=len(vectors),
        )

    def evaluate_batch(
        self, vectors: Iterable[np.ndarray], *, penalty_scale: float = 1.0
    ) -> list[FitnessResult]:
        return [self.evaluate_one(v, penalty_scale=penalty_scale) for v in vectors]
