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

    def test_special_guidance_uses_title_and_published_instructions(self) -> None:
        html = """
        <h1><small>Raccolta differenziata</small> Pile esauste</h1>
        <div class="page-body"><p>Usa gli appositi contenitori o portale al centro.</p></div>
        """
        with TemporaryDirectory() as temporary:
            registry = Path(temporary) / "registry.jsonl"
            registry.write_text(json.dumps({"payload": {
                "istat_code": "053014", "operator_ref": "sei-toscana",
            }}) + "\n", encoding="utf-8")
            records, report = extract_sei_stream_guidance(
                html, registry, "https://example.test/pile", datetime.now(),
            )
        self.assertEqual(1, len(records))
        self.assertEqual("Pile esauste", records[0]["payload"]["term"])
        self.assertEqual(
            "Punto di raccolta o centro di raccolta",
            records[0]["payload"]["destination_raw"],
        )
        self.assertIn("appositi contenitori", records[0]["payload"]["instructions_raw"])
        self.assertEqual(".page-body", records[0]["source"]["evidence"]["selector"])
        self.assertEqual(report["destination"], records[0]["payload"]["destination_raw"])

    def test_examples_are_added_as_search_terms_after_source_bullets(self) -> None:
        html = """
        <h1><small>Raccolta differenziata</small> RAEE</h1>
        <div class="differenziata__conferimenti si"><p>
          Sorgenti luminose (es. lampade a LED, tubi al neon, etc.)
          • Piccoli elettrodomestici (es. aspirapolvere, tostapane)
        </p></div>
        """
        with TemporaryDirectory() as temporary:
            registry = Path(temporary) / "registry.jsonl"
            registry.write_text(json.dumps({"payload": {
                "istat_code": "053014", "operator_ref": "sei-toscana",
            }}) + "\n", encoding="utf-8")
            records, report = extract_sei_stream_guidance(
                html, registry, "https://example.test/raee", datetime.now(),
            )
        terms = [record["payload"]["term"] for record in records]
        self.assertEqual("Sorgenti luminose (es. lampade a LED, tubi al neon, etc.)", terms[0])
        self.assertEqual("Piccoli elettrodomestici (es. aspirapolvere, tostapane)", terms[1])
        self.assertEqual(
            ["lampade a LED", "tubi al neon", "aspirapolvere", "tostapane"],
            terms[2:6],
        )
        self.assertEqual(["Sorgenti luminose", "Piccoli elettrodomestici"], terms[6:])
        self.assertEqual(2, report["source_bullets"])
        self.assertEqual(8, report["accepted_terms"])
        self.assertIn("Sorgenti luminose", records[2]["source"]["evidence"]["quote"])
