"""Piece 6 tests: OptimizerFactory builds strategies from a plain config mapping."""

import pytest

from quantroute import OptimizerFactory, PSOOptimizer, QPSOOptimizer
from quantroute.optimizers.qpso import QPSOConfig


def test_available_lists_registered_algorithms():
    assert set(OptimizerFactory.available()) >= {"pso", "qpso"}


def test_builds_qpso_with_params():
    opt = OptimizerFactory.from_config(
        {"algorithm": "qpso", "params": {"swarm_size": 12, "seed": 3, "beta_min": 0.4}}
    )
    assert isinstance(opt, QPSOOptimizer)
    assert opt.config.swarm_size == 12
    assert opt.config.seed == 3
    assert opt.config.beta_min == 0.4


def test_builds_pso_and_is_case_insensitive():
    opt = OptimizerFactory.from_config({"algorithm": "PSO", "params": {"swarm_size": 8}})
    assert isinstance(opt, PSOOptimizer)
    assert opt.config.swarm_size == 8


def test_missing_params_uses_defaults():
    opt = OptimizerFactory.from_config({"algorithm": "qpso"})
    assert isinstance(opt, QPSOOptimizer)
    assert opt.config.swarm_size == QPSOConfig().swarm_size


def test_unknown_algorithm_is_rejected():
    with pytest.raises(KeyError, match="unknown algorithm"):
        OptimizerFactory.from_config({"algorithm": "genetic-magic"})


def test_unknown_param_is_rejected_not_ignored():
    with pytest.raises(ValueError, match="unknown params"):
        OptimizerFactory.from_config({"algorithm": "qpso", "params": {"swrm_size": 40}})


def test_out_of_range_param_is_rejected_by_config():
    with pytest.raises(ValueError, match="invalid params"):
        OptimizerFactory.from_config({"algorithm": "qpso", "params": {"swarm_size": 1}})


def test_bad_shapes():
    with pytest.raises(TypeError):
        OptimizerFactory.from_config(["qpso"])  # not a mapping
    with pytest.raises(ValueError):
        OptimizerFactory.from_config({"params": {}})  # no algorithm
    with pytest.raises(TypeError):
        OptimizerFactory.from_config({"algorithm": "qpso", "params": [1, 2]})


def test_register_new_strategy():
    class DummyConfig(QPSOConfig):
        pass

    # a throwaway registration to prove the extension point works
    OptimizerFactory.register("qpso-dummy", QPSOOptimizer, QPSOConfig)
    try:
        opt = OptimizerFactory.from_config({"algorithm": "qpso-dummy", "params": {"seed": 9}})
        assert isinstance(opt, QPSOOptimizer) and opt.config.seed == 9
    finally:
        OptimizerFactory._registry.pop("qpso-dummy", None)
