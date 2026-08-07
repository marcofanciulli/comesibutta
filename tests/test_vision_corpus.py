from __future__ import annotations

import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from dovelobutto.vision_corpus import split_for_capture_group, validate_vision_corpus


WORKSPACE = Path(__file__).parents[1]
TAXONOMY = WORKSPACE / "data" / "vision" / "taxonomy-v1.json"
MANIFEST = WORKSPACE / "data" / "vision" / "corpus-manifest.json"


def _source() -> dict:
    return {
        "source_id": "source-owned-001",
        "rights_basis": "original_work",
        "license_id": None,
        "license_url": None,
        "attribution": "ComeSiButta",
        "rights_review": "approved",
        "personal_data_allowed": False,
        "notes": None,
    }


def _annotation() -> dict:
    return {
        "annotation_id": "annotation-001",
        "category_id": "mark.material_identification",
        "bounding_box": {"x_min": 0.1, "y_min": 0.2, "x_max": 0.4, "y_max": 0.5},
        "transcription": "PET 1",
        "transcription_status": "exact",
        "resolved_mark_ref": "packaging-material:eu-97-129:1",
        "quality": {
            "occlusion": "none", "blur": "none", "glare": "moderate", "perspective": "frontal"
        },
    }


class VisionCorpusTest(unittest.TestCase):
    def test_bootstrap_manifest_is_valid_and_explicitly_not_trainable(self) -> None:
        report = validate_vision_corpus(MANIFEST, TAXONOMY)
        self.assertEqual(0, report["assets"])
        self.assertEqual(0, report["annotations"])
        self.assertFalse(report["trainable"])
        self.assertFalse(report["release_evaluation_ready"])

    def test_validates_rights_files_annotations_and_deterministic_split(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            assets = root / "assets"
            assets.mkdir()
            image = assets / "owned.jpg"
            image.write_bytes(b"test-image-content")
            manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
            split = split_for_capture_group("package-001", manifest["split_policy"])
            manifest["sources"] = [_source()]
            manifest["assets"] = [{
                "asset_id": "asset-001",
                "path": "owned.jpg",
                "sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
                "mime_type": "image/jpeg",
                "width": 1200,
                "height": 900,
                "content_origin": "real_photo",
                "source_id": "source-owned-001",
                "capture_group_id": "package-001",
                "split": split,
                "captured_at": "2026-08-07T12:00:00+02:00",
                "privacy_review": "approved",
                "annotations": [_annotation()],
            }]
            manifest_path = root / "manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            report = validate_vision_corpus(manifest_path, TAXONOMY, assets)
        self.assertEqual(1, report["assets"])
        self.assertEqual(1, report["annotations"])
        self.assertTrue(report["trainable"])

    def test_rejects_capture_group_leakage(self) -> None:
        with TemporaryDirectory() as temporary:
            manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
            expected = split_for_capture_group("package-001", manifest["split_policy"])
            wrong = next(split for split in ("train", "validation", "test") if split != expected)
            manifest["sources"] = [_source()]
            manifest["assets"] = [{
                "asset_id": "asset-001", "path": "owned.jpg", "sha256": "0" * 64,
                "mime_type": "image/jpeg", "width": 100, "height": 100,
                "content_origin": "real_photo", "source_id": "source-owned-001",
                "capture_group_id": "package-001", "split": wrong,
                "captured_at": None, "privacy_review": "approved", "annotations": [],
            }]
            path = Path(temporary) / "manifest.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "deterministic capture-group split"):
                validate_vision_corpus(path, TAXONOMY)

    def test_rejects_unapproved_rights_and_invalid_boxes(self) -> None:
        with TemporaryDirectory() as temporary:
            manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
            source = _source()
            source["rights_review"] = "pending"
            annotation = _annotation()
            annotation["bounding_box"]["x_max"] = 0.05
            manifest["sources"] = [source]
            manifest["assets"] = [{
                "asset_id": "asset-001", "path": "owned.jpg", "sha256": "0" * 64,
                "mime_type": "image/jpeg", "width": 100, "height": 100,
                "content_origin": "real_photo", "source_id": "source-owned-001",
                "capture_group_id": "package-001",
                "split": split_for_capture_group("package-001", manifest["split_policy"]),
                "captured_at": None, "privacy_review": "approved", "annotations": [annotation],
            }]
            path = Path(temporary) / "manifest.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "rights are not approved"):
                validate_vision_corpus(path, TAXONOMY)

    def test_rejects_asset_paths_outside_the_corpus(self) -> None:
        with TemporaryDirectory() as temporary:
            manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
            manifest["sources"] = [_source()]
            manifest["assets"] = [{
                "asset_id": "asset-001", "path": "../private.jpg", "sha256": "0" * 64,
                "mime_type": "image/jpeg", "width": 100, "height": 100,
                "content_origin": "real_photo", "source_id": "source-owned-001",
                "capture_group_id": "package-001",
                "split": split_for_capture_group("package-001", manifest["split_policy"]),
                "captured_at": None, "privacy_review": "approved", "annotations": [],
            }]
            path = Path(temporary) / "manifest.json"
            path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "below the assets root"):
                validate_vision_corpus(path, TAXONOMY)

    def test_schema_documents_are_valid_json(self) -> None:
        for path in (
            WORKSPACE / "schemas" / "vision-taxonomy.schema.json",
            WORKSPACE / "schemas" / "vision-corpus-manifest.schema.json",
        ):
            self.assertIsInstance(json.loads(path.read_text(encoding="utf-8")), dict)

    def test_model_contract_uses_the_canonical_taxonomy_version(self) -> None:
        taxonomy = json.loads(TAXONOMY.read_text(encoding="utf-8"))
        contract = json.loads(
            (WORKSPACE / "examples" / "vision-model-contract.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(taxonomy["taxonomy_version"], contract["taxonomy_version"])


if __name__ == "__main__":
    unittest.main()
