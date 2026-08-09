from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from dovelobutto.destination_quality import DestinationQualityAudit
from dovelobutto.municipality_boundaries import (
    geometry_contains,
    materialize_municipality_boundaries,
)


class _FacilityService:
    def __init__(self, facilities):
        self.facilities = facilities

    def _resolve_facilities(self, *args, **kwargs):
        return self.facilities, []


class DestinationQualityTests(unittest.TestCase):
    def test_polygon_supports_holes_boundaries_and_multipolygons(self) -> None:
        polygon = {
            "type": "Polygon",
            "coordinates": [[
                [0, 0], [10, 0], [10, 10], [0, 10], [0, 0],
            ], [
                [4, 4], [6, 4], [6, 6], [4, 6], [4, 4],
            ]],
        }
        self.assertTrue(geometry_contains(polygon, 2, 2))
        self.assertFalse(geometry_contains(polygon, 5, 5))
        self.assertTrue(geometry_contains(polygon, 0, 5))
        multi = {"type": "MultiPolygon", "coordinates": [polygon["coordinates"]]}
        self.assertTrue(geometry_contains(multi, 2, 2))

    def test_boundary_materialization_requires_complete_registry_coverage(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            registry = root / "municipalities.jsonl"
            registry.write_text(json.dumps({
                "record_type": "municipality",
                "payload": {"istat_code": "048017"},
            }) + "\n", encoding="utf-8")
            geojson = root / "boundaries.geojson"
            geojson.write_text(json.dumps({
                "type": "FeatureCollection",
                "features": [{
                    "type": "Feature",
                    "properties": {"PRO_COM_T": "048017", "COMUNE": "Firenze"},
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [[[11, 43], [12, 43], [12, 44], [11, 44], [11, 43]]],
                    },
                }],
            }), encoding="utf-8")
            records, report = materialize_municipality_boundaries(
                geojson, [registry],
                source_url="https://example.test/boundaries.zip",
                retrieved_at=datetime.fromisoformat("2026-08-09T20:30:00+02:00"),
            )
        self.assertEqual("pass", report["status"])
        self.assertEqual(1, report["materialized_boundaries"])
        self.assertEqual(
            [11.0, 43.0, 12.0, 44.0], records[0]["payload"]["bbox"],
        )

    def test_verified_facility_omission_blocks_release(self) -> None:
        facility = {
            "id": "facility:one",
            "acceptance": {"status": "verified_description"},
        }
        audit = DestinationQualityAudit(
            _FacilityService([facility]),
            {"049007": {"name": "Cecina", "province_code": "LI", "ato_ref": "costa"}},
        )
        audit.observe(
            {
                "status": "resolved",
                "result": {
                    "destination_type": "special_case",
                    "facility": None,
                    "facility_alternatives": [],
                    "channel_services": [],
                    "delivery_channels": [{"channel_id": "channel:specialist-operator"}],
                    "unresolved_channels": [],
                    "eer": None,
                },
            },
            concept={"concept_id": "waste:test"},
            concept_id="waste:test",
            label="Test",
            municipality="049007",
            zone_id=None,
        )
        report = audit.report()
        self.assertFalse(report["summary"]["release_ready"])
        self.assertEqual(1, report["summary"]["blocking_issues"])
        self.assertEqual(
            "verified_facility_omitted", report["blocking_issues"][0]["code"],
        )

    def test_unpublished_specialist_service_is_reported_without_invention(self) -> None:
        audit = DestinationQualityAudit(
            _FacilityService([]),
            {"049007": {"name": "Cecina", "province_code": "LI", "ato_ref": "costa"}},
        )
        audit.observe(
            {
                "status": "resolved",
                "result": {
                    "destination_type": "special_case",
                    "facility": None,
                    "facility_alternatives": [],
                    "channel_services": [],
                    "delivery_channels": [{"channel_id": "channel:specialist-operator"}],
                    "unresolved_channels": [],
                    "eer": None,
                },
            },
            concept={"concept_id": "waste:test"},
            concept_id="waste:test",
            label="Test",
            municipality="049007",
            zone_id=None,
        )
        report = audit.report()
        self.assertTrue(report["summary"]["release_ready"])
        self.assertEqual(
            1,
            report["summary"]["categories"]["specialist_operator_only"][
                "concept_municipality_pairs"
            ],
        )


if __name__ == "__main__":
    unittest.main()
