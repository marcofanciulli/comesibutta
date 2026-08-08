from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from dovelobutto.catalog import build_catalog_from_paths, build_waste_catalog, normalize_term


def waste(term: str, destination: str, instructions: str | None, municipality: str, url: str) -> dict:
    return {
        "record_type": "waste_lookup",
        "municipality_istat": municipality,
        "payload": {"term": term, "destination_raw": destination, "instructions_raw": instructions},
        "source": {
            "url": url,
            "content_sha256": "a" * 64,
            "publisher": "Gestore",
            "retrieved_at": "2026-08-06T20:00:00+02:00",
            "evidence": {"quote": f"{term}: {destination}"},
        },
    }


class WasteCatalogTest(unittest.TestCase):
    def test_normalizes_accents_case_and_punctuation(self) -> None:
        self.assertEqual("caffe in capsule", normalize_term(" Caffè, in CAPSULE "))

    def test_deduplicates_shared_sources_but_preserves_local_scope(self) -> None:
        records = [
            waste("Televisore", "CdR", "Categoria GEOFOR: RAEE | EER 200136: apparecchiature fuori uso", "050001", "https://example.test/rifiutario"),
            waste("TELEVISORE", "CdR", "Categoria GEOFOR: RAEE | EER 200136: apparecchiature fuori uso", "050002", "https://example.test/rifiutario"),
            waste("Televisore", "Centro di raccolta", None, "053014", "https://example.test/manciano"),
        ]
        catalog, report = build_waste_catalog(records, datetime.fromisoformat("2026-08-06T21:00:00+02:00"))
        concept = catalog["concepts"][0]
        self.assertEqual("waste:televisore", concept["concept_id"])
        self.assertEqual("source_consensus", concept["eer"]["status"])
        self.assertEqual("200136", concept["eer"]["candidates"][0]["code"])
        self.assertIsNone(concept["eer"]["candidates"][0]["hazardous"])
        self.assertEqual("not_checked", concept["eer"]["candidates"][0]["register_status"])
        self.assertEqual(2, concept["coverage"]["source_assertions"])
        self.assertEqual(["050001", "050002", "053014"], concept["coverage"]["municipalities"])
        self.assertEqual(2, len(concept["local_destinations"]))
        self.assertEqual(2, report["source_assertions"])

    def test_never_promotes_conflicting_eer_candidates(self) -> None:
        records = [
            waste("Oggetto", "CdR", "EER 200135: apparecchiature pericolose", "050001", "https://a.test"),
            waste("Oggetto", "CdR", "EER 200136: apparecchiature fuori uso", "050002", "https://b.test"),
        ]
        catalog, report = build_waste_catalog(records, datetime.fromisoformat("2026-08-06T21:00:00+02:00"))
        self.assertEqual("conflict", catalog["concepts"][0]["eer"]["status"])
        self.assertEqual(1, report["eer_conflicts"])

    def test_uses_explicit_source_category_for_hazard(self) -> None:
        records = [waste(
            "Amianto", "Ditte specializzate",
            "Categoria GEOFOR: Pericoloso | EER 170605: materiali da costruzione contenenti amianto",
            "050001", "https://example.test/rifiutario",
        )]
        catalog, _ = build_waste_catalog(records, datetime.fromisoformat("2026-08-06T21:00:00+02:00"))
        self.assertTrue(catalog["concepts"][0]["eer"]["candidates"][0]["hazardous"])

    def test_reads_shared_operator_guidance_for_known_municipalities(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            registry = root / "registry.jsonl"
            registry.write_text(json.dumps({"payload": {
                "istat_code": "053014", "source_slug": "manciano",
            }}) + "\n", encoding="utf-8")
            guidance = root / "operator-organico-guidance.jsonl"
            guidance.write_text(json.dumps(waste(
                "Tappi di sughero", "Organico", None, "053014",
                "https://example.test/organico",
            ) | {"payload": {
                "municipality_ref": "istat:053014",
                "term": "Tappi di sughero",
                "destination_raw": "Organico",
                "instructions_raw": None,
            }}) + "\n", encoding="utf-8")
            catalog, _ = build_catalog_from_paths(
                [root], [registry], datetime.fromisoformat("2026-08-08T14:00:00+02:00"),
            )
        self.assertEqual(1, len(catalog["concepts"]))
        destination = catalog["concepts"][0]["local_destinations"][0]
        self.assertEqual("Organico", destination["label"])
        self.assertEqual(["053014"], destination["municipality_istats"])


if __name__ == "__main__":
    unittest.main()
