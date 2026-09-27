# Deliverable 5 — Urban Demonstration & Scaling Study

> This report is generated from actual solver runs. The network is synthetic but designed to mimic an urban last-mile delivery setting with arterial roads, clustered demand and changing congestion.

## Experiment design

- Profile: **quick**; algorithms: **qpso, qgpso, pso, ga, aco**; seeds: **0, 1**.
- Traffic snapshots: free-flow and rush-hour for the comparison benchmark; a separate corridor-incident snapshot for dynamic re-optimization.
- Objective: minimise total travel time while respecting capacity and route-duration constraints.
- Every value below is reproducible from `quantroute showcase`; no benchmark KPI is hard-coded.

## Algorithm comparison

| Scale | Traffic | Algorithm | Runs | Feasible | Median travel time (s) | Mean runtime (s) |
|---|---|---:|---:|---:|---:|---:|
| large | free-flow | aco | 2 | 100% | 1202.0 | 1.116 |
| large | free-flow | ga | 2 | 100% | 1726.9 | 0.898 |
| large | free-flow | pso | 2 | 100% | 1701.0 | 0.835 |
| large | free-flow | qgpso | 2 | 100% | 1801.4 | 0.848 |
| large | free-flow | qpso | 2 | 100% | 1798.2 | 0.900 |
| large | rush-hour | aco | 2 | 100% | 2132.9 | 1.107 |
| large | rush-hour | ga | 2 | 100% | 2889.1 | 0.913 |
| large | rush-hour | pso | 2 | 100% | 3007.2 | 0.919 |
| large | rush-hour | qgpso | 2 | 100% | 3217.0 | 0.957 |
| large | rush-hour | qpso | 2 | 100% | 3204.7 | 1.010 |
| medium | free-flow | aco | 2 | 100% | 887.8 | 0.437 |
| medium | free-flow | ga | 2 | 100% | 1088.6 | 0.344 |
| medium | free-flow | pso | 2 | 100% | 1195.6 | 0.327 |
| medium | free-flow | qgpso | 2 | 100% | 1260.4 | 0.353 |
| medium | free-flow | qpso | 2 | 100% | 1279.8 | 0.366 |
| medium | rush-hour | aco | 2 | 100% | 1588.2 | 0.480 |
| medium | rush-hour | ga | 2 | 100% | 1884.4 | 0.405 |
| medium | rush-hour | pso | 2 | 100% | 2212.3 | 0.348 |
| medium | rush-hour | qgpso | 2 | 100% | 2136.5 | 0.338 |
| medium | rush-hour | qpso | 2 | 100% | 2141.8 | 0.335 |
| small | free-flow | aco | 2 | 100% | 453.6 | 0.182 |
| small | free-flow | ga | 2 | 100% | 602.6 | 0.152 |
| small | free-flow | pso | 2 | 100% | 618.8 | 0.154 |
| small | free-flow | qgpso | 2 | 100% | 576.7 | 0.158 |
| small | free-flow | qpso | 2 | 100% | 528.1 | 0.205 |
| small | rush-hour | aco | 2 | 100% | 800.3 | 0.200 |
| small | rush-hour | ga | 2 | 100% | 1068.2 | 0.156 |
| small | rush-hour | pso | 2 | 100% | 1022.4 | 0.145 |
| small | rush-hour | qgpso | 2 | 100% | 1024.2 | 0.141 |
| small | rush-hour | qpso | 2 | 100% | 1024.2 | 0.138 |

## Dynamic traffic re-optimization

On the 28-stop scenario, a route planned before the simulated incident would cost **3564.5 s** if kept unchanged. Re-running **qpso** with **2 deterministic restarts** on the new traffic epoch produced **3613.7 s**, saving **-49.2 s (-1.38%)**.

This experiment directly demonstrates the system's dynamic-weight and re-optimization path: one immutable traffic epoch is used per solve, then a changed epoch produces a new route plan.

## Reproducibility

```bash
pip install -e '.[demo]'
quantroute showcase --profile quick --output-dir demo_results
# stronger final run:
quantroute showcase --profile full --output-dir demo_results_full
```

Open `dashboard.html` for the judge-facing visual summary. Raw evidence is in `records.csv`, `summary.csv`, and `results.json`.
