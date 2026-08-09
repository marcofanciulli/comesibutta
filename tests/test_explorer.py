from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from dovelobutto.explorer import build_explorer_dataset, write_explorer_dataset


WORKSPACE = Path(__file__).parents[1]


class ExplorerDatasetTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dataset = build_explorer_dataset(
            WORKSPACE / "outputs" / "sei-toscana",
            [
                WORKSPACE / "outputs" / "sei-toscana-grosseto-01-report.json",
                WORKSPACE / "outputs" / "sei-toscana-grosseto-02-report.json",
                WORKSPACE / "outputs" / "sei-toscana-arezzo-report.json",
                WORKSPACE / "outputs" / "sei-toscana-siena-report.json",
                WORKSPACE / "outputs" / "sei-toscana-livorno-ato-sud-report.json",
            ],
            WORKSPACE / "outputs" / "sei-toscana-municipalities.jsonl",
            datetime.fromisoformat("2026-08-06T09:00:00+02:00"),
        )

    def test_includes_complete_batch(self) -> None:
        self.assertEqual(104, len(self.dataset["municipalities"]))
        self.assertEqual(5090, len(self.dataset["records"]))
        self.assertEqual(0, self.dataset["batch"]["pages_remaining"])
        self.assertEqual(4, self.dataset["batch"]["warnings"])
        self.assertEqual(8, len(self.dataset["batch"]["errors"]))

    def test_exposes_ato_and_province_filters(self) -> None:
        self.assertEqual([{
            "id": "ato-toscana-sud",
            "name": "ATO Toscana Sud",
            "provinces": ["AR", "GR", "LI", "SI"],
        }], self.dataset["atos"])
        counts = {}
        for municipality in self.dataset["municipalities"]:
            counts[municipality["province_code"]] = counts.get(municipality["province_code"], 0) + 1
            self.assertEqual("ato-toscana-sud", municipality["ato_ref"])
        self.assertEqual({"AR": 35, "GR": 28, "LI": 6, "SI": 35}, counts)

    def test_joins_reports_and_registry(self) -> None:
        grosseto = next(item for item in self.dataset["municipalities"] if item["name"] == "Grosseto")
        self.assertEqual("053011", grosseto["istat_code"])
        self.assertEqual(105, grosseto["records"])
        self.assertEqual(0, len(grosseto["warnings"]))
        self.assertEqual(1, len(grosseto["equivalent_pages"]))

    def test_writes_browser_script(self) -> None:
        with TemporaryDirectory() as temporary:
            destination = Path(temporary) / "data.js"
            write_explorer_dataset(destination, self.dataset)
            text = destination.read_text(encoding="utf-8")
            self.assertTrue(text.startswith("window.COMESIBUTTA_DATA = "))
            self.assertTrue(text.endswith(";\n"))

    def test_includes_empty_catalog_when_not_supplied(self) -> None:
        self.assertEqual([], self.dataset["catalog"]["concepts"])

    def test_includes_registry_only_ato_costa_municipalities(self) -> None:
        dataset = build_explorer_dataset(
            WORKSPACE / "outputs" / "sei-toscana",
            [
                WORKSPACE / "outputs" / "sei-toscana-grosseto-01-report.json",
                WORKSPACE / "outputs" / "sei-toscana-grosseto-02-report.json",
                WORKSPACE / "outputs" / "sei-toscana-arezzo-report.json",
                WORKSPACE / "outputs" / "sei-toscana-siena-report.json",
                WORKSPACE / "outputs" / "sei-toscana-livorno-ato-sud-report.json",
            ],
            [
                WORKSPACE / "outputs" / "sei-toscana-municipalities.jsonl",
                WORKSPACE / "outputs" / "ato-toscana-costa-municipalities.jsonl",
            ],
            datetime.fromisoformat("2026-08-06T15:00:00+02:00"),
        )
        self.assertEqual(204, len(dataset["municipalities"]))
        self.assertEqual(104, dataset["batch"]["municipalities_acquired"])
        self.assertEqual(204, dataset["batch"]["municipalities_registered"])
        self.assertEqual(
            ["ato-toscana-costa", "ato-toscana-sud"],
            [ato["id"] for ato in dataset["atos"]],
        )
        livorno = next(item for item in dataset["municipalities"] if item["name"] == "Livorno")
        self.assertEqual("registry_only", livorno["acquisition_status"])
        self.assertEqual("AAMPS S.p.A.", livorno["local_operator_name"])

    def test_includes_acquired_esa_municipalities_and_waste_lookup(self) -> None:
        dataset = build_explorer_dataset(
            [
                WORKSPACE / "outputs" / "sei-toscana",
                WORKSPACE / "outputs" / "ato-toscana-costa",
            ],
            [
                WORKSPACE / "outputs" / "sei-toscana-grosseto-01-report.json",
                WORKSPACE / "outputs" / "sei-toscana-grosseto-02-report.json",
                WORKSPACE / "outputs" / "sei-toscana-arezzo-report.json",
                WORKSPACE / "outputs" / "sei-toscana-siena-report.json",
                WORKSPACE / "outputs" / "sei-toscana-livorno-ato-sud-report.json",
                WORKSPACE / "outputs" / "ato-toscana-costa-esa-report.json",
                WORKSPACE / "outputs" / "ato-toscana-costa-rea-report.json",
                WORKSPACE / "outputs" / "ato-toscana-costa-aamps-report.json",
                WORKSPACE / "outputs" / "ato-toscana-costa-geofor-report.json",
            ],
            [
                WORKSPACE / "outputs" / "sei-toscana-municipalities.jsonl",
                WORKSPACE / "outputs" / "ato-toscana-costa-municipalities.jsonl",
            ],
            datetime.fromisoformat("2026-08-06T16:00:00+02:00"),
            WORKSPACE / "outputs" / "waste-catalog.json",
            WORKSPACE / "outputs" / "eer-register.json",
        )
        self.assertEqual(154, dataset["batch"]["municipalities_acquired"])
        self.assertEqual(25501, len(dataset["records"]))
        self.assertEqual(3484, len(dataset["catalog"]["concepts"]))
        self.assertEqual(880, len(dataset["eer_register"]["entries"]))
        self.assertEqual("2026-12-09", dataset["eer_register"]["valid_from"])
        capoliveri = next(item for item in dataset["municipalities"] if item["name"] == "Capoliveri")
        self.assertEqual(292, capoliveri["records_by_type"]["waste_lookup"])
        self.assertEqual(2, capoliveri["records_by_type"]["facility"])
        self.assertEqual(4, capoliveri["records_by_type"]["opening_period"])
        self.assertEqual(31, capoliveri["records_by_type"]["facility_acceptance"])
        tetrapak = next(
            record for record in dataset["records"]
            if record["municipality_istat"] == "049004"
            and record["record_type"] == "waste_lookup"
            and record["payload"]["term"] == "Tetrapak"
        )
        self.assertIn("plastica e metallo", tetrapak["payload"]["destination_raw"].lower())
        bibbona = next(item for item in dataset["municipalities"] if item["name"] == "Bibbona")
        self.assertEqual(190, bibbona["records_by_type"]["waste_lookup"])
        self.assertEqual(14, bibbona["records_by_type"]["collection_schedule"])
        casale = next(item for item in dataset["municipalities"] if item["name"] == "Casale Marittimo")
        self.assertEqual(2, casale["records_by_type"]["collection_schedule"])
        orciano = next(item for item in dataset["municipalities"] if item["name"] == "Orciano Pisano")
        self.assertEqual(1, orciano["records_by_type"]["collection_point"])
        self.assertEqual(1, orciano["records_by_type"]["collection_schedule"])
        self.assertEqual(2, len(bibbona["warnings"]))
        self.assertEqual(1, bibbona["records_by_type"]["opening_period"])
        self.assertEqual(15, bibbona["records_by_type"]["facility_acceptance"])
        livorno = next(item for item in dataset["municipalities"] if item["name"] == "Livorno")
        self.assertEqual(406, livorno["records_by_type"]["waste_lookup"])
        self.assertEqual(1, len(livorno["warnings"]))
        self.assertEqual("collection_rules_not_municipality_wide", livorno["warnings"][0]["code"])
        bientina = next(item for item in dataset["municipalities"] if item["name"] == "Bientina")
        self.assertEqual(388, bientina["records_by_type"]["waste_lookup"])
        self.assertEqual(5, bientina["records_by_type"]["collection_rule"])
        peccioli = next(item for item in dataset["municipalities"] if item["name"] == "Peccioli")
        self.assertEqual("acquired", peccioli["acquisition_status"])
        self.assertEqual(388, peccioli["records_by_type"]["waste_lookup"])
        self.assertEqual("pending_subentry", peccioli["assignment_status"])

    def test_deduplicates_shared_ato_centro_waste_only_in_browser_bundle(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            registry = root / "registry.jsonl"
            registry.write_text("\n".join(json.dumps({"payload": {
                "name": name, "istat_code": istat, "source_slug": slug,
                "ato_ref": "ato-toscana-centro", "province_code": "FI",
                "operator_ref": "plures-alia", "local_operator_ref": "plures-alia",
            }}) for name, istat, slug in (("Uno", "048901", "uno"), ("Due", "048902", "due"))) + "\n", encoding="utf-8")
            for slug, istat in (("uno", "048901"), ("due", "048902")):
                records = [
                    {"record_type": "waste_lookup", "record_id": f"waste-{istat}", "payload": {"term": "Bottiglia"}},
                    {"record_type": "service_zone", "record_id": f"zone-{istat}", "payload": {"municipality_ref": f"istat:{istat}"}},
                ]
                (root / f"{slug}-acquisition.jsonl").write_text("\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8")
            report = root / "report.json"
            report.write_text(json.dumps({
                "observed_at": "2026-08-06T23:00:00+02:00", "pages_checked": 1,
                "pages_remaining": 0, "errors": [], "extraction": {
                    "municipality_reports": [
                        {"istat_code": istat, "records_by_type": {"waste_lookup": 1, "service_zone": 1}, "pages_available": 1, "pages_materialized": 1, "warnings": [], "equivalent_pages": []}
                        for istat in ("048901", "048902")
                    ]
                },
            }), encoding="utf-8")
            dataset = build_explorer_dataset(root, report, registry, datetime.fromisoformat("2026-08-06T23:30:00+02:00"))
        self.assertEqual(4, dataset["batch"]["records"])
        self.assertEqual(3, len(dataset["records"]))
        shared = [record for record in dataset["records"] if record.get("shared_ato_ref")]
        self.assertEqual(1, len(shared))
        self.assertEqual("ato-toscana-centro", shared[0]["shared_ato_ref"])

    def test_exposes_extra_regional_atos_only_for_tuscan_municipalities(self) -> None:
        dataset = build_explorer_dataset(
            WORKSPACE / "outputs" / "toscana-boundary",
            WORKSPACE / "outputs" / "toscana-boundary-report.json",
            WORKSPACE / "outputs" / "toscana-boundary-municipalities.jsonl",
            datetime.fromisoformat("2026-08-07T13:00:00+02:00"),
        )
        self.assertEqual(4, len(dataset["municipalities"]))
        self.assertEqual([
            {"id": "ato-emilia-romagna-bologna", "name": "ATO Emilia-Romagna - bacino Bologna", "provinces": ["FI"]},
            {"id": "ato-marche-1-pesaro-urbino", "name": "ATO 1 Marche - Pesaro e Urbino", "provinces": ["AR"]},
        ], dataset["atos"])
        sestino = next(item for item in dataset["municipalities"] if item["name"] == "Sestino")
        self.assertEqual(4, len(sestino["warnings"]))
        self.assertEqual(1, sestino["records_by_type"]["pickup_service"])


if __name__ == "__main__":
    unittest.main()
