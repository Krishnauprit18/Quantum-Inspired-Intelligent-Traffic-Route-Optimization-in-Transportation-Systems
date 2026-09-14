# quantroute

Quantum-inspired (QPSO) traffic route optimization core for SIH26137.
Implements the `optimization-core` package from `../system-design.html` (§9), built up
one piece at a time.

## Build order (see system-design.html §16, Phase 0)

| # | Piece | Status |
|---|-------|--------|
| 1 | Domain model — `ProblemSpec`, `Stop`, `Vehicle`, `Depot`, `ConstraintSet`, `Routes` | done |
| 2 | Cost matrix (`CostMatrix` / `DenseCostMatrix`) + CVRPLIB `.vrp` / `.sol` parser | done |
| 3 | Encoding — random-key giant tour + Prins split (`encoding.py`) | done |
| 4 | Constraint validator + repair + fitness evaluator (`constraints.py`, `repair.py`, `evaluate.py`) | done |
| 5 | QPSO optimizer + `Optimizer`/`Swarm`/`TerminationCriteria`/`RunResult` (`optimizers/`) | done |
| 6 | PSO baseline + shared driver + `OptimizerFactory` (`optimizers/driver.py`, `pso.py`, `factory.py`) | done |
| 7 | `qgpso` rotation-gate quantum optimizer (PDF Deliverable 3) + OR-Tools baseline (`optimizers/qgpso.py`, `ortools_solver.py`) | done |
| 11 | GA + ACO baselines (`optimizers/ga.py`, `aco.py`) + `docs/formulation.md` (deliverable 2) | done |
| 8 | CLI — `quantroute solve / info / algorithms / benchmark` (`cli.py`) | done |
| 9 | Benchmark harness — dataset × algorithm × seed, Wilcoxon + Holm, convergence plots (`benchmark/`) | done |
| 10 | Road graph — `RoadGraph` + Dijkstra + `WeightModel` (dynamic weights) + `RoadGraphMatrix` + loaders (`roadgraph/`); `quantroute demo` | done |
| 12 | FastAPI service (`service/`) + routes-on-map viz (`viz/`) + `quantroute serve` (deliverable 4) | done |
| 13 | Full demonstration: larger instance + varying traffic + scaling study -> `docs/demonstration.md` (deliverable 5, O3, O4) | todo |

Road-graph pieces (OSM → PostGIS, OSRM matrix) come after the algorithm core runs on
classic benchmark data.

## Layout

```
src/quantroute/      package
tests/               pytest
data/instances/      benchmark instances
```

## Dev

```
pip install -e ".[dev]"
pytest
```
