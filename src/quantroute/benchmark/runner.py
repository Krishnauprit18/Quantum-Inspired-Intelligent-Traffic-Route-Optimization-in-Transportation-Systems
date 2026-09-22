"""Execute a :class:`BenchmarkPlan`: one solve per (instance, algorithm, seed)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from quantroute.benchmark.config import AlgoSpec, BenchmarkPlan
from quantroute.encoding import RandomKeyGiantTour
from quantroute.evaluate import FitnessEvaluator
from quantroute.io import load_cvrplib
from quantroute.optimizers import OptimizerFactory, SearchProblem
from quantroute.repair import GreedyRepair

ProgressFn = Callable[[int, int, str], None]


@dataclass(frozen=True, slots=True)
class RunRecord:
    instance: str
    instance_path: str
    algorithm: str
    seed: int
    best_cost: float
    best_known: float | None
    gap_pct: float | None
    feasible: bool
    vehicles_used: int
    iterations: int
    elapsed_s: float
    stop_reason: str
    time_to_target_s: float | None
    config_hash: str
    convergence: tuple[tuple[int, float, float], ...] = field(repr=False, default=())

    def row(self) -> dict:
        """Flat mapping for a results table (no convergence blob)."""
        return {
            "instance": self.instance,
            "algorithm": self.algorithm,
            "seed": self.seed,
            "best_cost": self.best_cost,
            "best_known": self.best_known,
            "gap_pct": self.gap_pct,
            "feasible": self.feasible,
            "vehicles_used": self.vehicles_used,
            "iterations": self.iterations,
            "elapsed_s": self.elapsed_s,
            "stop_reason": self.stop_reason,
            "time_to_target_s": self.time_to_target_s,
            "config_hash": self.config_hash,
        }


def run_plan(plan: BenchmarkPlan, *, progress: ProgressFn | None = None) -> list[RunRecord]:
    records: list[RunRecord] = []
    total = plan.total_runs
    done = 0

    for inst_path in plan.instances:
        inst, _ = load_cvrplib(inst_path, objective=plan.objective)
        encoding = RandomKeyGiantTour(inst.spec, inst.matrix)
        repair = GreedyRepair(inst.spec, inst.matrix) if plan.repair else None
        evaluator = FitnessEvaluator(inst.spec, inst.matrix, encoding, repair=repair)
        problem = SearchProblem(
            inst.spec, inst.matrix, encoding, evaluator, best_known=inst.best_known
        )
        term = plan.termination_criteria()

        for algo in plan.algorithms:
            for seed in plan.seeds:
                done += 1
                label = f"{inst.spec.name} / {algo.id} / seed {seed}"
                if progress is not None:
                    progress(done, total, label)
                result = _solve_one(algo, seed, problem, term)
                records.append(
                    _to_record(inst, str(inst_path), algo.id, seed, result, plan.report_target_gap)
                )

    return records


def _solve_one(algo: AlgoSpec, seed: int, problem: SearchProblem, term):
    optimizer = OptimizerFactory.from_config(
        {"algorithm": algo.id, "params": {**algo.params, "seed": seed}}
    )
    return optimizer.solve(problem, termination=term)


def _to_record(
    inst, inst_path: str, algo_id: str, seed: int, result, report_target_gap: float
) -> RunRecord:
    bk = inst.best_known
    gap_pct = (result.best_cost - bk) / bk * 100.0 if (bk is not None and bk > 0) else None
    ttt = _time_to_target(result.convergence, bk, report_target_gap)
    return RunRecord(
        instance=inst.spec.name,
        instance_path=inst_path,
        algorithm=algo_id,
        seed=seed,
        best_cost=result.best_cost,
        best_known=bk,
        gap_pct=gap_pct,
        feasible=result.feasible,
        vehicles_used=result.metrics.vehicles_used,
        iterations=result.iterations,
        elapsed_s=result.elapsed_s,
        stop_reason=result.stop_reason,
        time_to_target_s=ttt,
        config_hash=result.config_hash,
        convergence=tuple(
            (rec.iteration, rec.elapsed_s, rec.incumbent_cost) for rec in result.convergence
        ),
    )


def _time_to_target(convergence, best_known: float | None, target_gap: float) -> float | None:
    if best_known is None or best_known <= 0:
        return None
    threshold = best_known * (1.0 + target_gap)
    for rec in convergence:
        if rec.incumbent_cost <= threshold:
            return rec.elapsed_s
    return None
