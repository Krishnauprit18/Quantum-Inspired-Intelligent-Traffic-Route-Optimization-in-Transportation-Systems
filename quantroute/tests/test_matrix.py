"""Piece 2 tests: DenseCostMatrix lookups/validation and the Euclidean builder."""

import math

import numpy as np
import pytest

from quantroute import CostMatrix, DenseCostMatrix, euclidean_matrix_2d


def test_dense_lookup_and_nodes():
    t = np.array([[0.0, 3.0], [5.0, 0.0]])
    m = DenseCostMatrix([10, 20], time_s=t)
    assert m.nodes == (10, 20)
    assert m.travel_time(10, 20) == 3.0
    assert m.travel_time(20, 10) == 5.0  # asymmetry preserved
    assert m.distance(10, 20) == 3.0  # distance defaults to time
    assert len(m) == 2
    assert isinstance(m, CostMatrix)  # structural interface satisfied


def test_dense_unknown_node_raises_clearly():
    m = DenseCostMatrix([1, 2], time_s=np.zeros((2, 2)))
    with pytest.raises(KeyError, match="not in this cost matrix"):
        m.travel_time(1, 99)


def test_dense_rejects_bad_arrays():
    with pytest.raises(ValueError, match="square"):
        DenseCostMatrix([1, 2], time_s=np.zeros((2, 3)))
    with pytest.raises(ValueError, match="match node count"):
        DenseCostMatrix([1, 2, 3], time_s=np.zeros((2, 2)))
    with pytest.raises(ValueError, match="non-finite"):
        DenseCostMatrix([1, 2], time_s=np.array([[0.0, np.nan], [1.0, 0.0]]))
    with pytest.raises(ValueError, match="negative"):
        DenseCostMatrix([1, 2], time_s=np.array([[0.0, -1.0], [1.0, 0.0]]))
    with pytest.raises(ValueError, match="unique"):
        DenseCostMatrix([1, 1], time_s=np.zeros((2, 2)))


def test_dense_max_nodes_guard():
    with pytest.raises(ValueError, match="max_nodes"):
        DenseCostMatrix([1, 2, 3], time_s=np.zeros((3, 3)), max_nodes=2)


def test_route_walk_sums_legs():
    m = euclidean_matrix_2d([1, 2, 3], xs=[0, 10, 20], ys=[0, 0, 0])
    assert m.route_time([1, 2, 3, 1]) == 10 + 10 + 20
    assert m.route_distance([1, 2]) == 10
    assert m.route_time([1]) == 0.0  # degenerate


def test_euclidean_euc2d_rounding_matches_tsplib():
    # sqrt(2) ~ 1.414 -> nint -> 1 ; sqrt(8) ~ 2.828 -> 3
    m = euclidean_matrix_2d([1, 2, 3], xs=[0, 1, 2], ys=[0, 1, 2])
    assert m.travel_time(1, 2) == 1.0
    assert m.travel_time(1, 3) == 3.0
    assert m.travel_time(1, 1) == 0.0


def test_euclidean_no_rounding_is_exact():
    m = euclidean_matrix_2d([1, 2], xs=[0, 1], ys=[0, 1], round_to_int=False)
    assert math.isclose(m.travel_time(1, 2), math.sqrt(2), rel_tol=1e-12)


def test_euclidean_rounds_half_up_like_tsplib():
    # distance is exactly 0.5 -> TSPLIB nint -> 1  (NumPy round-half-to-even would give 0)
    m = euclidean_matrix_2d([1, 2], xs=[0.0, 0.5], ys=[0.0, 0.0])
    assert m.travel_time(1, 2) == 1.0


def test_stored_arrays_are_read_only():
    m = euclidean_matrix_2d([1, 2], xs=[0, 3], ys=[0, 0])
    with pytest.raises(ValueError):
        m._time[0, 0] = 99.0  # defence-in-depth: matrix is immutable after construction


def test_euclidean_coordinate_length_mismatch():
    with pytest.raises(ValueError, match="length 3"):
        euclidean_matrix_2d([1, 2, 3], xs=[0, 1], ys=[0, 1, 2])


def test_submatrix_time_block():
    m = euclidean_matrix_2d([5, 6, 7], xs=[0, 3, 6], ys=[0, 0, 0])
    block = m.submatrix_time([7, 5])
    assert block.shape == (2, 2)
    assert block[0, 1] == 6  # 7 -> 5
    assert block[1, 0] == 6  # 5 -> 7
