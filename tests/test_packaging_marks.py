from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from dovelobutto.packaging_marks import build_packaging_material_register, write_json
from dovelobutto.sync import load_canonical_entities


WORKSPACE = Path(__file__).parents[1]
SOURCE_DIR = WORKSPACE / "data" / "sources" / "packaging-marks"


class PackagingMaterialRegisterTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.paths = {
            "transcription_path": SOURCE_DIR / "31997D0129-it.csv",
            "pdf_path": SOURCE_DIR / "31997D0129-it.pdf",
            "html_path": SOURCE_DIR / "31997D0129-it.html",
            "extracted_text_path": SOURCE_DIR / "31997D0129-it.txt",
        }
        cls.register, cls.report = build_packaging_material_register(
            **cls.paths,
            generated_at=datetime.fromisoformat("2026-08-07T18:00:00+02:00"),
        )
        cls.entries = {entry["numeric_code"]: entry for entry in cls.register["entries"]}

    def test_builds_every_official_numeric_slot(self) -> None:
        self.assertEqual(99, len(self.entries))
        self.assertEqual(31, self.report["assigned_codes"])
        self.assertEqual(68, self.report["unassigned_codes"])
        self.assertEqual(31, self.report["transcription_labels_verified"])

    def test_preserves_assigned_and_unassigned_codes(self) -> None:
        self.assertEqual("PET", self.entries[1]["abbreviation"])
        self.assertEqual("Polietilentereftalato", self.entries[1]["material_name"])
        self.assertEqual("unassigned", self.entries[7]["assignment_status"])
        self.assertIsNone(self.entries[7]["material_name"])

    def test_models_composite_abbreviation_as_a_rule(self) -> None:
        composite = self.entries[84]
        self.assertEqual("composite", composite["material_family"])
        self.assertEqual("C/{predominant_material_abbreviation}", composite["abbreviation_rule"])
        self.assertEqual("paper_cardboard", composite["predominant_family"])
        self.assertEqual(["Carta e cartone", "plastica", "alluminio"], composite["composition"])

    def test_material_codes_do_not_claim_a_disposal_destination(self) -> None:
        self.assertTrue(all(entry["disposal_semantics"] == "none" for entry in self.entries.values()))
        self.assertEqual(0, self.report["entries_with_disposal_semantics"])

    def test_rejects_a_transcription_in_the_wrong_family(self) -> None:
        with TemporaryDirectory() as temporary:
            transcription = Path(temporary) / "invalid.csv"
            transcription.write_text(
                self.paths["transcription_path"].read_text(encoding="utf-8").replace(
                    "1,plastic,", "1,glass,", 1,
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "belongs to plastic"):
                build_packaging_material_register(
                    transcription,
                    self.paths["pdf_path"],
                    self.paths["html_path"],
                    self.paths["extracted_text_path"],
                    datetime.fromisoformat("2026-08-07T18:00:00+02:00"),
                )

    def test_register_enters_the_canonical_dataset(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            register_path = root / "packaging-material-register.json"
            write_json(register_path, self.register)
            input_dir = root / "inputs"
            input_dir.mkdir()
            registry = root / "registry.jsonl"
            registry.write_text("", encoding="utf-8")
            entities = load_canonical_entities(
                [input_dir], [registry], packaging_material_register_path=register_path,
            )
        self.assertEqual(99, len(entities))
        self.assertIn(("packaging_material_mark", "packaging-material:eu-97-129:84"), entities)

    def test_contract_files_are_valid_json(self) -> None:
        for path in (
            WORKSPACE / "schemas" / "packaging-material-register.schema.json",
            WORKSPACE / "schemas" / "visual-recognition-observation.schema.json",
            WORKSPACE / "schemas" / "vision-model-contract.schema.json",
            WORKSPACE / "examples" / "vision-model-contract.json",
        ):
            self.assertIsInstance(json.loads(path.read_text(encoding="utf-8")), dict)


if __name__ == "__main__":
    unittest.main()
