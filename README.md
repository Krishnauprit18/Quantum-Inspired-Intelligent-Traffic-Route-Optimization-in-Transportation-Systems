# quantroute

Quantum-inspired (QPSO) traffic route optimization core for SIH26137.
Implements the `optimization-core` package from `system-design.html` (§9), built up
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
| 13 | Full demonstration: scalable urban instances + varying traffic + benchmark evidence + standalone dashboard (`quantroute showcase`, `docs/deliverable5.md`) | done |

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


## Deliverable 5 — judge-ready demonstration

Run a reproducible urban scaling study and generate the polished standalone dashboard:

```bash
pip install -e .
quantroute showcase --profile quick --output-dir demo_results
# final / stronger benchmark
quantroute showcase --profile full --output-dir demo_results_full
```

Outputs include `dashboard.html`, `demonstration.md`, raw `records.csv`, aggregated `summary.csv`, and `results.json`. The experiment covers free-flow/rush-hour benchmarking plus an incident re-optimization case. See `docs/deliverable5.md` and `docs/presentation_storyboard.md`.


## Secure production foundation (v1.0.0-rc1)

This branch upgrades the demo-grade package with secure-by-default production configuration, API authentication, HTTP hardening, corrected dependency packaging, non-root container deployment, shift-left CI/security gates, threat-model documentation, and reproducible local deployment scripts. See `docs/PRODUCTION_MIGRATION.md` and `docs/security/SHIFT_LEFT.md`.

**Important:** this is a production-engineering foundation, not a claim that a fleet deployment has completed field validation. Durable operational persistence, user/driver RBAC, audit-log storage, TLS termination, GPS ingestion, backup/restore validation, and a client-specific penetration test remain release gates for a real-world rollout.
