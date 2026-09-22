"""Shared driver for population metaheuristics (QPSO, PSO, and later GA / ACO).

All of them run the same outer loop — *iterate -> decode/repair/evaluate -> fold results
into the population's bests -> track the anytime incumbent -> publish -> check termination*
(system-design.html §8.3, §9). Only two things differ per algorithm:

  * how the population is initialised, and
  * the per-iteration move.

``PopulationOptimizer`` owns the loop; a :class:`Population` provides those two operations.
This keeps the comparison in the benchmark harness honest — the strategies differ *only*
in the move (FR-8) — and avoids re-implementing termination / anytime / determinism /
config-hash four times.
"""

from __future__ import annotations

import abc
import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

import numpy as np

from quantroute.evaluate import FitnessResult
from quantroute.optimizers._util import fitness_array
from quantroute.optimizers.base import (
    AnytimeCallback,
    IterationRecord,
    Optimizer,
    RunResult,
    SearchProblem,
    TerminationCriteria,
    default_termination,
)


@runtime_checkable
class Population(Protocol):
    """Algorithm-specific state the shared driver steps through."""

    @property
    def positions(self) -> np.ndarray:
        """Current ``P x D`` positions (read-only)."""
        ...

    def register_costs(self, costs: np.ndarray) -> None:
        """Fold this iteration's fitness values into personal / global bests."""
        ...

    def advance(self, rng: np.random.Generator, iteration: int, max_iterations: int) -> None:
        """Move every member to its next position (mutates internal state)."""
        ...

    def global_best(self) -> tuple[np.ndarray, float]:
        """``(vector, cost)`` of the population's best — for island exchange."""
        ...

    def inject_global_best(self, vector: np.ndarray, cost: float) -> None:
        """Adopt an externally supplied best if it is better."""
        ...


@dataclass(frozen=True, slots=True)
class DriverConfig:
    seed: int = 0
    max_iterations: int = 300
    publish_every: int = 10
    penalty_scale_start: float = 0.2
    penalty_scale_end: float = 1.0
    warm_start_fraction: float = 0.3
    warm_start_jitter: float = 0.05
    exchange_every: int | None = None

    def __post_init__(self) -> None:
        if self.max_iterations < 1:
            raise ValueError("max_iterations must be >= 1")
        if self.publish_every < 1:
            raise ValueError("publish_every must be >= 1")
        if not 0.0 <= self.warm_start_fraction <= 1.0:
            raise ValueError("warm_start_fraction must be in [0, 1]")
        if self.warm_start_jitter < 0.0:
            raise ValueError("warm_start_jitter must be >= 0")
        if self.exchange_every is not None and self.exchange_every < 1:
            raise ValueError("exchange_every must be >= 1 when set")


# island exchange: given (gbest_vector, gbest_cost), optionally return a better one to adopt
ExchangeFn = Callable[[np.ndarray, float], "tuple[np.ndarray, float] | None"]


class _Incumbent:
    """Best solution reported to the caller: the cheapest *feasible* one by base cost,
    falling back to the lowest-fitness infeasible one until a feasible appears."""

    __slots__ = ("vector", "cost", "_feasible_found", "_fallback_fitness")

    def __init__(self) -> None:
        self.vector: np.ndarray | None = None
        self.cost: float = float("inf")
        self._feasible_found = False
        self._fallback_fitness = float("inf")

    def offer(self, results: list[FitnessResult]) -> None:
        for r in results:
            if r.feasible:
                if not self._feasible_found or r.base_cost < self.cost:
                    self._feasible_found = True
                    self.cost = float(r.base_cost)
                    self.vector = np.array(r.vector, copy=True)
            elif not self._feasible_found and r.fitness < self._fallback_fitness:
                self._fallback_fitness = float(r.fitness)
                self.cost = float(r.base_cost)
                self.vector = np.array(r.vector, copy=True)


class PopulationOptimizer(Optimizer, abc.ABC):
    """Outer loop shared by every population metaheuristic in this package."""

    def __init__(self, driver: DriverConfig) -> None:
        self._driver = driver

    # -- subclass responsibilities ------------------------------------

    @abc.abstractmethod
    def _build_population(
        self, rng: np.random.Generator, problem: SearchProblem, warm_start: np.ndarray | None
    ) -> Population: ...

    @abc.abstractmethod
    def _algo_config_for_hash(self) -> dict:
        """Algorithm-specific config fields that affect the result — for ``config_hash``."""
        ...

    # -- the loop ----------------------------------------------------

    def solve(
        self,
        problem: SearchProblem,
        *,
        callback: AnytimeCallback | None = None,
        termination: TerminationCriteria | None = None,
        warm_start: np.ndarray | None = None,
        on_exchange: ExchangeFn | None = None,
    ) -> RunResult:
        dcfg = self._driver
        term = termination or default_termination(problem.spec, dcfg.max_iterations)
        rng = np.random.default_rng(dcfg.seed)
        evaluator = problem.evaluator

        pop = self._build_population(rng, problem, warm_start)

        started = time.perf_counter()
        trace: list[IterationRecord] = []
        incumbent = _Incumbent()

        results = evaluator.evaluate_batch(
            list(pop.positions), penalty_scale=self._penalty_scale(0)
        )
        pop.register_costs(fitness_array(results))
        incumbent.offer(results)
        trace.append(IterationRecord(0, time.perf_counter() - started, incumbent.cost))
        self._publish(callback, 0, incumbent, dcfg.publish_every, force=True)

        stagnation = 0
        stop_reason = "max_iterations"
        it = 0
        while True:
            it += 1
            reason = term.reason_to_stop(
                iteration=it - 1,
                elapsed_s=time.perf_counter() - started,
                incumbent_cost=incumbent.cost,
                best_known=problem.best_known,
                stagnation=stagnation,
            )
            if reason is not None:
                stop_reason = reason
                it -= 1
                break

            pop.advance(rng, it, dcfg.max_iterations)

            results = evaluator.evaluate_batch(
                list(pop.positions), penalty_scale=self._penalty_scale(it)
            )
            pop.register_costs(fitness_array(results))

            before = incumbent.cost
            incumbent.offer(results)
            stagnation = stagnation + 1 if (before - incumbent.cost) <= term.min_improvement else 0

            if (
                dcfg.exchange_every is not None
                and on_exchange is not None
                and it % dcfg.exchange_every == 0
            ):
                offered = on_exchange(*pop.global_best())
                if offered is not None:
                    pop.inject_global_best(offered[0], offered[1])

            trace.append(IterationRecord(it, time.perf_counter() - started, incumbent.cost))
            self._publish(callback, it, incumbent, dcfg.publish_every, force=False)

        return self._finalise(problem, incumbent, trace, it, stop_reason, started, term, callback)

    # -- helpers ---------------------------------------------------

    def _penalty_scale(self, it: int) -> float:
        d = self._driver
        ratio = min(1.0, it / d.max_iterations)
        return d.penalty_scale_start + (d.penalty_scale_end - d.penalty_scale_start) * ratio

    @staticmethod
    def _publish(
        callback: AnytimeCallback | None,
        it: int,
        incumbent: _Incumbent,
        every: int,
        *,
        force: bool,
    ) -> None:
        if callback is None or incumbent.vector is None:
            return
        if force or it % every == 0:
            callback.on_incumbent(it, incumbent.cost, np.array(incumbent.vector, copy=True))

    def _finalise(
        self,
        problem: SearchProblem,
        incumbent: _Incumbent,
        trace: list[IterationRecord],
        iterations: int,
        stop_reason: str,
        started: float,
        term: TerminationCriteria,
        callback: AnytimeCallback | None,
    ) -> RunResult:
        if incumbent.vector is None:  # pragma: no cover - set during iteration 0
            raise RuntimeError(f"{self.name} produced no incumbent")

        final = problem.evaluator.evaluate_one(incumbent.vector, penalty_scale=1.0)
        self._publish(callback, iterations, incumbent, 1, force=True)

        m = final.metrics
        breakdown = {
            "base_cost": final.base_cost,
            "penalty": final.penalty,
            "travel_time_s": m.total_travel_time_s,
            "distance_m": m.total_distance_m,
            "capacity_overflow": m.total_capacity_overflow,
            "lateness_s": m.total_lateness_s,
            "duration_overflow_s": m.total_duration_overflow_s,
            "vehicles_used": float(m.vehicles_used),
        }
        return RunResult(
            algorithm=self.name,
            best_vector=np.array(incumbent.vector, copy=True),
            best_fitness=final.fitness,
            best_cost=final.base_cost,
            routes=final.routes,
            feasible=final.feasible,
            metrics=m,
            cost_breakdown=breakdown,
            convergence=tuple(trace),
            iterations=iterations,
            stop_reason=stop_reason,
            elapsed_s=time.perf_counter() - started,
            seed=self._driver.seed,
            config_hash=self._config_hash(problem, term),
        )

    def _config_hash(self, problem: SearchProblem, term: TerminationCriteria) -> str:
        d = self._driver
        payload = {
            "algorithm": self.name,
            "algo_config": self._algo_config_for_hash(),
            "driver": {
                "seed": d.seed,
                "max_iterations": d.max_iterations,
                "penalty_scale_start": d.penalty_scale_start,
                "penalty_scale_end": d.penalty_scale_end,
                "warm_start_fraction": d.warm_start_fraction,
                "warm_start_jitter": d.warm_start_jitter,
            },
            "termination": {
                "max_iterations": term.max_iterations,
                "time_budget_s": term.time_budget_s,
                "target_gap": term.target_gap,
                "stagnation_iterations": term.stagnation_iterations,
            },
            "instance": {
                "name": problem.spec.name,
                "objective": problem.spec.objective.value,
                "dimension": problem.spec.dimension(),
                "vehicles": len(problem.spec.vehicles),
            },
        }
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def build_initial_positions(
    rng: np.random.Generator,
    encoding,
    swarm_size: int,
    lo: float,
    hi: float,
    warm_start: np.ndarray | None,
    *,
    fraction: float,
    jitter: float,
) -> np.ndarray:
    """Random positions for ``swarm_size`` members, a ``fraction`` of them jittered around
    ``warm_start``. Draw order is fixed — all random rows first, then the warm-start jitter
    — so a given (seed, config, warm_start) triple is fully reproducible. Passing a
    ``warm_start`` consumes extra ``rng.normal`` draws, so a warm-started run and a cold run
    diverge from here on (they are, deliberately, different runs)."""
    dim = encoding.dimension
    rows = np.asarray([encoding.random(rng) for _ in range(swarm_size)], dtype=np.float64)

    if warm_start is not None:
        ws = np.asarray(warm_start, dtype=np.float64)
        if ws.shape != (dim,):
            raise ValueError(f"warm_start must have shape ({dim},), got {ws.shape}")
        if not np.isfinite(ws).all():
            raise ValueError("warm_start contains non-finite values")
        n_ws = int(round(fraction * swarm_size))
        for i in range(n_ws):
            rows[i] = ws + rng.normal(0.0, jitter, size=dim)

    return np.clip(rows, lo, hi)
