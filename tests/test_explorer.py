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
            WORKSPACE / "outputs" / "sei-toscana-grosseto-01-report.json",
            WORKSPACE / "outputs" / "sei-toscana-municipalities.jsonl",
            datetime.fromisoformat("2026-08-06T09:00:00+02:00"),
        )

    def test_includes_complete_batch(self) -> None:
        self.assertEqual(10, len(self.dataset["municipalities"]))
        self.assertEqual(589, len(self.dataset["records"]))
        self.assertEqual(0, self.dataset["batch"]["pages_remaining"])
        self.assertEqual(3, self.dataset["batch"]["warnings"])

    def test_joins_reports_and_registry(self) -> None:
        grosseto = next(item for item in self.dataset["municipalities"] if item["name"] == "Grosseto")
        self.assertEqual("053011", grosseto["istat_code"])
        self.assertEqual(104, grosseto["records"])
        self.assertEqual(2, len(grosseto["warnings"]))
        self.assertEqual(1, len(grosseto["equivalent_pages"]))

    def test_writes_browser_script(self) -> None:
        with TemporaryDirectory() as temporary:
            destination = Path(temporary) / "data.js"
            write_explorer_dataset(destination, self.dataset)
            text = destination.read_text(encoding="utf-8")
            self.assertTrue(text.startswith("window.COMESIBUTTA_DATA = "))
            self.assertTrue(text.endswith(";\n"))


if __name__ == "__main__":
    unittest.main()
