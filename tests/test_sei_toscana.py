from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import unittest

from dovelobutto.sei_toscana import (
    MunicipalityContext,
    build_eer_description_reference,
    extract_municipality_bundle,
    reconcile_eer_records,
)


FIXTURES = Path(__file__).parent / "fixtures" / "sei_toscana" / "manciano"
BASE_URL = "https://seitoscana.it/comuni/manciano"


class SeiToscanaExtractorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        pages = []
        for name in ("raccolta-rifiuti", "centro-di-raccolta", "ritiro-ingombranti"):
            pages.append((f"{BASE_URL}/{name}", (FIXTURES / f"{name}.html").read_text(encoding="utf-8")))
        cls.records, cls.warnings = extract_municipality_bundle(
            context=MunicipalityContext("Manciano", "053014", "manciano"),
            retrieved_at=datetime.fromisoformat("2026-08-05T10:00:00+02:00"),
            pages=pages,
        )

    def records_of_type(self, record_type: str) -> list[dict]:
        return [record for record in self.records if record["record_type"] == record_type]

    def test_extracts_facility_and_coordinates(self) -> None:
        facilities = self.records_of_type("facility")
        self.assertEqual(1, len(facilities))
        facility = facilities[0]["payload"]
        self.assertEqual("Centro di Raccolta Manciano", facility["name"])
        self.assertAlmostEqual(42.60224106, facility["location"]["latitude"])
        self.assertAlmostEqual(11.51843219, facility["location"]["longitude"])
        self.assertEqual("800127484", facility["phone"])

    def test_extracts_opening_hours(self) -> None:
        periods = self.records_of_type("opening_period")
        self.assertEqual(1, len(periods))
        intervals = periods[0]["payload"]["weekly_intervals"]
        self.assertEqual(6, len(intervals))
        self.assertIn({"weekday": 6, "opens": "15:00", "closes": "17:00"}, intervals)

    def test_preserves_duplicate_eer_operational_rows(self) -> None:
        acceptances = self.records_of_type("facility_acceptance")
        self.assertEqual(23, len(acceptances))
        code_200136 = [record for record in acceptances if record["payload"]["eer_code_raw"] == "200136"]
        self.assertEqual(2, len(code_200136))
        self.assertEqual("RAEE R2", code_200136[1]["payload"]["operational_group"])
        self.assertTrue(all(record["payload"]["eer_code_status"] == "exact" for record in acceptances))

    def test_preserves_malformed_eer_with_review_candidate(self) -> None:
        html = """
        <section class="section-cdr">
          <h2 class="section-cdr__title">Centro di Raccolta Grosseto</h2>
          <table class="tabellaconferimenti"><tbody>
            <tr><td>15106</td><td>Imballaggi in materiali misti</td></tr>
          </tbody></table>
        </section>
        """
        records, warnings = extract_municipality_bundle(
            context=MunicipalityContext("Grosseto", "053011", "grosseto"),
            retrieved_at=datetime.fromisoformat("2026-08-05T10:00:00+02:00"),
            pages=[(f"https://seitoscana.it/comuni/grosseto/centro-di-raccolta", html)],
        )
        acceptance = next(record for record in records if record["record_type"] == "facility_acceptance")
        self.assertEqual("15106", acceptance["payload"]["eer_code_raw"])
        self.assertEqual("150106", acceptance["payload"]["eer_code_normalized"])
        self.assertEqual("inferred_candidate", acceptance["payload"]["eer_code_status"])
        self.assertEqual("low", acceptance["confidence"])
        self.assertEqual("invalid_eer_code", warnings[0]["code"])

    def test_reconciles_malformed_eer_from_unique_description(self) -> None:
        malformed_html = """
        <section class="section-cdr">
          <h2 class="section-cdr__title">Centro di Raccolta Grosseto</h2>
          <table class="tabellaconferimenti"><tbody>
            <tr><td>15106</td><td>Imballaggi in materiali misti (Plastica, Alluminio, Vetro)</td></tr>
          </tbody></table>
        </section>
        """
        reference_html = """
        <section class="section-cdr">
          <h2 class="section-cdr__title">Centro di Raccolta Manciano</h2>
          <table class="tabellaconferimenti"><tbody>
            <tr><td>150106</td><td>Imballaggi in materiali misti</td></tr>
          </tbody></table>
        </section>
        """
        malformed, warnings = extract_municipality_bundle(
            context=MunicipalityContext("Grosseto", "053011", "grosseto"),
            retrieved_at=datetime.fromisoformat("2026-08-05T10:00:00+02:00"),
            pages=[("https://seitoscana.it/comuni/grosseto/centro-di-raccolta", malformed_html)],
        )
        reference_records, _ = extract_municipality_bundle(
            context=MunicipalityContext("Manciano", "053014", "manciano"),
            retrieved_at=datetime.fromisoformat("2026-08-05T10:00:00+02:00"),
            pages=[("https://seitoscana.it/comuni/manciano/centro-di-raccolta", reference_html)],
        )
        reference = build_eer_description_reference([malformed, reference_records])
        reconciled, remaining_warnings = reconcile_eer_records(malformed, warnings, reference)
        acceptance = next(record for record in reconciled if record["record_type"] == "facility_acceptance")
        self.assertEqual("reconciled", acceptance["payload"]["eer_code_status"])
        self.assertEqual("unique_batch_description_match", acceptance["payload"]["reconciliation_basis"])
        self.assertEqual("high", acceptance["confidence"])
        self.assertEqual([], remaining_warnings)

    def test_extracts_explicit_prose_acceptance_without_table_warning(self) -> None:
        html = """
        <section class="section-cdr">
          <h2 class="section-cdr__title">Centro riservato ai manutentori del verde</h2>
          <p>I professionisti possono accedere per il conferimento del SOLO rifiuto biodegradabile (CER 200201).</p>
        </section>
        """
        records, warnings = extract_municipality_bundle(
            context=MunicipalityContext("Grosseto", "053011", "grosseto"),
            retrieved_at=datetime.fromisoformat("2026-08-05T10:00:00+02:00"),
            pages=[("https://seitoscana.it/comuni/grosseto/centro-di-raccolta", html)],
        )
        acceptance = next(record for record in records if record["record_type"] == "facility_acceptance")
        self.assertEqual("200201", acceptance["payload"]["eer_code_normalized"])
        self.assertEqual("rifiuto biodegradabile", acceptance["payload"]["description_raw"])
        self.assertEqual([], warnings)

    def test_extracts_temporary_facility_closure(self) -> None:
        html = """
        <section class="section-cdr">
          <h2 class="section-cdr__title">Centro di Raccolta Isola del Giglio</h2>
          <div class="alert alert--danger"><span>Chiuso per lavori di adeguamento</span></div>
        </section>
        """
        records, _ = extract_municipality_bundle(
            context=MunicipalityContext("Isola del Giglio", "053012", "isola-del-giglio"),
            retrieved_at=datetime.fromisoformat("2026-08-05T10:00:00+02:00"),
            pages=[("https://seitoscana.it/comuni/isola-del-giglio/centro-di-raccolta", html)],
        )
        facility = next(record for record in records if record["record_type"] == "facility")
        self.assertEqual("temporarily_closed", facility["payload"]["operational_status"])
        self.assertEqual("Chiuso per lavori di adeguamento", facility["payload"]["status_raw"])

    def test_extracts_domestic_and_non_domestic_access(self) -> None:
        access_records = self.records_of_type("facility_access")
        self.assertEqual(2, len(access_records))
        by_user_type = {record["payload"]["user_type"]: record["payload"] for record in access_records}
        self.assertIn("domestic", by_user_type)
        self.assertEqual("segreteria@seitoscana.it", by_user_type["non_domestic"]["contact_email"])
        self.assertTrue(by_user_type["domestic"]["information_urls"])

    def test_extracts_zone_specific_collection_rules(self) -> None:
        rules = self.records_of_type("collection_rule")
        self.assertEqual(9, len(rules))
        organic = next(
            record for record in rules
            if record["payload"]["zone_ref"].endswith(":marsiliana")
            and record["payload"]["stream_name"] == "Organico"
        )
        self.assertEqual("marrone", organic["payload"]["container_color"])
        self.assertEqual("biodegradable_bag", organic["payload"]["presentation"]["mode"])

    def test_extracts_special_collection_points(self) -> None:
        points = self.records_of_type("collection_point")
        self.assertEqual(27, len(points))
        streams = {stream for point in points for stream in point["payload"]["accepted_streams"]}
        self.assertEqual(
            {"Olio alimentare esausto", "Medicinali scaduti", "Pile esauste", "Piccoli RAEE"},
            streams,
        )
        oil_points = [point for point in points if point["payload"]["accepted_streams"] == ["Olio alimentare esausto"]]
        self.assertEqual(3, len(oil_points))

    def test_extracts_pickup_limits_and_methods(self) -> None:
        services = self.records_of_type("pickup_service")
        self.assertEqual(1, len(services))
        service = services[0]["payload"]
        self.assertEqual(5, service["max_items"])
        methods = {method["method"] for method in service["booking_methods"]}
        self.assertEqual({"web", "phone"}, methods)

    def test_records_are_json_serializable_and_have_provenance(self) -> None:
        json.dumps(self.records)
        for record in self.records:
            self.assertEqual(64, len(record["source"]["content_sha256"]))
            self.assertTrue(record["source"]["evidence"]["quote"] is not None)


if __name__ == "__main__":
    unittest.main()
