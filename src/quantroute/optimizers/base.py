"""Shared optimizer contract: ``Optimizer``, ``TerminationCriteria``, ``AnytimeCallback``,
``RunResult`` (system-design.html §9).

Every search strategy (QPSO, PSO, GA, ACO, OR-Tools) implements the same ``solve`` so the
benchmark harness can swap them by config alone (FR-8). ``SearchProblem`` bundles the four
things they all share — instance, cost oracle, encoding, evaluator — so a comparison
differs *only* in the strategy.

The doc's ``solve(spec, graph, cb)`` maps here to ``solve(problem, callback=...)`` with
``problem`` carrying ``spec`` + ``graph`` (a :class:`~quantroute.matrix.CostMatrix`) plus
the shared encoding/evaluator.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import numpy as np

from quantroute.constraints import SolutionMetrics
from quantroute.encoding import Encoding
from quantroute.evaluate import FitnessEvaluator
from quantroute.matrix import CostMatrix
from quantroute.problem import ProblemSpec
from quantroute.routes import Routes


@dataclass(frozen=True, slots=True)
class SearchProblem:
    """Everything a strategy needs, minus the strategy itself."""

    spec: ProblemSpec
    matrix: CostMatrix
    encoding: Encoding
    evaluator: FitnessEvaluator
    best_known: float | None = None
    """Reference optimum (from a ``.sol`` / literature) — enables the ``target_gap`` stop."""


@dataclass(frozen=True, slots=True)
class TerminationCriteria:
    """When to stop. The first condition that trips wins; ``max_iterations`` always applies
    and also drives the QPSO ``beta`` ramp (§9 update rule).
    """

    max_iterations: int = 300
    time_budget_s: float | None = None
    target_gap: float | None = None
    """Relative gap to ``best_known`` (e.g. ``0.01`` = within 1%) at which to stop."""
    stagnation_iterations: int | None = None
    """Stop after this many consecutive iterations without meaningful improvement."""
    min_improvement: float = 1e-9

    def __post_init__(self) -> None:
        if self.max_iterations < 1:
            raise ValueError("max_iterations must be >= 1")
        if self.time_budget_s is not None and self.time_budget_s <= 0:
            raise ValueError("time_budget_s must be > 0 when set")
        if self.target_gap is not None and self.target_gap < 0:
            raise ValueError("target_gap must be >= 0 when set")
        if self.stagnation_iterations is not None and self.stagnation_iterations < 1:
            raise ValueError("stagnation_iterations must be >= 1 when set")

    def reason_to_stop(
        self,
        *,
        iteration: int,
        elapsed_s: float,
        incumbent_cost: float,
        best_known: float | None,
        stagnation: int,
    ) -> str | None:
        if iteration >= self.max_iterations:
            return "max_iterations"
        if self.time_budget_s is not None and elapsed_s >= self.time_budget_s:
            return "time_budget"
        if (
            self.target_gap is not None
            and best_known is not None
            and best_known > 0.0
            and np.isfinite(incumbent_cost)
            and (incumbent_cost - best_known) / abs(best_known) <= self.target_gap
        ):
            return "target_gap"
        if self.stagnation_iterations is not None and stagnation >= self.stagnation_iterations:
            return "stagnation"
        return None


@runtime_checkable
class AnytimeCallback(Protocol):
    """Notified with the best-so-far incumbent every ``publish_every`` iterations and once
    at the end (§8.3 anytime contract). The service layer's implementation publishes to
    ``job:{id}:events``; tests use :class:`CollectingCallback`.
    """

    def on_incumbent(self, iteration: int, cost: float, vector: np.ndarray) -> None: ...


class NullCallback:
    def on_incumbent(self, iteration: int, cost: float, vector: np.ndarray) -> None:
        return None


class CollectingCallback:
    """Keeps every incumbent it is handed — for inspection and convergence plots."""

    __slots__ = ("records",)

    def __init__(self) -> None:
        self.records: list[tuple[int, float, np.ndarray]] = []

    def on_incumbent(self, iteration: int, cost: float, vector: np.ndarray) -> None:
        self.records.append((iteration, cost, np.array(vector, copy=True)))


@dataclass(frozen=True, slots=True)
class IterationRecord:
    iteration: int
    elapsed_s: float
    incumbent_cost: float


@dataclass(frozen=True, slots=True)
class RunResult:
    """The outcome of a ``solve`` (§9 ``RunResult``)."""

    algorithm: str
    best_vector: np.ndarray
    best_fitness: float
    best_cost: float
    routes: Routes
    feasible: bool
    metrics: SolutionMetrics
    cost_breakdown: dict[str, float]
    convergence: tuple[IterationRecord, ...]
    iterations: int
    stop_reason: str
    elapsed_s: float
    seed: int
    config_hash: str

    def gap(self, reference: float) -> float:
        """Relative gap of ``best_cost`` above ``reference`` (0.05 == 5% worse)."""
        if reference <= 0.0:
            raise ValueError("reference must be > 0 to compute a relative gap")
        return (self.best_cost - reference) / abs(reference)


class Optimizer(abc.ABC):
    """Strategy interface. Subclasses hold their own config and are otherwise stateless."""

    #: short identifier used by the benchmark harness / config
    name: str = "optimizer"

    @abc.abstractmethod
    def solve(
        self,
        problem: SearchProblem,
        *,
        callback: AnytimeCallback | None = None,
        termination: TerminationCriteria | None = None,
    ) -> RunResult:
        """Search for a low-cost solution to ``problem`` and return a :class:`RunResult`."""
        raise NotImplementedError


def default_termination(spec: ProblemSpec, max_iterations: int) -> TerminationCriteria:
    """Termination from the instance's own time budget plus an iteration cap."""
    return TerminationCriteria(
        max_iterations=max_iterations,
        time_budget_s=spec.time_budget_ms / 1000.0,
    )
