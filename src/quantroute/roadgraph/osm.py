"""OpenStreetMap (OSM) city ingestion for real-world transportation networks (SIH26137).

Downloads road networks via the Overpass API using geographical bounding boxes or
pre-configured city presets, filters drivable highway ways, and builds an indexed
:class:`~quantroute.roadgraph.graph.RoadGraph`.
"""

from __future__ import annotations

import logging
import urllib.parse
import urllib.request
from collections.abc import Mapping
from pathlib import Path

from quantroute.roadgraph.graph import RoadGraph, RoadGraphError
from quantroute.roadgraph.loaders import from_osm_xml

logger = logging.getLogger(__name__)

# Bounding boxes (south, west, north, east) for representative urban logistics zones
PRESET_CITIES: Mapping[str, tuple[float, float, float, float]] = {
    "bengaluru": (12.965, 77.585, 12.985, 77.615),  # Central Bangalore (MG Road / Brigade Rd)
    "delhi": (28.625, 77.210, 28.640, 77.230),  # Connaught Place / Central Delhi
    "mumbai": (18.925, 72.825, 18.940, 72.845),  # South Mumbai / Fort
    "pune": (18.515, 73.845, 18.535, 73.865),  # Shivajinagar / FC Road
}

OVERPASS_ENDPOINTS: tuple[str, ...] = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
)


def build_overpass_query(bbox: tuple[float, float, float, float], timeout_s: int = 25) -> str:
    """Build an Overpass QL query for drivable highways in bbox (south, west, north, east)."""
    south, west, north, east = bbox
    return (
        f"[out:xml][timeout:{timeout_s}];\n"
        f"(\n"
        f'  way["highway"~"motorway|trunk|primary|secondary|tertiary|residential|service|unclassified"]'
        f"({south:.5f},{west:.5f},{north:.5f},{east:.5f});\n"
        f"  node(w);\n"
        f");\n"
        f"out body;\n"
    )


def fetch_osm_city(
    city_or_bbox: str | tuple[float, float, float, float],
    *,
    output_path: str | Path | None = None,
    timeout_s: int = 30,
) -> str:
    """Download drivable highway network XML from Overpass API.

    Parameters
    ----------
    city_or_bbox:
        A known preset city name (e.g. 'bengaluru', 'delhi') or a (south, west, north, east) tuple.
    output_path:
        Optional file path to persist the raw .osm XML.
    timeout_s:
        HTTP request timeout in seconds.
    """
    if isinstance(city_or_bbox, str):
        key = city_or_bbox.strip().lower()
        if key not in PRESET_CITIES:
            known = ", ".join(sorted(PRESET_CITIES))
            raise RoadGraphError(
                f"unknown city preset {city_or_bbox!r}; available presets: {known}"
            )
        bbox = PRESET_CITIES[key]
    else:
        bbox = city_or_bbox

    query = build_overpass_query(bbox, timeout_s=timeout_s)
    data = urllib.parse.urlencode({"data": query}).encode("utf-8")

    last_error: Exception | None = None
    for endpoint in OVERPASS_ENDPOINTS:
        try:
            req = urllib.request.Request(
                endpoint,
                data=data,
                headers={"User-Agent": "QuantRoute-OSM-Ingest/1.0 (https://quantroute.org)"},
            )
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                xml_text = resp.read().decode("utf-8")
                if "<osm" not in xml_text or "</osm>" not in xml_text:
                    raise RoadGraphError(f"invalid XML response received from {endpoint}")

                if output_path is not None:
                    p = Path(output_path).expanduser()
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_text(xml_text, encoding="utf-8")

                return xml_text
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            logger.warning("Overpass endpoint %s failed: %s; trying next", endpoint, exc)
            continue

    raise RoadGraphError(f"failed to download OSM data from Overpass API: {last_error}")


def load_city_roadgraph(
    city_or_bbox: str | tuple[float, float, float, float],
    *,
    cache_path: str | Path | None = None,
    max_bytes: int = 256 * 1024 * 1024,
) -> RoadGraph:
    """Fetch or load an OpenStreetMap road network and return a validated :class:`RoadGraph`."""
    if cache_path is not None:
        p = Path(cache_path).expanduser()
        if p.is_file():
            return from_osm_xml(p, max_bytes=max_bytes)

    xml_content = fetch_osm_city(city_or_bbox, output_path=cache_path)
    # Temporary write or direct string parse
    if cache_path is not None:
        return from_osm_xml(cache_path, max_bytes=max_bytes)

    import tempfile

    with tempfile.NamedTemporaryFile("w+", suffix=".osm", encoding="utf-8", delete=True) as tmp:
        tmp.write(xml_content)
        tmp.flush()
        return from_osm_xml(tmp.name, max_bytes=max_bytes)
