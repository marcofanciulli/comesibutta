from __future__ import annotations

import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from dovelobutto.curation import validate_waste_curation
from dovelobutto.sync import load_canonical_entities


ROOT = Path(__file__).resolve().parents[1]


class WasteCurationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.register = json.loads(
            (ROOT / "data/curation/waste-curation-v1.json").read_text(encoding="utf-8")
        )
        cls.catalog = json.loads(
            (ROOT / "outputs/waste-catalog.json").read_text(encoding="utf-8")
        )

    def test_reviewed_register_matches_the_current_catalog(self) -> None:
        report = validate_waste_curation(self.register, self.catalog)
        self.assertEqual(3, report["alias_groups"])
        self.assertEqual(29, report["alias_members"])
        self.assertEqual(7, report["collection_streams"])
        self.assertEqual(0, report["alias_group_territorial_conflicts"])
        self.assertGreater(report["mapped_destination_assertions"], 1900)

    def test_unknown_alias_member_is_rejected(self) -> None:
        register = copy.deepcopy(self.register)
        register["alias_groups"][0]["member_concept_ids"].append("waste:inesistente")
        with self.assertRaisesRegex(ValueError, "Unknown concept"):
            validate_waste_curation(register, self.catalog)

    def test_one_concept_cannot_belong_to_two_groups(self) -> None:
        register = copy.deepcopy(self.register)
        register["alias_groups"][1]["member_concept_ids"].append(
            register["alias_groups"][0]["member_concept_ids"][0]
        )
        with self.assertRaisesRegex(ValueError, "belongs to both"):
            validate_waste_curation(register, self.catalog)

    def test_stream_alias_cannot_have_two_meanings(self) -> None:
        register = copy.deepcopy(self.register)
        register["collection_streams"][1]["aliases"].append("Organico")
        with self.assertRaisesRegex(ValueError, "belongs to both"):
            validate_waste_curation(register, self.catalog)

    def test_search_term_cannot_belong_to_two_groups(self) -> None:
        register = copy.deepcopy(self.register)
        register["alias_groups"][1]["search_terms"].append(
            register["alias_groups"][0]["search_terms"][0]
        )
        with self.assertRaisesRegex(ValueError, "Search term.*belongs to both"):
            validate_waste_curation(register, self.catalog)

    def test_register_enters_the_synchronized_dataset_with_dependencies(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = root / "inputs"
            inputs.mkdir()
            registry = root / "registry.jsonl"
            registry.write_text("", encoding="utf-8")
            catalog_path = root / "catalog.json"
            catalog_path.write_text(
                json.dumps(self.catalog, ensure_ascii=False), encoding="utf-8",
            )
            curation_path = root / "curation.json"
            curation_path.write_text(
                json.dumps(self.register, ensure_ascii=False), encoding="utf-8",
            )
            entities = load_canonical_entities(
                [inputs], [registry], catalog_path=catalog_path,
                waste_curation_register_path=curation_path,
            )
        group = entities[("waste_alias_group", "waste-alias:beverage-carton")]
        self.assertEqual(18, len(group.dependencies))
        self.assertIn(("collection_stream", "stream:organic"), entities)

    def test_schema_and_generated_report_are_machine_readable(self) -> None:
        schema = json.loads(
            (ROOT / "schemas/waste-curation-register.schema.json").read_text(encoding="utf-8")
        )
        report = json.loads(
            (ROOT / "outputs/waste-curation-report.json").read_text(encoding="utf-8")
        )
        self.assertEqual("object", schema["type"])
        self.assertEqual(self.register["register_id"], report["register_id"])


if __name__ == "__main__":
    unittest.main()
