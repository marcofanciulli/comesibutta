from datetime import datetime
from pathlib import Path
import unittest

from dovelobutto.registry import (
    extract_ato_centro_municipality_registry,
    read_istat_municipalities,
)


WORKSPACE = Path(__file__).parents[1]


class AtoCentroRegistryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.records, cls.warnings = extract_ato_centro_municipality_registry(
            datetime.fromisoformat("2026-08-06T22:30:00+02:00"),
            read_istat_municipalities(
                WORKSPACE / "data" / "sources" / "istat" / "toscana-comuni-2026-02-21.csv"
            ),
        )

    def test_matches_current_official_scope(self) -> None:
        self.assertEqual(65, len(self.records))
        self.assertEqual([], self.warnings)
        counts: dict[str, int] = {}
        for record in self.records:
            province = record["payload"]["province_code"]
            counts[province] = counts.get(province, 0) + 1
        self.assertEqual({"FI": 38, "PO": 7, "PT": 20}, counts)

    def test_excludes_the_three_emilia_romagna_ato_municipalities(self) -> None:
        names = {record["payload"]["name"] for record in self.records}
        self.assertTrue({"Firenzuola", "Marradi", "Palazzuolo sul Senio"}.isdisjoint(names))

    def test_uses_current_aliaestra_pages(self) -> None:
        firenze = next(record for record in self.records if record["payload"]["name"] == "Firenze")
        self.assertEqual("plures-alia", firenze["payload"]["operator_ref"])
        self.assertEqual(
            "https://aliaestra.it/ambiente/comuni/firenze",
            firenze["payload"]["homepage_url"],
        )
        self.assertIn("dove-lo-porto", firenze["payload"]["service_urls"]["facilities"][0])


if __name__ == "__main__":
    unittest.main()
