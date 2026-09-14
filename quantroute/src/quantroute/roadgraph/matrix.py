"""``RoadGraphMatrix`` — a :class:`~quantroute.matrix.CostMatrix` backed by a road network.

This is the piece that lets the *whole* solver stack (encoding, evaluator, every optimizer)
run on a real road graph without any change: it precomputes the depot+stops travel-time /
distance matrix for one :class:`WeightEpoch` and answers the same
``travel_time`` / ``distance`` / ``nodes`` interface as the Euclidean
:class:`~quantroute.matrix.DenseCostMatrix`. It adds ``shortest_path`` (the §9
``TransportGraph.shortest_path``) and ``with_epoch`` for re-optimization after a weight
change.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from quantroute.matrix import DenseCostMatrix
from quantroute.roadgraph.graph import Path, RoadGraph, RoadGraphError
from quantroute.roadgraph.weights import WeightEpoch


class RoadGraphMatrix:
    """OD travel-time / distance oracle for a fixed node set at one weight epoch."""

    __slots__ = ("_graph", "_epoch", "_dense")

    def __init__(
        self,
        graph: RoadGraph,
        nodes: Sequence[int],
        epoch: WeightEpoch,
        *,
        max_nodes: int = 20_000,
    ) -> None:
        node_list = [int(n) for n in nodes]
        if len(node_list) < 2:
            raise RoadGraphError("need at least 2 nodes (a depot and a stop)")
        unknown = [n for n in node_list if not graph.has_node(n)]
        if unknown:
            raise RoadGraphError(f"nodes not in the road graph: {unknown[:10]}")

        time_m, dist_m = graph.many_to_many(node_list, node_list, epoch.travel_time_s)
        if not np.isfinite(time_m).all():
            raise RoadGraphError(
                "some node pairs are not connected in the road graph "
                f"(e.g. {_first_disconnected(node_list, time_m)})"
            )

        self._graph = graph
        self._epoch = epoch
        self._dense = DenseCostMatrix(node_list, time_s=time_m, distance_m=dist_m, max_nodes=max_nodes)

    # -- CostMatrix interface -------------------------------------

    @property
    def nodes(self) -> tuple[int, ...]:
        return self._dense.nodes

    def travel_time(self, from_node: int, to_node: int) -> float:
        return self._dense.travel_time(from_node, to_node)

    def distance(self, from_node: int, to_node: int) -> float:
        return self._dense.distance(from_node, to_node)

    def route_time(self, nodes: Sequence[int]) -> float:
        return self._dense.route_time(nodes)

    def route_distance(self, nodes: Sequence[int]) -> float:
        return self._dense.route_distance(nodes)

    def submatrix_time(self, nodes: Sequence[int]) -> np.ndarray:
        return self._dense.submatrix_time(nodes)

    # -- road-graph extras -------------------------------------

    @property
    def epoch(self) -> WeightEpoch:
        return self._epoch

    @property
    def graph(self) -> RoadGraph:
        return self._graph

    def shortest_path(self, origin: int, destination: int) -> Path:
        return self._graph.shortest_path(origin, destination, self._epoch.travel_time_s)

    def with_epoch(self, epoch: WeightEpoch) -> "RoadGraphMatrix":
        """A new matrix over the same nodes, recomputed for ``epoch`` (re-optimization)."""
        return RoadGraphMatrix(self._graph, self._dense.nodes, epoch)

    def __len__(self) -> int:
        return len(self._dense)


def _first_disconnected(nodes: list[int], time_m: np.ndarray) -> str:
    bad = np.argwhere(~np.isfinite(time_m))
    if len(bad) == 0:
        return "?"
    i, j = bad[0]
    return f"{nodes[i]} -> {nodes[j]}"
