"""Command-line entry point (system-design.html §16 Phase 0).

    quantroute algorithms                 list optimization strategies
    quantroute info    <instance.vrp>     show a CVRPLIB instance's stats
    quantroute solve   <instance.vrp>     optimize it and print / export the result

``solve`` wires the pieces together — parse -> encoding -> repair -> evaluator -> optimizer
(via :class:`OptimizerFactory`) -> :class:`RunResult` — and can export the convergence trace
(for §14 curves) and the routes.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import typer

from quantroute import (
    CollectingCallback,
    ConstraintSet,
    Depot,
    FitnessEvaluator,
    GreedyRepair,
    Objective,
    OptimizerFactory,
    ProblemSpec,
    RandomKeyGiantTour,
    SearchProblem,
    Stop,
    TerminationCriteria,
    Vehicle,
)
from quantroute.io import CVRPLIBParseError, load_cvrplib

app = typer.Typer(
    add_completion=False,
    help="quantroute — quantum-inspired VRP optimizer (SIH26137).",
    no_args_is_help=True,
)

_OBJECTIVES = {
    "travel-time": Objective.MIN_TRAVEL_TIME,
    "distance": Objective.MIN_DISTANCE,
    "makespan": Objective.MIN_MAKESPAN,
}
# which config field carries the population size, per algorithm
_SIZE_FIELD = {
    "qpso": "swarm_size",
    "pso": "swarm_size",
    "qgpso": "population_size",
    "ga": "population_size",
    "aco": "n_ants",
}


def _fail(message: str) -> None:
    typer.echo(f"error: {message}", err=True)
    raise typer.Exit(code=1)


@app.command()
def algorithms() -> None:
    """List the available optimization strategies."""
    for name in OptimizerFactory.available():
        typer.echo(name)


@app.command()
def info(instance: Path = typer.Argument(..., help="path to a CVRPLIB .vrp file")) -> None:
    """Parse a CVRPLIB instance and print its key numbers."""
    try:
        inst, sol = load_cvrplib(instance)
    except (CVRPLIBParseError, FileNotFoundError, OSError) as exc:
        _fail(str(exc))

    typer.echo(f"name            {inst.spec.name}")
    typer.echo(f"stops           {inst.spec.dimension()}")
    typer.echo(f"vehicles        {inst.num_vehicles}  (from: {inst.num_vehicles_source})")
    typer.echo(f"capacity        {inst.capacity:g}  per vehicle")
    typer.echo(f"total demand    {inst.spec.total_demand:g}")
    typer.echo(f"depot node      {inst.depot_node}")
    typer.echo(f"best known      {inst.best_known if inst.best_known is not None else 'n/a'}")
    if sol is not None:
        typer.echo(f"paired .sol     {sol.num_vehicles} routes, cost {sol.cost}")


@app.command()
def solve(
    instance: Path = typer.Argument(..., help="path to a CVRPLIB .vrp file"),
    algorithm: str = typer.Option("qpso", "--algorithm", "-a", help="qpso | qgpso | pso | ortools"),
    iterations: int = typer.Option(300, "--iterations", "-i", help="max iterations"),
    time_budget: float = typer.Option(
        None, "--time-budget", "-t", help="seconds; stops the run when reached"
    ),
    seed: int = typer.Option(0, "--seed", "-s"),
    pop_size: int = typer.Option(None, "--pop-size", help="swarm / population size"),
    num_vehicles: int = typer.Option(None, "--num-vehicles", "-k", help="override the fleet size"),
    objective: str = typer.Option(
        "travel-time", "--objective", help="travel-time | distance | makespan"
    ),
    no_repair: bool = typer.Option(
        False, "--no-repair", help="disable the capacity repair operator"
    ),
    config: Path = typer.Option(
        None, "--config", "-c", help="YAML file: {algorithm: ..., params: {...}} (overrides flags)"
    ),
    convergence_csv: Path = typer.Option(None, "--convergence-csv", help="write the trace here"),
    routes_json: Path = typer.Option(None, "--routes-json", help="write the solution here"),
    map_html: Path = typer.Option(
        None, "--map-html", help="draw the routes to a standalone HTML map"
    ),
    map_png: Path = typer.Option(None, "--map-png", help="draw the routes to a PNG"),
    as_json: bool = typer.Option(False, "--json", help="print a JSON summary instead of a table"),
) -> None:
    """Optimize a CVRPLIB instance and report the best solution found."""
    if objective not in _OBJECTIVES:
        _fail(f"unknown objective {objective!r}; choose from {', '.join(_OBJECTIVES)}")

    try:
        inst, _ = load_cvrplib(
            instance, num_vehicles=num_vehicles, objective=_OBJECTIVES[objective]
        )
    except (CVRPLIBParseError, FileNotFoundError, OSError, ValueError) as exc:
        _fail(str(exc))

    encoding = RandomKeyGiantTour(inst.spec, inst.matrix)
    repair = None if no_repair else GreedyRepair(inst.spec, inst.matrix)
    evaluator = FitnessEvaluator(inst.spec, inst.matrix, encoding, repair=repair)
    problem = SearchProblem(inst.spec, inst.matrix, encoding, evaluator, best_known=inst.best_known)

    try:
        optimizer = _make_optimizer(algorithm, seed, iterations, pop_size, config)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        _fail(str(exc))

    termination = TerminationCriteria(max_iterations=iterations, time_budget_s=time_budget)
    callback = CollectingCallback()
    result = optimizer.solve(problem, callback=callback, termination=termination)

    summary = _summary(inst, result)

    if convergence_csv is not None:
        _write_convergence(convergence_csv, result)
    if routes_json is not None:
        _write_json(routes_json, summary)
    if map_html is not None or map_png is not None:
        _write_maps(inst, result, map_html, map_png)

    if as_json:
        typer.echo(json.dumps(summary, indent=2))
    else:
        _print_table(summary, result)

    raise typer.Exit(code=0 if result.feasible else 2)


# --------------------------------------------------------------------- helpers


def _make_optimizer(
    algorithm: str, seed: int, iterations: int, pop_size: int | None, config: Path | None
):
    if config is not None:
        import yaml  # local import: only needed for --config

        try:
            raw = yaml.safe_load(config.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise ValueError(f"cannot parse config {config}: {exc}") from None
        if not isinstance(raw, dict):
            raise ValueError(f"config {config} must be a mapping")
        return OptimizerFactory.from_config(raw)

    key = algorithm.strip().lower()
    params: dict[str, object] = {"seed": seed}
    if key != "ortools":
        params["max_iterations"] = iterations
    if pop_size is not None and key in _SIZE_FIELD:
        params[_SIZE_FIELD[key]] = pop_size
    return OptimizerFactory.from_config({"algorithm": key, "params": params})


def _summary(inst, result) -> dict:
    bk = inst.best_known
    gap = result.gap(bk) if (bk is not None and bk > 0) else None
    return {
        "instance": inst.spec.name,
        "stops": inst.spec.dimension(),
        "algorithm": result.algorithm,
        "best_cost": result.best_cost,
        "best_known": bk,
        "gap_pct": None if gap is None else round(gap * 100.0, 4),
        "feasible": result.feasible,
        "vehicles_used": result.metrics.vehicles_used,
        "iterations": result.iterations,
        "stop_reason": result.stop_reason,
        "elapsed_s": round(result.elapsed_s, 4),
        "seed": result.seed,
        "config_hash": result.config_hash,
        "cost_breakdown": {k: round(v, 4) for k, v in result.cost_breakdown.items()},
        "routes": [
            {"vehicle": r.vehicle_id, "stops": list(r.stop_ids)}
            for r in result.routes
            if r.stop_ids
        ],
    }


def _print_table(summary: dict, result) -> None:
    width = 16
    rows = [
        ("instance", summary["instance"]),
        ("stops", summary["stops"]),
        ("algorithm", summary["algorithm"]),
        ("best cost", f"{summary['best_cost']:.4g}"),
        ("best known", summary["best_known"] if summary["best_known"] is not None else "n/a"),
        ("gap", "n/a" if summary["gap_pct"] is None else f"{summary['gap_pct']:.3f}%"),
        ("feasible", summary["feasible"]),
        ("vehicles used", summary["vehicles_used"]),
        ("iterations", summary["iterations"]),
        ("stop reason", summary["stop_reason"]),
        ("elapsed", f"{summary['elapsed_s']:.3f}s"),
        ("config hash", summary["config_hash"]),
    ]
    for label, value in rows:
        typer.echo(f"{label:<{width}}{value}")
    typer.echo("routes:")
    for r in summary["routes"]:
        typer.echo(f"  {r['vehicle']:<6} {' '.join(r['stops'])}")
    if not result.feasible:
        typer.echo("  (solution is INFEASIBLE — see cost_breakdown)", err=True)


def _write_convergence(path: Path, result) -> None:
    try:
        with path.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(["iteration", "elapsed_s", "incumbent_cost"])
            for rec in result.convergence:
                writer.writerow(
                    [rec.iteration, f"{rec.elapsed_s:.6f}", f"{rec.incumbent_cost:.6f}"]
                )
    except OSError as exc:
        _fail(f"cannot write {path}: {exc}")


def _write_json(path: Path, summary: dict) -> None:
    try:
        path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    except OSError as exc:
        _fail(f"cannot write {path}: {exc}")


def _write_maps(inst, result, map_html: Path | None, map_png: Path | None) -> None:
    try:
        from quantroute.viz import render_map_html, render_map_png, routes_to_geojson
    except ImportError as exc:
        _fail(f"map output needs: pip install 'quantroute[viz]'  ({exc})")
    stop_node = {s.id: s.node for s in inst.spec.stops}
    fc = routes_to_geojson(result.routes, inst.coords, inst.depot_node, stop_node=stop_node)
    try:
        if map_html is not None:
            map_html.write_text(render_map_html(fc, title=inst.spec.name), encoding="utf-8")
            typer.echo(f"map: {map_html}")
        if map_png is not None:
            render_map_png(fc, map_png, title=inst.spec.name)
            typer.echo(f"map: {map_png}")
    except OSError as exc:
        _fail(f"cannot write map: {exc}")


@app.command()
def benchmark(
    config: Path = typer.Argument(..., help="path to a benchmark run.yaml"),
    output_dir: Path = typer.Option(
        None, "--output-dir", "-o", help="override the plan's output_dir"
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="print the plan and exit"),
    no_plot: bool = typer.Option(False, "--no-plot", help="skip convergence plots"),
) -> None:
    """Run a dataset x algorithm x seed benchmark and write the report."""
    import dataclasses

    try:
        from quantroute.benchmark import load_plan, run_plan, write_report
        from quantroute.benchmark.config import BenchmarkConfigError
    except ImportError as exc:
        _fail(f"benchmark needs extras: pip install 'quantroute[benchmark]'  ({exc})")

    try:
        plan = load_plan(config)
    except BenchmarkConfigError as exc:
        _fail(str(exc))

    if output_dir is not None:
        plan = dataclasses.replace(plan, output_dir=output_dir)

    if dry_run:
        typer.echo(
            f"{plan.name}: {len(plan.instances)} instances x "
            f"{len(plan.algorithms)} algorithms x {len(plan.seeds)} seeds "
            f"= {plan.total_runs} runs"
        )
        for a in plan.algorithms:
            typer.echo(f"  - {a.id}  {a.params}")
        typer.echo(f"output_dir: {plan.output_dir}")
        raise typer.Exit(code=0)

    def _progress(done: int, total: int, label: str) -> None:
        typer.echo(f"[{done:>4}/{total}] {label}", err=True)

    records = run_plan(plan, progress=_progress)
    out = write_report(records, plan, plan.output_dir, plot=not no_plot)
    typer.echo(f"wrote {out}")


@app.command()
def demo(
    rows: int = typer.Option(6, help="grid rows"),
    cols: int = typer.Option(6, help="grid columns"),
    stops: int = typer.Option(8, help="number of delivery stops"),
    vehicles: int = typer.Option(3, help="fleet size"),
    algorithm: str = typer.Option("qpso", "-a"),
    seed: int = typer.Option(1, "-s"),
    iterations: int = typer.Option(120, "-i"),
    congestion: float = typer.Option(
        0.0, help="if > 0, also solve with every road slowed by this factor"
    ),
    map_html: Path = typer.Option(
        None, "--map-html", help="draw the free-flow routes to an HTML map"
    ),
) -> None:
    """Run the full solver on a synthetic grid road graph (dynamic weights included)."""
    import numpy as np

    from quantroute.roadgraph import RoadGraphMatrix, WeightModel, grid_city

    graph = grid_city(rows, cols, spacing_m=100.0)
    n_nodes = graph.num_nodes
    if stops + 1 > n_nodes:
        _fail(f"grid has only {n_nodes} nodes; reduce --stops")

    rng = np.random.default_rng(seed)
    depot = int(n_nodes // 2)
    choices = [n for n in range(n_nodes) if n != depot]
    stop_nodes = sorted(int(x) for x in rng.choice(choices, size=stops, replace=False))

    wm = WeightModel(graph, smoothing=1.0)

    stop_node = {f"s{n}": n for n in stop_nodes}

    def _solve(epoch, label: str):
        matrix = RoadGraphMatrix(graph, [depot, *stop_nodes], epoch)
        spec = ProblemSpec(
            name=f"grid-{rows}x{cols}",
            depots=(Depot("depot", node=depot),),
            stops=tuple(Stop(f"s{n}", node=n, demand=10.0) for n in stop_nodes),
            vehicles=tuple(
                Vehicle(f"v{i}", capacity=100.0, start_depot="depot") for i in range(vehicles)
            ),
            constraints=ConstraintSet(enforce_time_windows=False),
        )
        enc = RandomKeyGiantTour(spec, matrix)
        ev = FitnessEvaluator(spec, matrix, enc, repair=GreedyRepair(spec, matrix))
        problem = SearchProblem(spec, matrix, enc, ev)
        key = _SIZE_FIELD.get(algorithm.strip().lower(), "swarm_size")
        opt = OptimizerFactory.from_config(
            {
                "algorithm": algorithm,
                "params": {"seed": seed, "max_iterations": iterations, key: 30},
            }
        )
        res = opt.solve(problem, termination=TerminationCriteria(max_iterations=iterations))
        typer.echo(
            f"{label:<14} best={res.best_cost:9.1f}s  feasible={res.feasible}  "
            f"vehicles={res.metrics.vehicles_used}  {res.elapsed_s:.2f}s"
        )
        return res, epoch

    typer.echo(
        f"grid {rows}x{cols}: {n_nodes} nodes, {graph.num_edges} edges | depot {depot} | {stops} stops"
    )
    free_res, free_epoch = _solve(wm.free_flow_epoch(), "free-flow")
    if congestion > 0.0:
        jam = wm.update(unobserved_factor=1.0 + congestion, source="demo-congestion")
        _solve(jam, f"congested x{1 + congestion:g}")

    if map_html is not None:
        try:
            from quantroute.viz import render_map_html, routes_to_geojson
        except ImportError as exc:
            _fail(f"map output needs: pip install 'quantroute[viz]'  ({exc})")
        coords = graph.coordinates()
        fc = routes_to_geojson(
            free_res.routes,
            coords,
            depot,
            stop_node=stop_node,
            road_graph=graph,
            epoch=free_epoch,
        )
        map_html.write_text(render_map_html(fc, title=f"grid-{rows}x{cols}"), encoding="utf-8")
        typer.echo(f"map: {map_html}")


@app.command()
def showcase(
    output_dir: Path = typer.Option(
        Path("demo_results"), "--output-dir", "-o", help="Deliverable-5 output directory"
    ),
    profile: str = typer.Option("quick", help="quick | full"),
    algorithms: str = typer.Option("qpso,qgpso,pso,ga,aco", help="comma-separated algorithms"),
    seeds: str = typer.Option(
        None, help="comma-separated integer seeds; profile defaults if omitted"
    ),
) -> None:
    """Run Deliverable 5: scaling benchmark + traffic incident + standalone dashboard."""
    from quantroute.demonstration import run_demonstration

    algos = tuple(x.strip() for x in algorithms.split(",") if x.strip())
    seed_values = None
    if seeds:
        try:
            seed_values = tuple(int(x.strip()) for x in seeds.split(",") if x.strip())
        except ValueError:
            _fail("--seeds must be comma-separated integers")

    def _progress(done: int, total: int, label: str) -> None:
        typer.echo(f"[{done:>3}/{total}] {label}", err=True)

    try:
        artifacts = run_demonstration(
            output_dir,
            profile=profile,
            algorithms=algos,
            seeds=seed_values,
            progress=_progress,
        )
    except (ValueError, KeyError, ImportError) as exc:
        _fail(str(exc))

    typer.echo(f"dashboard    {artifacts.dashboard}")
    typer.echo(f"report       {artifacts.report}")
    typer.echo(f"raw results  {artifacts.results_json}")


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", help="bind address"),
    port: int = typer.Option(8000, help="port"),
    reload: bool = typer.Option(False, help="auto-reload on code changes (dev)"),
) -> None:
    """Start the HTTP API (Swagger UI at /docs)."""
    try:
        import uvicorn
    except ImportError as exc:
        _fail(f"serve needs: pip install 'quantroute[service]'  ({exc})")
    typer.echo(f"quantroute API on http://{host}:{port}  (docs: http://{host}:{port}/docs)")
    uvicorn.run("quantroute.service:create_app", host=host, port=port, factory=True, reload=reload)


def main() -> None:
    app()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(app())
