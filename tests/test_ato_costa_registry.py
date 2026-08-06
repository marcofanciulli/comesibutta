from __future__ import annotations

from datetime import datetime
from pathlib import Path
import unittest

from dovelobutto.registry import (
    extract_ato_costa_municipality_registry,
    read_istat_municipalities,
)
from dovelobutto.ato_costa import (
    MunicipalityContext,
    extract_aamps_waste_lookup,
    extract_esa_bundle,
    extract_rea_waste_lookup,
)
from dovelobutto.rea import extract_rea_centre, extract_rea_collection_pages


WORKSPACE = Path(__file__).parents[1]


class AtoCostaRegistryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        source = WORKSPACE / "data" / "sources" / "ato-toscana-costa" / "municipalities-sol-2026.csv"
        cls.records, cls.warnings = extract_ato_costa_municipality_registry(
            source.read_text(encoding="utf-8"),
            datetime.fromisoformat("2026-08-06T14:00:00+02:00"),
            read_istat_municipalities(
                WORKSPACE / "data" / "sources" / "istat" / "toscana-comuni-2026-02-21.csv"
            ),
        )

    def test_matches_all_official_municipalities(self) -> None:
        self.assertEqual(100, len(self.records))
        self.assertEqual([], self.warnings)
        counts: dict[str, int] = {}
        for record in self.records:
            province = record["payload"]["province_code"]
            counts[province] = counts.get(province, 0) + 1
        self.assertEqual({"LI": 13, "LU": 33, "MS": 17, "PI": 37}, counts)

    def test_preserves_unified_and_local_operators(self) -> None:
        livorno = next(record for record in self.records if record["payload"]["name"] == "Livorno")
        self.assertEqual("retiambiente", livorno["payload"]["operator_ref"])
        self.assertEqual("aamps", livorno["payload"]["local_operator_ref"])
        self.assertEqual("AAMPS S.p.A.", livorno["payload"]["local_operator_name"])

    def test_preserves_transition_cases(self) -> None:
        statuses = {
            record["payload"]["name"]: record["payload"]["assignment_status"]
            for record in self.records
        }
        self.assertEqual("pending_subentry", statuses["Porto Azzurro"])
        self.assertEqual("pending_subentry", statuses["Peccioli"])
        self.assertEqual("transition", statuses["Lucca"])

    def test_seeds_livorno_source_strategies(self) -> None:
        records = {record["payload"]["name"]: record["payload"] for record in self.records}
        self.assertIn("Dove-lo-butto", records["Livorno"]["service_urls"]["collection"][0])
        self.assertEqual("https://www.esaspa.it/centri-di-raccolta/", records["Rio"]["service_urls"]["facilities"][0])
        self.assertIn("comune-di-bibbona", records["Bibbona"]["homepage_url"])

    def test_preserves_rea_irregular_municipality_urls(self) -> None:
        records = {record["payload"]["name"]: record["payload"] for record in self.records}
        self.assertIn("castelnuovo-val-di-cecina/servizi", records["Castelnuovo di Val di Cecina"]["homepage_url"])
        self.assertIn("comune-guardistallo", records["Guardistallo"]["homepage_url"])
        self.assertIn("comune-di-monteverdi/", records["Monteverdi Marittimo"]["homepage_url"])

class EsaExtractorTest(unittest.TestCase):
    def test_extracts_shared_rifiutario_rules_and_local_facilities(self) -> None:
        collection = """
        <main><p>In tutta l’Isola d’Elba è attiva la raccolta differenziata porta a porta.</p>
        <ul><li data-name="Tetrapak" data-destination="Imballaggi e contenitori in plastica e metallo">Tetrapak</li>
        <li data-name="Armadio" data-destination="Centro di Raccolta">Armadio</li></ul></main>
        """
        facilities = """
        <main><p>Le utenze domestiche regolarmente iscritte a ruolo TARI possono conferire gratuitamente.</p>
        <a href="https://example.test/capoliveri-lacona">CDR Mobile a Lacona (Capoliveri)</a>
        <a href="https://example.test/rio">CDR Rio, Loc. Serrantone</a></main>
        """
        records, warnings = extract_esa_bundle(
            MunicipalityContext("Capoliveri", "049004", "capoliveri"),
            datetime.fromisoformat("2026-08-06T15:00:00+02:00"),
            [
                ("https://www.esaspa.it/cittadini/raccolta-differenziata/", collection),
                ("https://www.esaspa.it/centri-di-raccolta/", facilities),
            ],
        )
        self.assertEqual([], warnings)
        self.assertEqual(2, sum(record["record_type"] == "waste_lookup" for record in records))
        self.assertEqual(5, sum(record["record_type"] == "collection_rule" for record in records))
        facilities = [record for record in records if record["record_type"] == "facility"]
        self.assertEqual(1, len(facilities))
        self.assertIn("Lacona", facilities[0]["payload"]["name"])

    def test_keeps_marciana_separate_from_marciana_marina(self) -> None:
        facilities = """
        <main><a href="https://example.test/marciana">CDR Marciana Loc. San Rocco</a>
        <a href="https://example.test/marina">CDR Marciana Marina, Viale Aldo Moro, 41</a></main>
        """
        records, _ = extract_esa_bundle(
            MunicipalityContext("Marciana", "049010", "marciana"),
            datetime.fromisoformat("2026-08-06T15:00:00+02:00"),
            [
                ("https://www.esaspa.it/cittadini/raccolta-differenziata/", '<li data-name="Vetro" data-destination="Vetro">Vetro</li>'),
                ("https://www.esaspa.it/centri-di-raccolta/", facilities),
            ],
        )
        names = [record["payload"]["name"] for record in records if record["record_type"] == "facility"]
        self.assertEqual(["CDR Marciana Loc. San Rocco"], names)


class ReaExtractorTest(unittest.TestCase):
    def test_preserves_entries_without_a_published_destination(self) -> None:
        source = """{
          "source_url": "https://www.reaspa.it/wp-admin/admin-ajax.php",
          "items": [
            {"id": "1", "name": "Tetrapak", "destination": "Sacco multimateriale", "category": "multimateriale"},
            {"id": "2", "name": "Lavatrice", "destination": "", "category": ""}
          ]
        }"""
        records = extract_rea_waste_lookup(
            MunicipalityContext("Bibbona", "049001", "bibbona"),
            datetime.fromisoformat("2026-08-06T16:30:00+02:00"),
            "https://www.reaspa.it/wp-admin/admin-ajax.php",
            source,
        )
        self.assertEqual(2, len(records))
        lavatrice = next(record for record in records if record["payload"]["term"] == "Lavatrice")
        self.assertIsNone(lavatrice["payload"]["destination_raw"])
        self.assertEqual("missing_destination", lavatrice["payload"]["resolution_status"])

    def test_extracts_bag_rules_and_pickup_service(self) -> None:
        collection = """<main class="zui-content"><h1>Raccolta stradale</h1>
        <h2>UTENZE DOMESTICHE</h2><h3>Organico</h3>
        <p>Usare sacchi compostabili nel contenitore marrone.</p>
        <h3>Carta e cartone</h3><p>Raccolta in contenitore blu.</p></main>"""
        pickup = """<main class="zui-content"><h1>Raccolta ingombranti</h1>
        <p>La raccolta degli ingombranti si prenota online.</p></main>"""
        records, warnings = extract_rea_collection_pages(
            MunicipalityContext("Bibbona", "049001", "bibbona"),
            datetime.fromisoformat("2026-08-06T18:00:00+02:00"),
            [
                ("https://www.reaspa.it/servizi/raccolta-stradale/?comune=1", collection),
                ("https://www.reaspa.it/servizi/raccolta-ingombranti/?comune=1", pickup),
            ],
        )
        self.assertEqual([], warnings)
        organic = next(record for record in records if record["record_type"] == "collection_rule" and record["payload"]["stream_name"] == "Rifiuti organici")
        self.assertEqual("compostable_bag", organic["payload"]["presentation"]["mode"])
        self.assertEqual("marrone", organic["payload"]["container_color"])
        self.assertEqual(1, sum(record["record_type"] == "pickup_service" for record in records))

    def test_preserves_centre_materials_without_inventing_eer_codes(self) -> None:
        html = """<main class="zui-content"><h1>Cecina</h1>
        <p>Quando: lunedi 8:00-12:00</p><p>Dove siamo: Cecina, Via Pasubio 130</p>
        <h3>Cosa conferire</h3><ul><li>Legno</li><li>Vernici e bombolette spray</li></ul>
        <h3>Modalità di accesso</h3><p>Tessera sanitaria per le utenze domestiche.</p></main>"""
        records = extract_rea_centre(
            MunicipalityContext("Cecina", "049007", "cecina"),
            datetime.fromisoformat("2026-08-06T18:00:00+02:00"),
            "https://www.reaspa.it/centri-di-raccolta/cecina/",
            html,
        )
        accepted = [record for record in records if record["record_type"] == "facility_acceptance"]
        self.assertEqual(2, len(accepted))
        self.assertIsNone(accepted[0]["payload"]["eer_code_raw"])
        self.assertIsNone(accepted[0]["payload"]["hazardous"])
        self.assertEqual("unmapped_description", accepted[0]["payload"]["eer_code_status"])
        self.assertEqual(1, sum(record["record_type"] == "opening_period" for record in records))


class AampsExtractorTest(unittest.TestCase):
    def test_pairs_pdf_columns_and_flags_wrapped_destinations(self) -> None:
        bbox = """<html xmlns="http://www.w3.org/1999/xhtml"><body><doc>
        <page width="883" height="637"><flow><block>
          <line xMin="55" yMin="105"><word>tetra</word><word>pak</word></line>
          <line xMin="252" yMin="105.2"><word>sacco</word><word>giallo</word></line>
          <line xMin="449" yMin="115"><word>lavatrici</word></line>
          <line xMin="646" yMin="115.2"><word>raccolta</word><word>o</word><word>servizio</word><word>ingombranti</word></line>
        </block></flow></page></doc></body></html>"""
        records, warnings = extract_aamps_waste_lookup(
            MunicipalityContext("Livorno", "049009", "livorno"),
            datetime.fromisoformat("2026-08-06T17:10:00+02:00"),
            "https://example.test/aamps.pdf",
            bbox,
        )
        self.assertEqual(2, len(records))
        self.assertEqual("sacco giallo", records[0]["payload"]["destination_raw"])
        self.assertEqual("medium", records[1]["confidence"])
        self.assertEqual("possible_pdf_column_wrap", warnings[0]["code"])


if __name__ == "__main__":
    unittest.main()
