import json
from pathlib import Path
import struct
import unittest


ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "outputs/models/packaging-mark-bootstrap-v0.1.0"


class VisionTrainingArtifactsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.training = json.loads(
            (MODEL_DIR / "training-report.json").read_text(encoding="utf-8")
        )
        cls.evaluation = json.loads(
            (MODEL_DIR / "evaluation-report.json").read_text(encoding="utf-8")
        )

    def test_bootstrap_is_never_marked_for_release(self):
        self.assertEqual(self.training["status"], "bootstrap_not_for_release")
        self.assertEqual(self.evaluation["status"], "synthetic_validation_only")
        self.assertFalse(self.evaluation["release_eligible"])

    def test_only_annotated_synthetic_assets_are_used(self):
        dataset = self.training["dataset"]
        self.assertEqual(dataset["annotated_train_assets"], 150)
        self.assertEqual(dataset["annotated_validation_assets"], 36)
        self.assertEqual(dataset["excluded_unannotated_assets"], 20)
        self.assertEqual(dataset["observed_categories"], ["mark.material_identification"])

    def test_training_improves_over_the_baseline(self):
        last = self.training["epochs"][-1]
        self.assertLess(last["mean_train_loss"], self.training["epochs"][0]["mean_train_loss"])
        self.assertGreater(last["validation"]["f1_iou_50"], 0)
        self.assertEqual(self.training["best_epoch"], 3)

    def test_threshold_is_selected_from_the_declared_sweep(self):
        threshold = f'{self.evaluation["selected_threshold"]:.1f}'
        selected = self.evaluation["threshold_sweep"][threshold]
        self.assertEqual(threshold, "0.4")
        self.assertEqual(selected["f1_iou_50"], 0.5)
        self.assertEqual(self.evaluation["validation_assets"], 36)

    def test_preview_is_a_960_by_840_png(self):
        preview = MODEL_DIR / "validation-preview.png"
        with preview.open("rb") as stream:
            self.assertEqual(stream.read(8), b"\x89PNG\r\n\x1a\n")
            stream.read(8)
            width, height = struct.unpack(">II", stream.read(8))
        self.assertEqual((width, height), (960, 840))


if __name__ == "__main__":
    unittest.main()
