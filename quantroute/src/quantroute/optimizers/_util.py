"""Small shared helpers for the optimizer package."""

from __future__ import annotations

import numpy as np

from quantroute.evaluate import FitnessResult


def readonly(arr: np.ndarray) -> np.ndarray:
    """A no-copy read-only view — callers get to read population state, not corrupt it."""
    view = arr.view()
    view.flags.writeable = False
    return view


def fitness_array(results: list[FitnessResult]) -> np.ndarray:
    return np.fromiter((r.fitness for r in results), dtype=np.float64, count=len(results))
