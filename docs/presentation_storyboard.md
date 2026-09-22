# SIH26137 — Judge Presentation Storyboard

This is the recommended 7–8 minute story for the final demonstration. Keep the live dashboard open beside the slides so every claim can be backed by a reproducible artifact.

## 1. Problem in one sentence — 30 sec

Urban fleets lose time because the best route changes when congestion changes. Classical exact routing becomes expensive as the number of stops grows, while a route that was good five minutes ago can become poor after an incident.

**Show:** the problem statement title, then immediately move to the dashboard. Do not spend two minutes defining quantum computing.

## 2. What we built — 45 sec

Quantroute is an end-to-end traffic-aware VRP platform: weighted road graph → dynamic traffic epoch → QPSO/QGPSO optimizer → capacity-safe vehicle routes → benchmark evidence and API/visualization.

**Judge takeaway:** this is not a notebook with one algorithm; it is an executable software platform matching all five requested deliverables.

## 3. Why “quantum-inspired” is real here — 60 sec

Explain the two implementations precisely:

- **QPSO:** particles are sampled around an attractor using the quantum delta-potential-well update; there is no classical velocity vector.
- **QGPSO:** each route-key dimension is represented by a Q-bit angle. The observed key is `sin²(theta)` and rotation-gate updates move the solution toward personal/global best states, with a quantum NOT-style mutation.
- Both use the same random-key route decoder, repair operator and fitness function, so the benchmark comparison is fair.

Avoid claiming quantum speedup. The code is quantum-inspired and runs on classical hardware, exactly as the problem statement requests.

## 4. Live urban scenario — 90 sec

Open `demo_results/dashboard.html`.

1. Point out the synthetic road network with arterials, an urban hub and clustered delivery stops.
2. Show free-flow vs rush-hour in the algorithm selector.
3. Explain that each solve pins one immutable traffic-weight epoch, so results are reproducible.
4. Show the corridor-incident card: the old route is re-evaluated under the incident, then a small deterministic multi-start QPSO budget produces a new feasible route.

**Key line:** “We do not merely increase a congestion score in the UI; the road-edge travel-time matrix is rebuilt and the VRP is solved again against the new epoch.”

## 5. Benchmark evidence — 90 sec

Use the scaling table and raw `records.csv` if judges ask for evidence.

- Multiple algorithms: QPSO, QGPSO, PSO, GA and ACO.
- Multiple random seeds.
- Small, medium and large urban instances.
- Free-flow and rush-hour conditions.
- Feasibility, travel time and runtime are all recorded.

Do **not** promise that QPSO wins every instance. The stronger claim is that the platform provides a reproducible experimental framework and QPSO/QGPSO remain competitive while supporting the requested quantum-inspired design. If another baseline wins a particular case, show it openly.

## 6. Scalability and production path — 60 sec

The hackathon implementation is the optimization core. The existing system design extends it to API gateway/orchestration, graph services, distributed fitness workers, PostGIS/TimescaleDB, cache and object storage. The code already separates graph, weight epochs, solver and API boundaries, so OSM/live-traffic adapters can replace the synthetic generator without rewriting the optimizer.

## 7. Close — 30 sec

Close with the problem-statement deliverables:

1. Weighted graph network model — implemented.
2. Mathematical formulation and constraints — implemented and documented.
3. Quantum-inspired QPSO/QGPSO — implemented.
4. Software/API and route visualization — implemented.
5. Realistic large-instance demonstration, traffic variation, scaling study, dashboard and reproducible evidence — implemented by `quantroute showcase`.

## Demo safety checklist

Before judging, run:

```bash
pip install -e '.[demo,service]'
pytest -q
quantroute showcase --profile full --output-dir demo_results_full
quantroute serve --host 127.0.0.1 --port 8000
```

Keep `demo_results_full/dashboard.html`, `demo_results_full/demonstration.md`, and the API `/docs` page open in separate tabs. If the full benchmark is too slow on the presentation laptop, use the checked-in quick-profile artifacts and explain that the full profile is a longer repeat of the same reproducible pipeline.
