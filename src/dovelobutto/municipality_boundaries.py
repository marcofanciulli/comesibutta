from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Any, Iterable

from .records import SourceDocument, make_record


def _coordinates(geometry: dict[str, Any]) -> Iterable[tuple[float, float]]:
    def walk(value: Any) -> Iterable[tuple[float, float]]:
        if (
            isinstance(value, list)
            and len(value) >= 2
            and isinstance(value[0], (int, float))
            and isinstance(value[1], (int, float))
        ):
            yield float(value[0]), float(value[1])
            return
        if isinstance(value, list):
            for item in value:
                yield from walk(item)

    yield from walk(geometry.get("coordinates", []))


def _bbox(geometry: dict[str, Any]) -> list[float]:
    points = list(_coordinates(geometry))
    if not points:
        raise ValueError("Municipality geometry has no coordinates")
    longitudes, latitudes = zip(*points)
    return [min(longitudes), min(latitudes), max(longitudes), max(latitudes)]


def materialize_municipality_boundaries(
    geojson_path: Path,
    registry_paths: list[Path],
    *,
    source_url: str,
    retrieved_at: datetime,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    content = geojson_path.read_text(encoding="utf-8")
    collection = json.loads(content)
    if collection.get("type") != "FeatureCollection":
        raise ValueError("Municipality boundaries must be a GeoJSON FeatureCollection")
    registered = set()
    for path in registry_paths:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            if record.get("record_type") == "municipality":
                code = str((record.get("payload") or {}).get("istat_code") or "")
                if len(code) == 6:
                    registered.add(code)
    source = SourceDocument(
        source_url,
        retrieved_at,
        content,
        publisher="Istituto nazionale di statistica (ISTAT)",
        parser="istat_2026_generalized_municipality_geojson",
        parser_version="0.1.0",
    )
    records = []
    seen = set()
    for feature in collection.get("features", []):
        properties = feature.get("properties") or {}
        code = str(properties.get("PRO_COM_T") or "").zfill(6)
        geometry = feature.get("geometry") or {}
        if code not in registered or code in seen:
            continue
        if geometry.get("type") not in {"Polygon", "MultiPolygon"}:
            raise ValueError(f"Unsupported geometry for municipality {code}")
        seen.add(code)
        records.append(make_record(
            record_type="municipality_boundary",
            natural_key=f"municipality-boundary:istat:{code}",
            payload={
                "municipality_ref": f"istat:{code}",
                "name": properties.get("COMUNE"),
                "geometry_geojson": geometry,
                "bbox": _bbox(geometry),
                "reference_date": "2026-01-01",
            },
            source=source,
            evidence_kind="json",
            evidence_selector=f"feature[PRO_COM_T='{code}']",
            evidence_quote=f"{properties.get('COMUNE')}: {code}",
            confidence="high",
        ))
    missing = sorted(registered - seen)
    unexpected = sorted(seen - registered)
    report = {
        "source_url": source_url,
        "retrieved_at": retrieved_at.isoformat(),
        "reference_date": "2026-01-01",
        "registered_municipalities": len(registered),
        "materialized_boundaries": len(records),
        "missing_boundaries": missing,
        "unexpected_boundaries": unexpected,
        "status": "pass" if not missing and not unexpected else "fail",
    }
    if report["status"] != "pass":
        raise ValueError(
            f"Municipality boundary coverage mismatch: {len(missing)} missing, "
            f"{len(unexpected)} unexpected"
        )
    return records, report


def _point_on_segment(
    longitude: float, latitude: float,
    left: list[float], right: list[float],
    *, epsilon: float = 1e-10,
) -> bool:
    cross = (
        (longitude - left[0]) * (right[1] - left[1])
        - (latitude - left[1]) * (right[0] - left[0])
    )
    if abs(cross) > epsilon:
        return False
    return (
        min(left[0], right[0]) - epsilon <= longitude
        <= max(left[0], right[0]) + epsilon
        and min(left[1], right[1]) - epsilon <= latitude
        <= max(left[1], right[1]) + epsilon
    )


def _ring_relation(
    longitude: float, latitude: float, ring: list[list[float]],
) -> str:
    inside = False
    if len(ring) < 3:
        return "outside"
    previous = ring[-1]
    for current in ring:
        if _point_on_segment(longitude, latitude, previous, current):
            return "boundary"
        if (current[1] > latitude) != (previous[1] > latitude):
            crossing = (
                (previous[0] - current[0])
                * (latitude - current[1])
                / (previous[1] - current[1])
                + current[0]
            )
            if longitude < crossing:
                inside = not inside
        previous = current
    return "inside" if inside else "outside"


def _polygon_contains(
    longitude: float, latitude: float, polygon: list[list[list[float]]],
) -> bool:
    if not polygon:
        return False
    outer = _ring_relation(longitude, latitude, polygon[0])
    if outer == "outside":
        return False
    for hole in polygon[1:]:
        relation = _ring_relation(longitude, latitude, hole)
        if relation == "inside":
            return False
    return True


def geometry_contains(
    geometry: dict[str, Any], longitude: float, latitude: float,
) -> bool:
    if geometry.get("type") == "Polygon":
        return _polygon_contains(longitude, latitude, geometry.get("coordinates", []))
    if geometry.get("type") == "MultiPolygon":
        return any(
            _polygon_contains(longitude, latitude, polygon)
            for polygon in geometry.get("coordinates", [])
        )
    return False
