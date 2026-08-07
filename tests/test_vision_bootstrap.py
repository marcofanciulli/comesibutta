from __future__ import annotations

import hashlib
import json
from pathlib import Path
import unittest

from dovelobutto.vision_corpus import validate_vision_corpus


WORKSPACE = Path(__file__).parents[1]
TAXONOMY = WORKSPACE / "data" / "vision" / "taxonomy-v1.json"
MANIFEST = WORKSPACE / "outputs" / "vision-bootstrap-manifest.json"
REPORT = WORKSPACE / "outputs" / "vision-bootstrap-report.json"
SOURCES = WORKSPACE / "data" / "sources" / "packaging-labeling"


class VisionBootstrapTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        cls.report = json.loads(REPORT.read_text(encoding="utf-8"))

    def test_manifest_is_valid_and_has_expected_counts(self) -> None:
        validation = validate_vision_corpus(MANIFEST, TAXONOMY)
        self.assertEqual(206, validation["assets"])
        self.assertEqual(186, validation["annotations"])
        self.assertEqual(170, validation["split_counts"]["train"])
        self.assertEqual(36, validation["split_counts"]["validation"])
        self.assertEqual(0, validation["split_counts"]["test"])
        self.assertFalse(validation["release_evaluation_ready"])

    def test_reference_pages_cover_the_material_examples(self) -> None:
        references = [
            asset for asset in self.manifest["assets"]
            if asset["content_origin"] == "document_crop"
        ]
        self.assertEqual(
            {f"reference:mase-guidelines-2022:page-{page}" for page in range(20, 40)},
            {asset["asset_id"] for asset in references},
        )
        self.assertTrue(all(not asset["annotations"] for asset in references))

    def test_each_assigned_material_code_has_six_synthetic_variants(self) -> None:
        synthetic = [
            asset for asset in self.manifest["assets"]
            if asset["content_origin"] == "synthetic"
        ]
        mark_counts: dict[str, int] = {}
        for asset in synthetic:
            annotation = asset["annotations"][0]
            mark_ref = annotation["resolved_mark_ref"]
            mark_counts[mark_ref] = mark_counts.get(mark_ref, 0) + 1
        self.assertEqual(31, len(mark_counts))
        self.assertEqual({6}, set(mark_counts.values()))

    def test_source_hashes_match_the_preserved_documents(self) -> None:
        paths = {
            "guidelines_pdf": SOURCES / "dm-360-2022-adopted-guidelines-it.pdf",
            "decree_pdf": SOURCES / "dm-360-2022-guidelines-it.pdf",
            "legal_notice_pdf": SOURCES / "mase-legal-notice.pdf",
        }
        actual = {
            role: hashlib.sha256(path.read_bytes()).hexdigest()
            for role, path in paths.items()
        }
        self.assertEqual(actual, self.report["source_sha256"])

    def test_photo_capture_contract_and_example_are_machine_readable(self) -> None:
        schema = json.loads(
            (WORKSPACE / "schemas" / "photo-capture-record.schema.json").read_text(
                encoding="utf-8"
            )
        )
        record = json.loads(
            (WORKSPACE / "examples" / "photo-capture-ledger.jsonl").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual("MI", record["primary_category"])
        self.assertEqual("object", schema["type"])


if __name__ == "__main__":
    unittest.main()
