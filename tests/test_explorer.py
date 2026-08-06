from __future__ import annotations

from datetime import datetime
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
        self.assertEqual(153, dataset["batch"]["municipalities_acquired"])
        self.assertEqual(24386, len(dataset["records"]))
        self.assertEqual(818, len(dataset["catalog"]["concepts"]))
        self.assertEqual(880, len(dataset["eer_register"]["entries"]))
        self.assertEqual("2026-12-09", dataset["eer_register"]["valid_from"])
        capoliveri = next(item for item in dataset["municipalities"] if item["name"] == "Capoliveri")
        self.assertEqual(292, capoliveri["records_by_type"]["waste_lookup"])
        tetrapak = next(
            record for record in dataset["records"]
            if record["municipality_istat"] == "049004"
            and record["record_type"] == "waste_lookup"
            and record["payload"]["term"] == "Tetrapak"
        )
        self.assertIn("plastica e metallo", tetrapak["payload"]["destination_raw"].lower())
        bibbona = next(item for item in dataset["municipalities"] if item["name"] == "Bibbona")
        self.assertEqual(190, bibbona["records_by_type"]["waste_lookup"])
        self.assertEqual(2, len(bibbona["warnings"]))
        self.assertEqual(1, bibbona["records_by_type"]["opening_period"])
        self.assertEqual(15, bibbona["records_by_type"]["facility_acceptance"])
        livorno = next(item for item in dataset["municipalities"] if item["name"] == "Livorno")
        self.assertEqual(125, livorno["records_by_type"]["waste_lookup"])
        self.assertEqual(5, len(livorno["warnings"]))
        bientina = next(item for item in dataset["municipalities"] if item["name"] == "Bientina")
        self.assertEqual(388, bientina["records_by_type"]["waste_lookup"])
        self.assertEqual(5, bientina["records_by_type"]["collection_rule"])
        peccioli = next(item for item in dataset["municipalities"] if item["name"] == "Peccioli")
        self.assertEqual("registry_only", peccioli["acquisition_status"])
        self.assertEqual("pending_subentry", peccioli["assignment_status"])


if __name__ == "__main__":
    unittest.main()
