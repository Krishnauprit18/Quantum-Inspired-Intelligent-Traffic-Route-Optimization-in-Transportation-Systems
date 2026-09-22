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
| large | free-flow | aco | 2 | 100% | 1202.0 | 0.470 |
| large | free-flow | ga | 2 | 100% | 1539.0 | 0.272 |
| large | free-flow | pso | 2 | 100% | 1837.1 | 0.276 |
| large | free-flow | qgpso | 2 | 100% | 1691.3 | 0.318 |
| large | free-flow | qpso | 2 | 100% | 1788.5 | 0.275 |
| large | rush-hour | aco | 2 | 100% | 2132.9 | 0.465 |
| large | rush-hour | ga | 2 | 100% | 3024.9 | 0.290 |
| large | rush-hour | pso | 2 | 100% | 3202.9 | 0.273 |
| large | rush-hour | qgpso | 2 | 100% | 3268.2 | 0.260 |
| large | rush-hour | qpso | 2 | 100% | 3114.8 | 0.255 |
| medium | free-flow | aco | 2 | 100% | 884.5 | 0.327 |
| medium | free-flow | ga | 2 | 100% | 1134.0 | 0.181 |
| medium | free-flow | pso | 2 | 100% | 1085.4 | 0.185 |
| medium | free-flow | qgpso | 2 | 100% | 1143.7 | 0.163 |
| medium | free-flow | qpso | 2 | 100% | 1260.4 | 0.152 |
| medium | rush-hour | aco | 2 | 100% | 1588.2 | 0.286 |
| medium | rush-hour | ga | 2 | 100% | 2122.4 | 0.182 |
| medium | rush-hour | pso | 2 | 100% | 1914.4 | 0.230 |
| medium | rush-hour | qgpso | 2 | 100% | 1974.3 | 0.160 |
| medium | rush-hour | qpso | 2 | 100% | 2096.0 | 0.165 |
| small | free-flow | aco | 2 | 100% | 453.6 | 0.160 |
| small | free-flow | ga | 2 | 100% | 586.4 | 0.111 |
| small | free-flow | pso | 2 | 100% | 612.4 | 0.076 |
| small | free-flow | qgpso | 2 | 100% | 576.7 | 0.080 |
| small | free-flow | qpso | 2 | 100% | 570.2 | 0.103 |
| small | rush-hour | aco | 2 | 100% | 800.3 | 0.227 |
| small | rush-hour | ga | 2 | 100% | 1082.3 | 0.091 |
| small | rush-hour | pso | 2 | 100% | 1022.4 | 0.087 |
| small | rush-hour | qgpso | 2 | 100% | 1024.2 | 0.102 |
| small | rush-hour | qpso | 2 | 100% | 1008.3 | 0.097 |

## Dynamic traffic re-optimization

On the 28-stop scenario, a route planned before the simulated incident would cost **3430.7 s** if kept unchanged. Re-running **qpso** with **2 deterministic restarts** on the new traffic epoch produced **3208.2 s**, saving **222.4 s (6.48%)**.

This experiment directly demonstrates the system's dynamic-weight and re-optimization path: one immutable traffic epoch is used per solve, then a changed epoch produces a new route plan.

## Reproducibility

```bash
pip install -e '.[demo]'
quantroute showcase --profile quick --output-dir demo_results
# stronger final run:
quantroute showcase --profile full --output-dir demo_results_full
```

Open `dashboard.html` for the judge-facing visual summary. Raw evidence is in `records.csv`, `summary.csv`, and `results.json`.
