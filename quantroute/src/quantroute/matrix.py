"""Travel-time / distance lookups between graph nodes.

This is the `TransportGraph.matrix()` role from system-design.html §9, narrowed to what
the optimizer actually needs: given two node ids, how long (and how far) is the leg.

`CostMatrix` is the interface every source implements:
  * `DenseCostMatrix`     — an in-memory N x N table (this file); used for classic
                            benchmark instances where distances are Euclidean.
  * `RoadGraphMatrix`     — later; backed by a routing engine (OSRM / GraphHopper) and
                            pinned to one weight epoch.

Keeping the optimizer behind this interface means swapping Euclidean benchmark data for a
real road network is a one-line change at the call site, not a rewrite (§8.1).

Units: travel time in seconds, distance in metres. For pure-distance instances the two
are equal (unit speed), which keeps objective handling uniform (§9, `Objective`).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

import numpy as np

# Guard against accidentally materialising an enormous dense matrix: an N x N float64
# table costs 8 * N**2 bytes (N = 15_000 -> ~1.8 GB). Callers that genuinely need more
# must opt in explicitly.
DEFAULT_MAX_NODES = 15_000


@runtime_checkable
class CostMatrix(Protocol):
    """Read-only travel-cost oracle over a fixed set of node ids."""

    @property
    def nodes(self) -> tuple[int, ...]:
        """All node ids this matrix can answer for, in a stable order."""
        ...

    def travel_time(self, from_node: int, to_node: int) -> float:
        """Seconds to traverse the leg ``from_node -> to_node``."""
        ...

    def distance(self, from_node: int, to_node: int) -> float:
        """Metres for the leg ``from_node -> to_node``."""
        ...


class DenseCostMatrix:
    """An explicit N x N cost table indexed by node id.

    Parameters
    ----------
    node_ids:
        The node ids, one per matrix row/column. Must be unique.
    time_s:
        ``(N, N)`` array of non-negative, finite travel times in seconds.
        ``time_s[i, j]`` is the cost of ``node_ids[i] -> node_ids[j]``.
    distance_m:
        Optional ``(N, N)`` array of distances in metres. Defaults to ``time_s``
        (unit-speed / pure-distance instances).
    max_nodes:
        Upper bound on ``N`` accepted without complaint (see ``DEFAULT_MAX_NODES``).

    The matrix is **not** required to be symmetric or zero-diagonal; road networks are
    frequently neither.
    """

    __slots__ = ("_node_ids", "_index", "_time", "_dist")

    def __init__(
        self,
        node_ids: Sequence[int],
        time_s: np.ndarray,
        distance_m: np.ndarray | None = None,
        *,
        max_nodes: int = DEFAULT_MAX_NODES,
    ) -> None:
        ids = tuple(int(n) for n in node_ids)
        n = len(ids)
        if n == 0:
            raise ValueError("DenseCostMatrix requires at least one node")
        if len(set(ids)) != n:
            raise ValueError("DenseCostMatrix node_ids must be unique")
        if n > max_nodes:
            raise ValueError(
                f"DenseCostMatrix: {n} nodes exceeds max_nodes={max_nodes}; "
                f"a dense table would use ~{8 * n * n / 1e9:.1f} GB. "
                "Raise max_nodes explicitly or use a sparse/road-graph matrix."
            )

        time_arr = self._validate_square(time_s, n, "time_s")
        if distance_m is None:
            dist_arr = time_arr
        else:
            dist_arr = self._validate_square(distance_m, n, "distance_m")

        self._node_ids = ids
        self._index: dict[int, int] = {node: i for i, node in enumerate(ids)}
        self._time = time_arr
        self._dist = dist_arr

    @staticmethod
    def _validate_square(arr: np.ndarray, n: int, label: str) -> np.ndarray:
        # Own a private C-contiguous float64 copy so the caller cannot mutate our
        # state through a reference they kept, then freeze it (defence in depth —
        # the design treats a cost matrix / weight epoch as immutable, §7/§8).
        a = np.array(arr, dtype=np.float64, order="C", copy=True)
        if a.ndim != 2 or a.shape[0] != a.shape[1]:
            raise ValueError(f"{label} must be a square 2-D array, got shape {a.shape}")
        if a.shape[0] != n:
            raise ValueError(
                f"{label} shape {a.shape} does not match node count {n}"
            )
        if not np.isfinite(a).all():
            raise ValueError(f"{label} contains non-finite values (nan/inf)")
        if (a < 0).any():
            raise ValueError(f"{label} contains negative costs")
        a.setflags(write=False)
        return a

    @property
    def nodes(self) -> tuple[int, ...]:
        return self._node_ids

    def _pos(self, node: int) -> int:
        try:
            return self._index[int(node)]
        except KeyError:
            raise KeyError(f"node {node!r} is not in this cost matrix") from None

    def travel_time(self, from_node: int, to_node: int) -> float:
        return float(self._time[self._pos(from_node), self._pos(to_node)])

    def distance(self, from_node: int, to_node: int) -> float:
        return float(self._dist[self._pos(from_node), self._pos(to_node)])

    def route_time(self, nodes: Sequence[int]) -> float:
        """Total travel time along ``nodes`` (sum of consecutive legs, no service time)."""
        return self._walk(nodes, self._time)

    def route_distance(self, nodes: Sequence[int]) -> float:
        """Total distance along ``nodes`` (sum of consecutive legs)."""
        return self._walk(nodes, self._dist)

    def _walk(self, nodes: Sequence[int], table: np.ndarray) -> float:
        if len(nodes) < 2:
            return 0.0
        idx = [self._pos(n) for n in nodes]
        rows = np.asarray(idx[:-1])
        cols = np.asarray(idx[1:])
        return float(table[rows, cols].sum())

    def submatrix_time(self, nodes: Sequence[int]) -> np.ndarray:
        """Dense ``(k, k)`` travel-time block for ``nodes`` (order preserved)."""
        idx = [self._pos(n) for n in nodes]
        return self._time[np.ix_(idx, idx)].copy()

    def __len__(self) -> int:
        return len(self._node_ids)

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"DenseCostMatrix(n={len(self)})"


def euclidean_matrix_2d(
    node_ids: Sequence[int],
    xs: Sequence[float],
    ys: Sequence[float],
    *,
    round_to_int: bool = True,
    max_nodes: int = DEFAULT_MAX_NODES,
) -> DenseCostMatrix:
    """Build a symmetric cost matrix from 2-D coordinates.

    With ``round_to_int=True`` this reproduces the TSPLIB ``EUC_2D`` rule
    ``nint(d) = floor(d + 0.5)`` (round half *up*, not NumPy's round-half-to-even),
    which is what CVRPLIB best-known values assume — keep it on when comparing against
    published results.
    """
    x = np.asarray(xs, dtype=np.float64)
    y = np.asarray(ys, dtype=np.float64)
    n = len(node_ids)
    if x.shape != (n,) or y.shape != (n,):
        raise ValueError(
            f"coordinate arrays must each have length {n}, "
            f"got xs={x.shape}, ys={y.shape}"
        )
    if n > max_nodes:
        raise ValueError(
            f"euclidean_matrix_2d: {n} nodes exceeds max_nodes={max_nodes}"
        )

    dx = x[:, None] - x[None, :]
    dy = y[:, None] - y[None, :]
    dist = np.sqrt(dx * dx + dy * dy)
    if round_to_int:
        dist = np.floor(dist + 0.5)  # TSPLIB nint(): round half up
    np.fill_diagonal(dist, 0.0)
    return DenseCostMatrix(node_ids, time_s=dist, max_nodes=max_nodes)
