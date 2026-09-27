"""Real-time traffic streaming simulator and SUMO integration (SIH26137).

Provides:
  * :class:`TrafficProbe` and :class:`TrafficStreamSimulator`: generates dynamic rush-hour
    congestion waves, unexpected corridor incidents, and stochastic vehicle speed probes.
  * :class:`SUMOOutputParser`: ingests simulation dumps from Eclipse SUMO (Simulation of
    Urban MObility) and maps them onto edge travel-time updates for :class:`WeightModel`.
"""

from __future__ import annotations

import math
from collections.abc import Generator, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from defusedxml import ElementTree as ET

from quantroute.roadgraph.graph import RoadGraph
from quantroute.roadgraph.weights import WeightEpoch, WeightModel


@dataclass(frozen=True, slots=True)
class TrafficProbe:
    """Individual vehicle speed telemetry probe."""

    edge_id: int
    speed_kph: float
    timestamp: float
    vehicle_id: str = "probe"


class SUMOOutputParser:
    """Parses SUMO edge data output XML (e.g. netdump / edgedata) into speed observations."""

    @staticmethod
    def parse_edge_speeds(xml_source: str | Path) -> dict[str, float]:
        """Extract ``{edge_id_str: speed_m_s}`` from a SUMO edge-data XML document."""
        if isinstance(xml_source, Path) or (
            isinstance(xml_source, str) and not xml_source.strip().startswith("<")
        ):
            tree = ET.parse(xml_source)
            root = tree.getroot()
        else:
            root = ET.fromstring(xml_source)

        speeds: dict[str, float] = {}
        for edge_el in root.iter("edge"):
            eid = edge_el.attrib.get("id")
            spd_str = edge_el.attrib.get("speed")
            if eid and spd_str:
                try:
                    spd_ms = float(spd_str)
                    if spd_ms > 0:
                        speeds[eid] = spd_ms * 3.6  # convert m/s to km/h
                except ValueError:
                    continue
        return speeds


class TrafficStreamSimulator:
    """Simulates real-world urban traffic dynamics and streams updates to a :class:`WeightModel`."""

    def __init__(self, graph: RoadGraph, *, seed: int = 42) -> None:
        self._graph = graph
        self._rng = np.random.default_rng(seed)

    def generate_rush_hour(
        self,
        *,
        arterial_factor: float = 2.5,
        residential_factor: float = 1.3,
    ) -> dict[int, float]:
        """Simulate morning/evening rush hour congestion multipliers."""
        factors: dict[int, float] = {}
        classes = self._graph.edge_class
        for eid in range(self._graph.num_edges):
            c = classes[eid]
            if c in ("motorway", "trunk", "primary", "secondary"):
                noise = self._rng.uniform(0.85, 1.15)
                factors[eid] = arterial_factor * noise
            else:
                noise = self._rng.uniform(0.9, 1.1)
                factors[eid] = residential_factor * noise
        return factors

    def generate_incident(
        self,
        edge_ids: Sequence[int],
        *,
        severity_multiplier: float = 6.0,
    ) -> dict[int, float]:
        """Simulate an abrupt traffic accident, lane closure, or waterlogging event."""
        factors: dict[int, float] = {}
        for eid in edge_ids:
            if 0 <= eid < self._graph.num_edges:
                factors[eid] = severity_multiplier
        return factors

    def generate_random_probes(
        self,
        sample_fraction: float = 0.3,
    ) -> dict[int, float]:
        """Simulate floating GPS vehicle speed measurements across a subset of road segments."""
        n_edges = self._graph.num_edges
        sample_count = max(1, int(n_edges * sample_fraction))
        sampled_edges = self._rng.choice(n_edges, size=sample_count, replace=False)

        speeds: dict[int, float] = {}
        classes = self._graph.edge_class
        from quantroute.roadgraph.loaders import _DEFAULT_SPEED_KPH, ROAD_CLASS_SPEED_KPH

        for eid in sampled_edges:
            base_speed = ROAD_CLASS_SPEED_KPH.get(classes[eid], _DEFAULT_SPEED_KPH)
            # Add stochastic fluctuation between 40% to 110% of base speed
            speed_ratio = self._rng.uniform(0.4, 1.1)
            speeds[int(eid)] = round(base_speed * speed_ratio, 1)

        return speeds

    def stream_epochs(
        self,
        model: WeightModel,
        *,
        steps: int = 5,
        incident_step: int | None = 2,
        incident_edge: int = 0,
    ) -> Generator[WeightEpoch, None, None]:
        """Simulate an evolving temporal traffic stream and yield successive :class:`WeightEpoch`s."""
        # Yield free-flow epoch first
        yield model.free_flow_epoch()

        for step in range(1, steps + 1):
            if incident_step is not None and step == incident_step:
                # Sudden crash on the corridor
                incident_factors = self.generate_incident([incident_edge], severity_multiplier=8.0)
                epoch = model.update(
                    congestion_factor=incident_factors,
                    source=f"incident-edge-{incident_edge}",
                )
            else:
                # Evolving rush hour and probe updates
                # Congestion ramps up then clears
                cycle_factor = 1.0 + 1.5 * math.sin((step / steps) * math.pi)
                probes = self.generate_random_probes(sample_fraction=0.4)
                epoch = model.update(
                    edge_speeds_kph=probes,
                    unobserved_factor=cycle_factor,
                    source=f"stream-step-{step}",
                )
            yield epoch
