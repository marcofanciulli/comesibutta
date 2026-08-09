from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from dovelobutto.cli import main
from dovelobutto.routing_coverage import build_routing_coverage


GENERATED_AT = datetime.fromisoformat("2026-08-09T01:00:00+02:00")


class RoutingCoverageTests(unittest.TestCase):
    def test_current_catalog_has_complete_portable_routing(self) -> None:
        root = Path(__file__).resolve().parents[1]
        catalog = json.loads(
            (root / "outputs/waste-catalog.json").read_text(encoding="utf-8")
        )
        curation = json.loads(
            (root / "data/curation/waste-curation-v1.json").read_text(
                encoding="utf-8",
            )
        )

        report = build_routing_coverage(
            catalog, curation, generated_at=GENERATED_AT,
        )

        self.assertEqual(3495, report["summary"]["concepts"])
        self.assertEqual(3495, report["summary"]["classified"])
        self.assertEqual(10, report["summary"]["alias_groups"])
        self.assertEqual(10, report["summary"]["classified_alias_groups"])
        self.assertEqual(0, report["summary"]["incomplete"])
        self.assertTrue(report["summary"]["release_ready"])

    def test_alias_without_portable_class_blocks_release(self) -> None:
        catalog = {
            "generated_at": GENERATED_AT.isoformat(),
            "concepts": [],
        }
        curation = {
            "generated_at": GENERATED_AT.isoformat(),
            "alias_groups": [{
                "group_id": "waste-alias:unknown",
                "preferred_label": "Oggetto sconosciuto",
                "member_concept_ids": [],
            }],
            "waste_classes": [],
        }

        report = build_routing_coverage(
            catalog, curation, generated_at=GENERATED_AT,
        )

        self.assertEqual(1, report["summary"]["incomplete_alias_groups"])
        self.assertFalse(report["summary"]["release_ready"])

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

    def test_family_destination_is_not_reported_as_unmapped(self) -> None:
        catalog = {
            "generated_at": GENERATED_AT.isoformat(),
            "concepts": [{
                "concept_id": "waste:mobile",
                "preferred_label": "Mobile",
                "normalized_term": "mobile",
                "local_destinations": [{"label": "INGOMBRANTI"}],
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
            "disambiguation_groups": [],
            "waste_classes": [{
                "class_id": "waste-class:bulky",
                "eer_codes": ["200307"],
            }],
            "family_mappings": [{
                "mapping_id": "family-map:bulky",
                "class_id": "waste-class:bulky",
                "destination_aliases": ["INGOMBRANTI"],
            }],
        }

        report = build_routing_coverage(
            catalog, curation, generated_at=GENERATED_AT,
        )

        self.assertEqual("classified", report["entries"][0]["status"])
        self.assertEqual([], report["entries"][0]["unmapped_destinations"])
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

    def test_production_publish_is_blocked_by_incomplete_territorial_coverage(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            routing_report = {
                "summary": {
                    "release_ready": True, "incomplete": 0, "concepts": 0,
                },
            }
            territorial_report = {
                "summary": {
                    "release_ready": False,
                    "failures": 1,
                    "near_duplicate_review_candidates": 0,
                },
                "dataset_revision": 1,
                "destination_quality": {
                    "summary": {"release_ready": True, "blocking_issues": 0},
                    "method": {}, "categories": {}, "territories": [],
                    "blocking_issues": [],
                },
            }
            with (
                patch(
                    "dovelobutto.routing_coverage.build_routing_coverage_paths",
                    return_value=routing_report,
                ),
                patch("dovelobutto.routing_coverage.write_routing_coverage"),
                patch("dovelobutto.cli.load_canonical_entities", return_value={}),
                patch(
                    "dovelobutto.query_coverage.audit_query_coverage_path",
                    return_value=territorial_report,
                ),
                patch("dovelobutto.query_coverage.write_coverage_report"),
            ):
                with self.assertRaisesRegex(
                    ValueError, "Territorial query coverage is incomplete",
                ):
                    main([
                        "publish-data-release",
                        "--input-dir", str(root),
                        "--registry", str(root / "registry.jsonl"),
                        "--catalog", str(root / "catalog.json"),
                        "--waste-curation-register", str(root / "curation.json"),
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
