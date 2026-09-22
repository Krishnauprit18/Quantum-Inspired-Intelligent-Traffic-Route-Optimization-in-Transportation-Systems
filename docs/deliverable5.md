# Deliverable 5 Implementation

The SIH problem asks for a complete technical demonstration on a real or simulated large-scale scenario. Quantroute implements this through `quantroute.demonstration` and the `quantroute showcase` CLI command.

## What is demonstrated

- **Urban network:** a deterministic Manhattan-style road graph with faster arterial roads, a central logistics hub and clustered/peripheral delivery demand.
- **Dynamic traffic:** free-flow, rush-hour and corridor-incident `WeightEpoch` snapshots. Edge travel times are changed before the OD matrix is rebuilt.
- **VRP constraints:** vehicle capacity and maximum route duration are enforced through the existing evaluator/repair pipeline.
- **Quantum-inspired optimization:** QPSO and QGPSO are benchmarked through exactly the same encoding and evaluator as classical PSO, GA and ACO.
- **Scaling:** quick and full profiles increase road-network size and number of delivery stops.
- **Reproducibility:** every run exports seed, solver, travel time, distance, feasibility, vehicle count and runtime to CSV/JSON.
- **Frontend:** the generated `dashboard.html` is standalone and dependency-free. It renders KPI cards, algorithm comparisons, a route SVG, dynamic-traffic impact and a scaling table without requiring a web server.

## Commands

```bash
# Fast judge/CI run
quantroute showcase --profile quick --output-dir demo_results

# Stronger final experiment (more stops, iterations and seeds)
quantroute showcase --profile full --output-dir demo_results_full

# Restrict algorithms or seeds when profiling hardware
quantroute showcase --profile quick --algorithms qpso,qgpso,pso --seeds 0,1,2
```

The generated directory contains:

```text
dashboard.html      judge-facing visual dashboard
demonstration.md    generated experiment narrative and table
records.csv         one row per solver run
summary.csv         aggregated scale × traffic × algorithm results
results.json        full machine-readable evidence + incident experiment
```

## Interpretation rule

The dashboard intentionally reports the measurements exactly as produced. It does not force the quantum-inspired solver to appear best. ACO, GA or PSO may win an individual synthetic instance. This avoids benchmark cherry-picking and makes the demonstration defensible during judging.

The incident card uses a small deterministic multi-start budget for the stochastic re-optimizer and reports the best feasible QPSO plan. Multi-start is an operational strategy, not a hidden change to the objective; the seeds and number of restarts are stored in `results.json`.

## Replacing the synthetic network with a real city

The demonstration is intentionally isolated behind the `RoadGraph`/`WeightEpoch` interfaces. A production deployment can load OSM/GeoJSON/PostGIS roads and live speed observations, while the QPSO/QGPSO solver, route encoding, repair, evaluator and benchmark reporting remain unchanged.
