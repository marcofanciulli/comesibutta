from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from dovelobutto.cli import main
from dovelobutto.routing_coverage import build_routing_coverage


GENERATED_AT = datetime.fromisoformat("2026-08-09T01:00:00+02:00")


class RoutingCoverageTests(unittest.TestCase):
    def test_every_concept_is_present_and_unclassified_blocks_release(self) -> None:
        catalog = {
            "generated_at": GENERATED_AT.isoformat(),
            "concepts": [
                {
                    "concept_id": "waste:carta",
                    "preferred_label": "Carta",
                    "local_destinations": [{"label": "Carta e cartone"}],
                    "eer": {"candidates": []},
                },
                {
                    "concept_id": "waste:ignoto",
                    "preferred_label": "Ignoto",
                    "local_destinations": [],
                    "eer": {"candidates": []},
                },
            ],
        }
        curation = {
            "generated_at": GENERATED_AT.isoformat(),
            "curated_concepts": [],
            "collection_streams": [{
                "stream_id": "stream:paper",
                "aliases": ["Carta e cartone"],
            }],
            "delivery_channels": [],
            "eer_mappings": [],
            "stream_mappings": [],
            "disambiguation_groups": [],
        }

        report = build_routing_coverage(
            catalog, curation, generated_at=GENERATED_AT,
        )

        self.assertEqual(2, report["summary"]["concepts"])
        self.assertEqual(0, report["summary"]["classified"])
        self.assertEqual(2, report["summary"]["unclassified"])
        self.assertFalse(report["summary"]["release_ready"])
        paper = next(
            entry for entry in report["entries"]
            if entry["concept_id"] == "waste:carta"
        )
        self.assertTrue(paper["local_route_observed"])
        self.assertFalse(paper["portable_classification"])

    def test_reviewed_question_is_a_complete_classification_path(self) -> None:
        catalog = {
            "generated_at": GENERATED_AT.isoformat(),
            "concepts": [{
                "concept_id": "waste:bicchiere",
                "preferred_label": "Bicchiere",
                "local_destinations": [],
                "eer": {"candidates": []},
            }],
        }
        curation = {
            "generated_at": GENERATED_AT.isoformat(),
            "curated_concepts": [],
            "collection_streams": [],
            "delivery_channels": [],
            "eer_mappings": [],
            "stream_mappings": [],
            "disambiguation_groups": [{
                "group_id": "waste-question:glass-material",
                "trigger_concept_ids": ["waste:bicchiere"],
                "options": [],
            }],
        }

        report = build_routing_coverage(
            catalog, curation, generated_at=GENERATED_AT,
        )

        self.assertTrue(report["summary"]["release_ready"])
        self.assertEqual("classified", report["entries"][0]["status"])

    def test_production_publish_is_blocked_by_incomplete_routing(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            catalog = root / "catalog.json"
            catalog.write_text(json.dumps({
                "generated_at": GENERATED_AT.isoformat(),
                "concepts": [{
                    "concept_id": "waste:ignoto",
                    "preferred_label": "Ignoto",
                    "local_destinations": [],
                    "eer": {"candidates": []},
                }],
            }), encoding="utf-8")
            curation = root / "curation.json"
            curation.write_text(json.dumps({
                "generated_at": GENERATED_AT.isoformat(),
                "curated_concepts": [],
                "collection_streams": [],
                "delivery_channels": [],
                "eer_mappings": [],
                "stream_mappings": [],
                "disambiguation_groups": [],
                "family_mappings": [],
            }), encoding="utf-8")
            with self.assertRaisesRegex(
                ValueError, "Canonical waste routing is incomplete",
            ):
                main([
                    "publish-data-release",
                    "--input-dir", str(root),
                    "--registry", str(root / "registry.jsonl"),
                    "--catalog", str(catalog),
                    "--waste-curation-register", str(curation),
                    "--database", str(root / "publisher.sqlite"),
                    "--artifact-dir", str(root / "artifacts"),
                    "--manifest", str(root / "manifest.json"),
                    "--revision", "1",
                    "--generated-at", GENERATED_AT.isoformat(),
                    "--private-key", str(root / "private.pem"),
                    "--key-id", "test",
                    "--base-url", "https://example.test/",
                    "--report", str(root / "release-report.json"),
                ])


if __name__ == "__main__":
    unittest.main()
