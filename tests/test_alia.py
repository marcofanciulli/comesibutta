from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from dovelobutto.alia import build_junker_queries, materialize_alia


RETRIEVED_AT = datetime.fromisoformat("2026-08-06T23:00:00+02:00")


class AliaTests(unittest.TestCase):
    def test_builds_deduplicated_three_character_queries(self) -> None:
        catalog = {"concepts": [{"terms": ["Bottiglia di vetro", "Bottiglie"]}, {"terms": ["Carta"]}]}
        self.assertEqual(["bot", "car", "vet"], build_junker_queries(catalog))

    def test_materializes_waste_centres_hours_and_mobile_points(self) -> None:
        municipalities = [
            {"name": "Firenze", "istat_code": "048017", "source_slug": "firenze"},
            {"name": "Prato", "istat_code": "100005", "source_slug": "prato"},
        ]
        bundle = {
            "access": {}, "errors": [],
            "junker": {"queries": {"bot": [{"genericId": 2435, "desc": "Bottiglia di vetro"}]}, "details": {
                "2435": {"genericDesc": "Bottiglia di vetro", "bins": [{"binId": 2, "desc": "Imballaggi in vetro", "color": 8046520}]},
            }},
            "centres": [{"sapId": "394", "description": "ECOCENTRO FIRENZE", "address": "Via di prova", "municipality": "FIRENZE", "geometry": {"x": 11.2, "y": 43.7}}],
            "eco_trucks": [{"idGis": "178", "municipality": "FIRENZE", "streetName": "Piazza di prova", "locationDetails": "fronte 10", "geometry": {"x": 11.3, "y": 43.8}}],
            "centre_details": [
                {"extId": {"value": "394"}, "displayName": "ECOCENTRO FIRENZE", "cosaPuoiConferire": {"values": [{"name": "legno", "value": "carta%20e%20cartone"}]}, "tooltipCosaPuoiConferire": {"values": []}, "regoleAccesso": {"jsonValue": {"value": {"href": "/regole"}}}, "openingHours": {"jsonValue": [{"fields": {"day": {"value": "Lunedì"}, "openingTime1": {"value": "8:00"}, "closingTime1": {"value": "12:00"}}}]}},
                {"extId": {"value": "178"}, "displayName": "FIRENZE-PIAZZA DI PROVA", "cosaPuoiConferire": {"values": [{"name": "pile", "value": "pile"}]}, "openingHours": {"jsonValue": []}},
            ],
        }
        with TemporaryDirectory() as directory:
            report = materialize_alia(municipalities, bundle, RETRIEVED_AT, Path(directory))
            records = [json.loads(line) for line in (Path(directory) / "firenze-acquisition.jsonl").read_text(encoding="utf-8").splitlines()]
        types = {record["record_type"] for record in records}
        self.assertTrue({"waste_lookup", "collection_rule", "facility", "facility_access", "opening_period", "facility_acceptance", "collection_point", "pickup_service"}.issubset(types))
        opening = next(record for record in records if record["record_type"] == "opening_period")
        self.assertEqual("08:00", opening["payload"]["weekly_intervals"][0]["opens"])
        acceptance = next(record for record in records if record["record_type"] == "facility_acceptance")
        self.assertEqual("Carta e cartone", acceptance["payload"]["description_raw"])
        self.assertEqual(2, report["extraction"]["municipalities"])
        prato = next(item for item in report["extraction"]["municipality_reports"] if item["municipality"] == "Prato")
        self.assertEqual("facility_not_in_municipality", prato["warnings"][0]["code"])


if __name__ == "__main__":
    unittest.main()
