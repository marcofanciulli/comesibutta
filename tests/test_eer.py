from __future__ import annotations

from datetime import datetime
from pathlib import Path
import unittest

from dovelobutto.eer import build_eer_register, parse_consolidated_eer


WORKSPACE = Path(__file__).parents[1]
SOURCE_DIR = WORKSPACE / "data" / "sources" / "eer"


class EerRegisterTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.base_path = SOURCE_DIR / "02000D0532-20231206-it.html"
        cls.register, cls.report = build_eer_register(
            cls.base_path,
            SOURCE_DIR / "32025D0934-it.html",
            SOURCE_DIR / "32025D0934R01-it.html",
            datetime.fromisoformat("2026-08-06T22:30:00+02:00"),
        )
        cls.entries = {entry["code"]: entry for entry in cls.register["entries"]}
        cls.retired = {
            entry["code"]: entry for entry in cls.register["retired_entries"]
        }

    def test_parses_complete_consolidated_register(self) -> None:
        base = parse_consolidated_eer(self.base_path.read_text(encoding="utf-8"))
        self.assertEqual(20, len(base["chapters"]))
        self.assertEqual(111, len(base["subchapters"]))
        self.assertEqual(842, len(base["entries"]))

    def test_applies_corrected_effective_date(self) -> None:
        self.assertEqual("2026-12-09", self.register["valid_from"])
        self.assertEqual("future", self.register["status_at_generation"])

    def test_applies_battery_amendment(self) -> None:
        self.assertEqual(880, len(self.entries))
        self.assertTrue(self.entries["160607"]["hazardous"])
        self.assertIn("litio", self.entries["160607"]["title"])
        self.assertTrue(self.entries["200143"]["hazardous"])
        self.assertFalse(self.entries["200144"]["title"].endswith("»."))
        self.assertIn("200133", self.retired)
        self.assertIn("200134", self.retired)
        self.assertEqual("2026-12-08", self.retired["200133"]["valid_to"])

    def test_expands_cross_references(self) -> None:
        wood = self.entries["200138"]
        self.assertEqual("legno contenente sostanze pericolose", wood["references"][0]["title"])
        self.assertIn(
            "legno contenente sostanze pericolose (20 01 37)",
            wood["title_expanded"],
        )
        self.assertEqual(1, self.report["unresolved_references"])
        self.assertEqual(
            {
                "entry_code": "110112",
                "entry_title": "soluzioni acquose di lavaggio, diverse da quelle di cui alla voce 10 01 11",
                "referenced_code": "100111",
            },
            self.report["unresolved_reference_details"][0],
        )

    def test_preserves_hazardous_flag(self) -> None:
        self.assertTrue(self.entries["200135"]["hazardous"])
        self.assertFalse(self.entries["200136"]["hazardous"])


if __name__ == "__main__":
    unittest.main()
