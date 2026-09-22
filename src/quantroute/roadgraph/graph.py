"""In-memory directed road network — the graph model behind PDF Deliverable 1 and
system-design.html §8.1 / §9 (``TransportGraph``).

A :class:`RoadGraph` stores nodes (intersections / depots, with coordinates) and directed
edges (road segments, each with a length and a free-flow travel time). Adjacency is held in
CSR arrays so a Dijkstra relaxation is a tight loop.

Edge *weights* are not stored here — they live in an immutable
:class:`~quantroute.roadgraph.weights.WeightEpoch` and are passed in per query, so the same
graph can be evaluated against many traffic snapshots without mutation (§8.2).
"""

from __future__ import annotations

import heapq
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np


class RoadGraphError(ValueError):
    """Malformed graph, unknown node, or a disconnected origin/destination pair."""


@dataclass(frozen=True, slots=True)
class Path:
    """A concrete route through the graph."""

    nodes: tuple[int, ...]
    edges: tuple[int, ...]
    travel_time_s: float
    distance_m: float


class RoadGraph:
    """Directed weighted road network with shortest-path and many-to-many queries."""

    __slots__ = (
        "_node_ids",
        "_node_xy",
        "_id_to_idx",
        "_edge_src",
        "_edge_dst",
        "_edge_len_m",
        "_edge_free_flow_s",
        "_edge_class",
        "_indptr",
        "_adj_edge",
    )

    def __init__(
        self,
        node_ids: np.ndarray,
        node_xy: np.ndarray,
        edge_src_idx: np.ndarray,
        edge_dst_idx: np.ndarray,
        edge_len_m: np.ndarray,
        edge_free_flow_s: np.ndarray,
        edge_class: Sequence[str],
    ) -> None:
        n = len(node_ids)
        e = len(edge_src_idx)
        if n < 2:
            raise RoadGraphError("a road graph needs at least 2 nodes")
        if e < 1:
            raise RoadGraphError("a road graph needs at least 1 edge")
        for arr, name, length in (
            (edge_dst_idx, "edge_dst_idx", e),
            (edge_len_m, "edge_len_m", e),
            (edge_free_flow_s, "edge_free_flow_s", e),
        ):
            if len(arr) != length:
                raise RoadGraphError(f"{name} length {len(arr)} != edge count {e}")
        if len(edge_class) != e:
            raise RoadGraphError("edge_class length != edge count")

        self._node_ids = np.array(node_ids, dtype=np.int64, copy=True)
        self._node_xy = np.array(node_xy, dtype=np.float64, copy=True).reshape(n, 2)
        if len(set(self._node_ids.tolist())) != n:
            raise RoadGraphError("node ids must be unique")
        self._id_to_idx = {int(nid): i for i, nid in enumerate(self._node_ids)}

        self._edge_src = np.array(edge_src_idx, dtype=np.int64, copy=True)
        self._edge_dst = np.array(edge_dst_idx, dtype=np.int64, copy=True)
        self._edge_len_m = np.array(edge_len_m, dtype=np.float64, copy=True)
        self._edge_free_flow_s = np.array(edge_free_flow_s, dtype=np.float64, copy=True)
        self._edge_class = tuple(str(c) for c in edge_class)

        if self._edge_src.min() < 0 or self._edge_src.max() >= n:
            raise RoadGraphError("edge source index out of range")
        if self._edge_dst.min() < 0 or self._edge_dst.max() >= n:
            raise RoadGraphError("edge destination index out of range")
        if not np.isfinite(self._edge_len_m).all() or (self._edge_len_m < 0).any():
            raise RoadGraphError("edge lengths must be finite and non-negative")
        if not np.isfinite(self._edge_free_flow_s).all() or (self._edge_free_flow_s <= 0).any():
            raise RoadGraphError("edge free-flow times must be finite and > 0")

        for arr in (self._edge_len_m, self._edge_free_flow_s):
            arr.setflags(write=False)

        # CSR adjacency, sorted by source node
        order = np.argsort(self._edge_src, kind="stable")
        self._adj_edge = order.astype(np.int64)
        counts = np.zeros(n + 1, dtype=np.int64)
        np.add.at(counts, self._edge_src + 1, 1)
        self._indptr = np.cumsum(counts)
        for arr in (self._node_ids, self._edge_src, self._edge_dst, self._adj_edge, self._indptr):
            arr.setflags(write=False)

    # -- introspection -----------------------------------------------

    @property
    def num_nodes(self) -> int:
        return len(self._node_ids)

    @property
    def num_edges(self) -> int:
        return len(self._edge_src)

    @property
    def node_ids(self) -> np.ndarray:
        return self._node_ids

    @property
    def edge_free_flow_s(self) -> np.ndarray:
        return self._edge_free_flow_s

    @property
    def edge_len_m(self) -> np.ndarray:
        return self._edge_len_m

    @property
    def edge_class(self) -> tuple[str, ...]:
        return self._edge_class

    def coordinates(self) -> dict[int, tuple[float, float]]:
        """``node id -> (x, y)`` for every node."""
        return {
            int(nid): (float(xy[0]), float(xy[1]))
            for nid, xy in zip(self._node_ids, self._node_xy, strict=False)
        }

    def has_node(self, node_id: int) -> bool:
        return int(node_id) in self._id_to_idx

    def _idx(self, node_id: int) -> int:
        try:
            return self._id_to_idx[int(node_id)]
        except KeyError:
            raise RoadGraphError(f"node {node_id!r} is not in the graph") from None

    # -- queries -------------------------------------------------

    def many_to_many(
        self, sources: Sequence[int], targets: Sequence[int], weights: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray]:
        """Return ``(travel_time[S,T], distance[S,T])`` for every source->target pair
        under per-edge ``weights`` (seconds). ``distance`` is the metres along the
        time-optimal path.
        """
        weights = np.asarray(weights, dtype=np.float64)
        if weights.shape != (self.num_edges,):
            raise RoadGraphError(
                f"weights must have one value per edge ({self.num_edges}), got {weights.shape}"
            )
        s_idx = [self._idx(s) for s in sources]
        t_idx = np.array([self._idx(t) for t in targets], dtype=np.int64)

        time_m = np.empty((len(s_idx), len(t_idx)), dtype=np.float64)
        dist_m = np.empty_like(time_m)
        for i, su in enumerate(s_idx):
            dist, length, _ = self._dijkstra(su, weights, need=t_idx)
            time_m[i] = dist[t_idx]
            dist_m[i] = length[t_idx]
        return time_m, dist_m

    def shortest_path(self, origin: int, destination: int, weights: np.ndarray) -> Path:
        weights = np.asarray(weights, dtype=np.float64)
        if weights.shape != (self.num_edges,):
            raise RoadGraphError("weights must have one value per edge")
        su, tu = self._idx(origin), self._idx(destination)
        dist, length, prev_edge = self._dijkstra(su, weights, need=np.array([tu]))
        if not np.isfinite(dist[tu]):
            raise RoadGraphError(f"no path from node {origin} to node {destination}")

        edges: list[int] = []
        nodes_rev: list[int] = [tu]
        cur = tu
        while cur != su:
            e = int(prev_edge[cur])
            edges.append(e)
            cur = int(self._edge_src[e])
            nodes_rev.append(cur)
        edges.reverse()
        nodes_rev.reverse()
        return Path(
            nodes=tuple(int(self._node_ids[i]) for i in nodes_rev),
            edges=tuple(edges),
            travel_time_s=float(dist[tu]),
            distance_m=float(length[tu]),
        )

    # -- core ------------------------------------------------

    def _dijkstra(
        self, src: int, weights: np.ndarray, need: np.ndarray | None
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        n = self.num_nodes
        dist = np.full(n, np.inf, dtype=np.float64)
        length = np.full(n, np.inf, dtype=np.float64)
        prev_edge = np.full(n, -1, dtype=np.int64)
        dist[src] = 0.0
        length[src] = 0.0

        remaining: set[int] | None = set(int(x) for x in need) if need is not None else None
        heap: list[tuple[float, int]] = [(0.0, src)]

        indptr = self._indptr
        adj_edge = self._adj_edge
        edge_dst = self._edge_dst
        edge_len = self._edge_len_m

        while heap:
            d, u = heapq.heappop(heap)
            if d > dist[u]:
                continue
            if remaining is not None and u in remaining:
                remaining.discard(u)
                if not remaining:
                    break
            for pos in range(indptr[u], indptr[u + 1]):
                eid = int(adj_edge[pos])
                v = int(edge_dst[eid])
                nd = d + weights[eid]
                if nd < dist[v]:
                    dist[v] = nd
                    length[v] = length[u] + edge_len[eid]
                    prev_edge[v] = eid
                    heapq.heappush(heap, (nd, v))
        return dist, length, prev_edge
