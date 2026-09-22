# Mathematical Formulation

> PDF SIH26137 — Deliverable 2. This is the optimization model `quantroute` implements:
> the network, the decision variables, the objective, the constraints, and how the
> quantum-inspired metaheuristics search it. Section references point at the code.

---

## 1. Network model

The transportation network is a **directed weighted graph** `G = (V, A)`
(`quantroute/roadgraph/graph.py`).

| Symbol | Meaning |
|---|---|
| `V` | nodes — road intersections plus depot and customer locations |
| `A ⊆ V × V` | arcs — directed road segments |
| `ℓ_a ≥ 0` | length of arc `a` (metres) |
| `t_a(e) > 0` | travel time of arc `a` under **weight epoch** `e` (seconds) |
| `c_a` | road class of arc `a` (used to derive a free-flow time) |

### Weight epochs (dynamic weights)

A **weight epoch** `e` is an immutable vector `t(e) ∈ ℝ^{|A|}_{>0}` — one travel time per
arc — tagged with an id and a timestamp (`quantroute/roadgraph/weights.py`). Epoch `0` is
free-flow: `t_a(0) = ℓ_a / v(c_a)` with `v(c_a)` the class speed.

New epochs come from observations (measured speeds, measured times, or a congestion
multiplier `φ_a`) blended with an exponential moving average and floored at free-flow:

```
observed_a   = ℓ_a / speed_a        (or measured directly, or φ_a · t_a(0))
smoothed_a   = (1 − α)·t_a(e−1) + α·observed_a
t_a(e)       = max( t_a(0),  smoothed_a )        for observed arcs
t_a(e)       = φ_class · t_a(0)                   for unobserved arcs (optional)
```

A solve **pins one epoch** for its whole run, so the objective is well defined and results
are reproducible. Re-optimization after a traffic change re-derives the cost matrix under
the new epoch (`RoadGraphMatrix.with_epoch`).

### Origin–destination costs

For the routing problem we only need costs between the depot and the customers. Let
`N = {0, 1, …, n}` with `0` the depot and `1…n` the customers. Under a fixed epoch `e`:

```
τ_ij = shortest-path travel time from node(i) to node(j) in G     (Dijkstra)
d_ij = length of that time-optimal path (metres)
```

`τ` and `d` are the `n+1 × n+1` matrices held by `DenseCostMatrix` /
`RoadGraphMatrix`. For classic benchmark instances (CVRPLIB) `G` is complete and
`τ_ij = d_ij =` the rounded Euclidean distance.

---

## 2. The Vehicle Routing Problem

A fleet `K = {1, …, m}` of vehicles, each with capacity `Q_k`, starts and ends at the
depot. Customer `i` has demand `q_i ≥ 0`, service time `s_i ≥ 0`, and a time window
`[a_i, b_i]`.

### Decision variables (arc-flow model)

```
x_{ijk} ∈ {0, 1}   = 1 if vehicle k travels directly from i to j        (i, j ∈ N, k ∈ K)
u_{ik}  ≥ 0        = load on vehicle k after leaving i    (or MTZ rank)
w_{ik}  ≥ 0        = service start time of vehicle k at i
```

### Objective

Minimise total travel time over the pinned epoch (`Objective.MIN_TRAVEL_TIME`;
`MIN_DISTANCE` swaps `τ→d`, `MIN_MAKESPAN` minimises the longest route):

```
min   Σ_{k∈K} Σ_{i∈N} Σ_{j∈N}  τ_ij · x_{ijk}
```

### Constraints

```
(C1) visit once      Σ_{k} Σ_{i}  x_{ijk} = 1                     ∀ j ∈ 1…n
(C2) flow balance    Σ_{i} x_{ipk} − Σ_{j} x_{pjk} = 0            ∀ p ∈ N, k ∈ K
(C3) depot degree    Σ_{j} x_{0jk} ≤ 1 ,  Σ_{i} x_{i0k} ≤ 1       ∀ k ∈ K
(C4) capacity        Σ_{i} Σ_{j} q_j · x_{ijk} ≤ Q_k              ∀ k ∈ K
(C5) time windows    x_{ijk}=1 ⇒ w_{jk} ≥ w_{ik} + s_i + τ_ij
                     a_j ≤ w_{jk} ≤ b_j                           ∀ j, k
(C6) route duration  (return time) − (depart time) ≤ T_max        ∀ k ∈ K
(C7) subtour elim.   MTZ:  u_{ik} − u_{jk} + Q_k·x_{ijk} ≤ Q_k − q_j
```

`T_max` is `ConstraintSet.max_route_seconds`; `[a_i, b_i]` are `Stop.tw_open_s` /
`tw_close_s` and are only active when `ConstraintSet.enforce_time_windows` is true.

This exact model is what `OR-Tools` builds (`optimizers/ortools_solver.py`); it is NP-hard,
so for large `n` the metaheuristics solve a **penalised** version instead.

---

## 3. Metaheuristic formulation

### 3.1 Representation — random-key giant tour

The metaheuristics search a **continuous** space and never touch `x_{ijk}` directly. A
candidate is a vector

```
z ∈ [0, 1]^n          (one "random key" per customer;  D = n)
```

Decoding (`encoding.py`):

1. **Giant tour** — `π = argsort(z)` is an ordering of all `n` customers.
2. **Split** — an `O(n·W)` Bellman recurrence cuts `π` into consecutive segments, one per
   vehicle, minimising total route cost subject to capacity `Q`:

   ```
   f(0) = 0
   f(j) = min over  i < j , load(π_{i+1..j}) ≤ Q  of   f(i) + routecost(i, j)
   routecost(i, j) = τ_{0, π_{i+1}} + Σ_{r=i+1}^{j-1} τ_{π_r, π_{r+1}} + τ_{π_j, 0}
   ```

   If the optimal split needs more than `m` vehicles the surplus is folded into the last
   vehicle and the solution is flagged infeasible (never hidden — FR-7).

So the decision variables the search actually manipulates are the `n` real keys; `(C1)`,
`(C2)`, `(C3)`, `(C7)` are satisfied by construction of the split, and `(C4)` by the
capacity guard inside it.

### 3.2 Penalised objective

`FitnessEvaluator` (`evaluate.py`) scores a decoded solution `R`:

```
fitness(R, s) =  base(R)
              +  s · [ λ_cap · Σ_k max(0, load_k − Q_k)
                     + λ_tw  · Σ_k Σ_i max(0, arrive_{ik} − b_i)
                     + λ_dur · Σ_k max(0, duration_k − T_max) ]
              +  λ_struct · ( |unvisited| + |duplicated| )
```

* `base(R)` = `Σ` route travel time (or distance / makespan).
* `s ∈ [s_0, 1]` ramps with the iteration (`penalty_scale_start → penalty_scale_end`), so
  early search explores infeasible regions cheaply and late search is driven feasible.
* `λ_struct` is large and **not** ramped — structural errors are never discounted.

`GreedyRepair` (`repair.py`) optionally fixes capacity violations by a length-1 ejection
chain before scoring, and tidies each route by due date when time windows are on.

### 3.3 Search operators

All strategies implement one `Optimizer.solve` contract over the shared driver
(`optimizers/driver.py`), differing only in the per-iteration move:

| id | move |
|---|---|
| `qpso` | **delta-potential-well**: `x = p ± L·ln(1/u)`, `p = φ·pbest + (1−φ)·gbest`, `L = 2β·|mbest − x|`, `β: β_max → β_min` |
| `qgpso` | **quantum rotation gate** (PDF Deliverable 3): key `= sin²θ`; `θ ← θ + Δθ` with `Δθ` a bounded rotation toward the pbest / gbest angles, plus a quantum NOT-gate mutation `θ ↦ π/2 − θ` |
| `pso` | inertia-weight velocity: `v = w·v + c₁r₁(pbest−x) + c₂r₂(gbest−x)` |
| `ga` | elitism + tournament + whole-arithmetic crossover + Gaussian mutation |
| `aco` | ant tours from pheromone `τ` and heuristic `η = 1/τ_ij`, converted to keys; MMAS-style `τ` update |
| `ortools` | the exact arc-flow model above, guided local search |

### 3.4 QPSO update rule (per iteration, verbatim from the code)

```
mbest = mean_i pbest_i
β     = β_max − (β_max − β_min) · it / max_it
for each particle i, each dimension:
    φ  ~ U(0,1);   p = φ·pbest_i + (1−φ)·gbest
    u  ~ U(0,1);   L = 2β·|mbest − x_i|
    x_i = p ± L·ln(1/u)        (± by a fair coin)
    x_i = clip(x_i, 0, 1)
```

---

## 4. Termination and reporting

A run stops on the first of: `max_iterations`, a wall-clock `time_budget`, reaching
`target_gap` relative to a known optimum, or `stagnation` (no improvement for _k_
iterations). It returns the best **feasible** solution by `base` cost (falling back to the
least-infeasible until a feasible appears), the full convergence trace
`{(iteration, elapsed_s, incumbent_cost)}`, the cost breakdown, the seed, and a
`config_hash` so the run reproduces exactly.

Benchmarking (`quantroute/benchmark/`, §14 of the design doc) runs the
`instance × algorithm × seed` matrix and compares algorithms with a paired Wilcoxon
signed-rank test, Holm-Bonferroni corrected, plus a rank-biserial effect size.
