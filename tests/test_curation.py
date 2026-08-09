from __future__ import annotations

import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from dovelobutto.curation import (
    matching_collection_streams,
    matching_delivery_channels,
    validate_waste_curation,
)
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
        self.assertEqual(10, report["alias_groups"])
        self.assertEqual(48, report["alias_members"])
        self.assertEqual(7, report["collection_streams"])
        self.assertEqual(9, report["delivery_channels"])
        self.assertEqual(5, report["hazard_material_profiles"])
        self.assertEqual(11, report["curated_concepts"])
        self.assertEqual(13, report["curated_search_terms"])
        self.assertEqual(13, report["eer_mappings"])
        self.assertEqual(22, report["eer_mapped_concepts"])
        self.assertEqual(2, report["stream_mappings"])
        self.assertEqual(2, report["stream_mapped_concepts"])
        self.assertEqual(3, report["disambiguation_groups"])
        self.assertEqual(3, report["disambiguation_triggers"])
        self.assertEqual(38, report["waste_classes"])
        self.assertEqual(81, report["waste_class_outcomes"])
        self.assertEqual(61, report["family_mappings"])
        self.assertEqual(0, report["alias_group_territorial_conflicts"])
        self.assertGreater(report["mapped_destination_assertions"], 1900)
        self.assertGreater(report["channel_mapped_destination_assertions"], 1700)
        self.assertGreater(report["multi_channel_destination_assertions"], 600)

    def test_cork_group_contains_the_livorno_catalog_variant(self) -> None:
        cork = next(
            group for group in self.register["alias_groups"]
            if group["group_id"] == "waste-alias:cork-stopper"
        )
        self.assertIn("waste:tappi-in-sughero", cork["member_concept_ids"])

    def test_mollusc_shell_group_keeps_specific_species_separate(self) -> None:
        group = next(
            group for group in self.register["alias_groups"]
            if group["group_id"] == "waste-alias:mollusc-shells"
        )
        self.assertIn("waste:guscio-dei-molluschi", group["member_concept_ids"])
        self.assertNotIn("waste:guscio-delle-ostriche", group["member_concept_ids"])
        self.assertIn("Murici", group["search_terms"])
        self.assertIn("Ostriche", group["search_terms"])

    def test_lead_and_resin_questions_cover_every_reviewed_branch(self) -> None:
        groups = {
            group["group_id"]: group
            for group in self.register["disambiguation_groups"]
        }
        self.assertEqual(
            {
                "waste:piombo-domestico",
                "waste:batteria-o-accumulatore-al-piombo",
                "waste:piombo-da-costruzione-demolizione",
                "waste:piombo-contaminato-pericoloso",
                "waste:residuo-metallurgia-piombo",
            },
            {option["concept_id"] for option in groups["waste-question:lead-form"]["options"]},
        )
        self.assertEqual(
            {
                "waste:resina-pericolosa",
                "waste:resina-non-pericolosa",
                "waste:imballaggio-contaminato-da-resina",
                "waste:resina-indurita",
            },
            {option["concept_id"] for option in groups["waste-question:resin-state"]["options"]},
        )
        mappings = {
            mapping["concept_ids"][0]: mapping["eer_code"]
            for mapping in self.register["eer_mappings"]
            if len(mapping["concept_ids"]) == 1
        }
        self.assertNotIn("waste:piombo-domestico", mappings)
        self.assertEqual("200133", mappings["waste:batteria-o-accumulatore-al-piombo"])
        self.assertNotIn("waste:piombo-da-costruzione-demolizione", mappings)
        self.assertEqual("170409", mappings["waste:piombo-contaminato-pericoloso"])
        self.assertEqual("100402", mappings["waste:residuo-metallurgia-piombo"])
        self.assertEqual("200127", mappings["waste:resina-pericolosa"])
        self.assertEqual("200128", mappings["waste:resina-non-pericolosa"])
        self.assertEqual("150110", mappings["waste:imballaggio-contaminato-da-resina"])

    def test_unknown_alias_member_is_rejected(self) -> None:
        register = copy.deepcopy(self.register)
        register["alias_groups"][0]["member_concept_ids"].append("waste:inesistente")
        with self.assertRaisesRegex(ValueError, "Unknown concept"):
            validate_waste_curation(register, self.catalog)

    def test_alias_group_requires_a_known_portable_class(self) -> None:
        register = copy.deepcopy(self.register)
        register["alias_groups"][0]["waste_class_id"] = "waste-class:inesistente"
        with self.assertRaisesRegex(ValueError, "requires a known waste class"):
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

    def test_channel_alias_cannot_have_two_meanings(self) -> None:
        register = copy.deepcopy(self.register)
        register["delivery_channels"][1]["aliases"].append("Centro di raccolta")
        with self.assertRaisesRegex(ValueError, "Channel alias.*belongs to both"):
            validate_waste_curation(register, self.catalog)

    def test_eer_mapping_requires_known_unique_concepts_and_valid_code(self) -> None:
        register = copy.deepcopy(self.register)
        register["eer_mappings"][0]["concept_ids"].append("waste:inesistente")
        with self.assertRaisesRegex(ValueError, "Unknown concept"):
            validate_waste_curation(register, self.catalog)
        register = copy.deepcopy(self.register)
        register["eer_mappings"][1]["eer_code"] = "20 01 36"
        with self.assertRaisesRegex(ValueError, "Invalid EER code"):
            validate_waste_curation(register, self.catalog)
        register = copy.deepcopy(self.register)
        register["eer_mappings"][1]["concept_ids"].append(
            register["eer_mappings"][0]["concept_ids"][0]
        )
        with self.assertRaisesRegex(ValueError, "unconditional EER mapping"):
            validate_waste_curation(register, self.catalog)

    def test_compound_destination_preserves_all_controlled_channels(self) -> None:
        matches = matching_delivery_channels(
            "Ecocentro - ritiro ingombranti", self.register["delivery_channels"],
        )
        self.assertEqual(
            ["channel:collection-centre", "channel:home-pickup"],
            [match["channel_id"] for match in matches],
        )
        self.assertEqual([], matching_delivery_channels(
            "Centro storico", self.register["delivery_channels"],
        ))

    def test_compound_instruction_identifies_stream_not_access_card(self) -> None:
        matches = matching_collection_streams(
            'Contenitore grigio per indifferenziata con Carta Smeraldo',
            self.register["collection_streams"],
        )
        self.assertEqual(
            ["stream:residual"],
            [match["stream_id"] for match in matches],
        )
        self.assertEqual([], matching_collection_streams(
            "Ritiro per carta catramata, lana di vetro e vetroresina",
            self.register["collection_streams"],
        ))

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
        self.assertIn(("delivery_channel", "channel:home-pickup"), entities)
        mapping = entities[("waste_eer_mapping", "eer-map:used-cooking-oil")]
        self.assertIn(("waste_concept", "waste:olio-alimentare-esausto"), mapping.dependencies)
        stream_mapping = entities[(
            "waste_stream_mapping", "stream-map:small-foam-residual",
        )]
        self.assertIn(("collection_stream", "stream:residual"), stream_mapping.dependencies)
        question = entities[(
            "waste_disambiguation_group", "waste-question:foam-size",
        )]
        self.assertIn(("waste_concept", "waste:gommapiuma"), question.dependencies)
        self.assertIn(("waste_concept", "waste:piombo"), entities)
        lead_question = entities[(
            "waste_disambiguation_group", "waste-question:lead-form",
        )]
        self.assertIn(("waste_concept", "waste:piombo"), lead_question.dependencies)

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
