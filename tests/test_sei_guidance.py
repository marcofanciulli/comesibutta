from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from dovelobutto.sei_guidance import extract_sei_stream_guidance


class SeiGuidanceTests(unittest.TestCase):
    def test_operator_guidance_is_scoped_to_sei_municipalities(self) -> None:
        html = """
        <h1><small>Raccolta differenziata</small> Organico</h1>
        <div class="differenziata__conferimenti si">
          <h3>Si</h3><p>Scarti alimentari • Tappi di sughero • Fondi di caffe</p>
        </div>
        """
        with TemporaryDirectory() as temporary:
            registry = Path(temporary) / "registry.jsonl"
            registry.write_text("\n".join([
                json.dumps({"payload": {
                    "istat_code": "053014", "operator_ref": "sei-toscana",
                }}),
                json.dumps({"payload": {
                    "istat_code": "049009", "operator_ref": "aamps",
                }}),
            ]), encoding="utf-8")
            records, report = extract_sei_stream_guidance(
                html,
                registry,
                "https://example.test/organico",
                datetime.fromisoformat("2026-08-08T11:00:00+02:00"),
            )
        self.assertEqual(3, len(records))
        self.assertEqual("Organico", report["stream_name"])
        self.assertEqual(1, report["municipalities"])
        cork = next(record for record in records if record["payload"]["term"] == "Tappi di sughero")
        self.assertEqual("istat:053014", cork["payload"]["municipality_ref"])
        self.assertEqual("Organico", cork["payload"]["destination_raw"])
        self.assertEqual(
            ".differenziata__conferimenti.si",
            cork["source"]["evidence"]["selector"],
        )

    def test_missing_guidance_is_rejected(self) -> None:
        with TemporaryDirectory() as temporary:
            registry = Path(temporary) / "registry.jsonl"
            registry.write_text("", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "does not expose"):
                extract_sei_stream_guidance(
                    "<h1>Organico</h1>", registry, "https://example.test", datetime.now(),
                )
