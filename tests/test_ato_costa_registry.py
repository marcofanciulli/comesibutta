from __future__ import annotations

from datetime import date, datetime, timedelta
import hashlib
from pathlib import Path
import unittest
from unittest.mock import patch

from dovelobutto.registry import (
    extract_ato_costa_municipality_registry,
    read_istat_municipalities,
)
from dovelobutto.ato_costa import (
    AAMPS_ICON_COLORS,
    ESA_SIGN_HASHES,
    MunicipalityContext,
    _aamps_destinations,
    _aamps_term_lines,
    extract_aamps_waste_lookup,
    extract_esa_bundle,
    extract_ersu_montignoso_supplement,
    extract_rea_waste_lookup,
)
from dovelobutto.rea import (
    extract_rea_centre,
    extract_rea_collection_pages,
    extract_rea_ecomobile_calendar,
    extract_rea_rur_calendar,
    extract_rea_weekly_calendar,
)
from dovelobutto.geofor import _facilities, _waste_and_rules, parse_rifiutario


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
        self.assertIn("Dove_lo_butto_2023", records["Livorno"]["service_urls"]["collection"][0])
        self.assertEqual("https://www.esaspa.it/centri-di-raccolta/", records["Rio"]["service_urls"]["facilities"][0])
        self.assertIn("comune-di-bibbona", records["Bibbona"]["homepage_url"])

    def test_preserves_rea_irregular_municipality_urls(self) -> None:
        records = {record["payload"]["name"]: record["payload"] for record in self.records}
        self.assertIn("castelnuovo-val-di-cecina/servizi", records["Castelnuovo di Val di Cecina"]["homepage_url"])
        self.assertIn("comune-guardistallo", records["Guardistallo"]["homepage_url"])
        self.assertIn("comune-di-monteverdi/", records["Monteverdi Marittimo"]["homepage_url"])

    def test_seeds_geofor_municipality_urls(self) -> None:
        records = {record["payload"]["name"]: record["payload"] for record in self.records}
        self.assertEqual("https://www.geofor.it/bientina/", records["Bientina"]["homepage_url"])
        self.assertEqual("https://www.geofor.it/montopoli/", records["Montopoli in Val d'Arno"]["homepage_url"])
        self.assertEqual("https://www.geofor.it/s-giuliano-terme/", records["San Giuliano Terme"]["homepage_url"])
        self.assertIn("dove-lo-butto", records["Pisa"]["service_urls"]["collection"][1])

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

    def test_extracts_verified_sign_codes_and_seasonal_hours(self) -> None:
        sign = b"verified Campo sign fixture"
        pages = [
            ("https://www.esaspa.it/cittadini/raccolta-differenziata/", '<li data-name="Vetro" data-destination="Vetro">Vetro</li>'),
            ("https://www.esaspa.it/centri-di-raccolta/", '<p>Le utenze domestiche regolarmente iscritte a ruolo TARI possono conferire gratuitamente.</p>'),
            ("https://www.esaspa.it/centri-di-raccolta/centro-di-raccolta-di-campo-nellelba/", '<main><h1>Centro di raccolta di Campo nell’Elba</h1><p>tutto l’anno dal lunedì al sabato aperto dalle 7:30 alle 12:30.</p></main>'),
            ("https://www.esaspa.it/wp-content/uploads/2026/07/CAMPO-NELLELBA.jpeg", sign),
        ]
        with patch.dict(ESA_SIGN_HASHES, {"CAMPO-NELLELBA.jpeg": hashlib.sha256(sign).hexdigest()}):
            records, warnings = extract_esa_bundle(
                MunicipalityContext("Campo nell'Elba", "049003", "campo-nell-elba"),
                datetime.fromisoformat("2026-08-08T10:00:00+02:00"), pages,
            )
        self.assertEqual([], warnings)
        opening = next(record for record in records if record["record_type"] == "opening_period")
        self.assertEqual(6, len(opening["payload"]["weekly_intervals"]))
        accepted = [record for record in records if record["record_type"] == "facility_acceptance"]
        self.assertEqual(29, len(accepted))
        mercury = next(record for record in accepted if record["payload"]["eer_code_normalized"] == "200121")
        self.assertTrue(mercury["payload"]["hazardous"])
        self.assertEqual("image", mercury["source"]["evidence"]["kind"])

    def test_preserves_mobile_stop_time_without_inventing_a_duration(self) -> None:
        pages = [
            ("https://www.esaspa.it/cittadini/raccolta-differenziata/", '<li data-name="Vetro" data-destination="Vetro">Vetro</li>'),
            ("https://www.esaspa.it/centri-di-raccolta/centro-di-raccolta-mobile-a-cavo-rio/", '<main><p>dedicato alle utenze domestiche e non domestiche</p><p>Tutto l’anno, tutti i martedì e giovedì alle ore 10:00.</p></main>'),
        ]
        records, warnings = extract_esa_bundle(
            MunicipalityContext("Rio", "049021", "rio"),
            datetime.fromisoformat("2026-08-08T10:00:00+02:00"), pages,
        )
        self.assertEqual([], warnings)
        opening = next(record for record in records if record["record_type"] == "opening_period")
        self.assertEqual([], opening["payload"]["weekly_intervals"])
        self.assertIn("10:00", opening["payload"]["exceptions_raw"])
        self.assertEqual(2, sum(record["record_type"] == "facility_access" for record in records))
        self.assertEqual(2, sum(record["record_type"] == "facility_acceptance" for record in records))


class ReaExtractorTest(unittest.TestCase):
    @staticmethod
    def _calendar_page(year: int, weekday: int) -> dict:
        words = [
            {"text": "GENNAIO", "x0": 10, "x1": 20, "top": 10, "bottom": 12},
            {"text": str(year), "x0": 22, "x1": 30, "top": 10, "bottom": 12},
            {"text": "MERCOLEDÌ", "x0": 32, "x1": 42, "top": 10, "bottom": 12},
            {"text": "ALTERNI", "x0": 44, "x1": 52, "top": 10, "bottom": 12},
        ]
        months = (
            "GENNAIO", "FEBBRAIO", "MARZO", "APRILE", "MAGGIO", "GIUGNO",
            "LUGLIO", "AGOSTO", "SETTEMBRE", "OTTOBRE", "NOVEMBRE", "DICEMBRE",
        )
        for index, month in enumerate(months):
            row = 100 if index < 6 else 200
            column = index % 6
            words.append({
                "text": month, "x0": column * 100 + 20, "x1": column * 100 + 80,
                "top": row, "bottom": row + 10,
            })
        current = date(year, 1, 1)
        while current.isoweekday() != weekday:
            current += timedelta(days=1)
        while current.year == year:
            index = current.month - 1
            row = 115 if index < 6 else 215
            column = index % 6
            words.append({
                "text": str(current.day), "x0": column * 100 + 45,
                "x1": column * 100 + 55, "top": row, "bottom": row + 8,
            })
            current += timedelta(days=14)
        return {"number": 1, "words": words}

    def test_extracts_complete_biweekly_rur_calendar(self) -> None:
        page = self._calendar_page(2026, 3)
        with patch("dovelobutto.rea._pdf_bbox_words", return_value=([page], "<bbox/>")):
            records, warnings = extract_rea_rur_calendar(
                MunicipalityContext("Casale Marittimo", "050006", "casale-marittimo"),
                datetime.fromisoformat("2026-08-06T19:00:00+02:00"),
                "https://example.test/CALENDARIO-CASALE-2026.pdf",
                Path("calendar.pdf"),
                "domestic",
            )
        self.assertEqual([], warnings)
        self.assertEqual(1, len(records))
        schedule = records[0]
        self.assertEqual("collection_schedule", schedule["record_type"])
        dates = schedule["payload"]["events"][0]["dates"]
        self.assertEqual(26, len(dates))
        self.assertTrue(all(date.fromisoformat(value).isoweekday() == 3 for value in dates))
        self.assertEqual("2026-01-01", schedule["validity"]["valid_from"])
        self.assertEqual("2026-12-31", schedule["validity"]["valid_to"])

    def test_links_ecomobile_dates_to_the_collection_point(self) -> None:
        words = []
        for line_number, line in enumerate((
            "8 GENNAIO 2026",
            "13:00 - 15:30 • ORCIANO PISANO",
            "Piazza dei Bersaglieri",
            "29 GENNAIO 2026",
            "13:00 - 15:30 • ORCIANO PISANO",
            "Piazza dei Bersaglieri",
        )):
            x = 20
            for token in line.split():
                words.append({
                    "text": token, "x0": x, "x1": x + len(token) * 6,
                    "top": 20 + line_number * 15, "bottom": 30 + line_number * 15,
                })
                x += len(token) * 6 + 5
        page = {"number": 1, "width": 600, "height": 800, "words": words}
        config = {
            "weekday": 4, "strict_year": True,
            "stops": ((
                "Orciano Pisano", r"ORCIANO PISANO", "Piazza dei Bersaglieri",
                "13:00-15:30", 2,
            ),),
        }
        with patch("dovelobutto.rea._pdf_bbox_words", return_value=([page], "<bbox/>")):
            records, warnings = extract_rea_ecomobile_calendar(
                MunicipalityContext("Orciano Pisano", "050023", "orciano-pisano"),
                datetime.fromisoformat("2026-08-06T19:00:00+02:00"),
                "https://example.test/Ecomobile-Orciano-Pisano2026.pdf.pdf",
                Path("calendar.pdf"), config,
            )
        self.assertEqual([], warnings)
        self.assertEqual(["collection_point", "collection_schedule"], [item["record_type"] for item in records])
        self.assertEqual(
            records[0]["natural_key"], records[1]["payload"]["collection_point_ref"],
        )
        self.assertEqual(
            ["2026-01-08", "2026-01-29"], records[1]["payload"]["events"][0]["dates"],
        )

    def test_materializes_verified_icon_calendar_with_zone_and_season(self) -> None:
        config = {
            "istat": "050010", "label": "Castellina Marittima",
            "valid_from": "2023-05-03", "expose_from": None,
            "expose_by": "12:00",
            "zones": {"rurale": ("Zone rurali", "Zone rurali")},
            "rows": (
                ("default", "all", "Rifiuti organici", ((3, None, None),)),
                ("default", "non_domestic", "Rifiuti organici", ((1, "06-15", "09-15"),)),
                ("rurale", "all", "Vetro", ()),
            ),
        }
        page = {"number": 2, "words": [
            {"text": "ORGANICO"}, {"text": "CARTA"},
        ]}
        with patch("dovelobutto.rea._pdf_bbox_words", return_value=([page], "<bbox/>")):
            records, warnings = extract_rea_weekly_calendar(
                MunicipalityContext("Castellina Marittima", "050010", "castellina-marittima"),
                datetime.fromisoformat("2026-08-06T19:00:00+02:00"),
                "https://example.test/calendario.pdf", Path("calendar.pdf"), config,
            )
        self.assertEqual([], warnings)
        self.assertEqual(2, sum(item["record_type"] == "service_zone" for item in records))
        self.assertEqual(3, sum(item["record_type"] == "collection_rule" for item in records))
        self.assertEqual(2, sum(item["record_type"] == "collection_schedule" for item in records))
        seasonal = next(
            item for item in records
            if item["record_type"] == "collection_schedule"
            and item["payload"]["collection_rule_ref"].endswith("non_domestic:rifiuti-organici")
        )
        self.assertEqual("06-15", seasonal["payload"]["events"][0]["start_month_day"])
        self.assertEqual("09-15", seasonal["payload"]["events"][0]["end_month_day"])
        self.assertEqual("12:00", seasonal["payload"]["expose_by"])
        street_glass = next(
            item for item in records
            if item["record_type"] == "collection_rule"
            and item["payload"]["stream_name"] == "Vetro"
        )
        self.assertEqual("street", street_glass["payload"]["collection_method"])
        self.assertEqual("container", street_glass["payload"]["presentation"]["mode"])

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
    def test_discards_a_wrapped_instruction_fragment_without_an_object(self) -> None:
        pages = "".join(
            (
                '<page width="883" height="637"></page>'
                if page != 5 else
                '<page width="883" height="637"><flow><block>'
                '<line xMin="70" yMin="105" yMax="115">'
                '<word>(private</word><word>del</word><word>contenuto)</word>'
                '</line><line xMin="70" yMin="125" yMax="135">'
                '<word>Bottiglia</word><word>di</word><word>vetro</word>'
                '</line></block></flow></page>'
            )
            for page in range(1, 6)
        )
        bbox = (
            '<html xmlns="http://www.w3.org/1999/xhtml"><body><doc>'
            f'{pages}</doc></body></html>'
        )

        self.assertEqual(
            [(5, 125.0, 135.0, "Bottiglia di vetro")],
            _aamps_term_lines(bbox),
        )

    def test_recognizes_visual_destination_icons(self) -> None:
        width, height = 482, 681
        pixels = bytearray([255] * width * height * 3)
        color = AAMPS_ICON_COLORS["Carta e cartone"]
        for y in range(100, 110):
            for x in range(320, 330):
                offset = (y * width + x) * 3
                pixels[offset:offset + 3] = bytes(color)
        self.assertEqual(["Carta e cartone"], _aamps_destinations((width, height, bytes(pixels)), 100, 110))

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


class ErsuMontignosoExtractorTest(unittest.TestCase):
    @patch("dovelobutto.ato_costa.ERSU_MONTIGNOSO_SHA256", hashlib.sha256(b"fixture").hexdigest())
    def test_extracts_shared_centres_eer_and_pickups(self) -> None:
        records, warnings = extract_ersu_montignoso_supplement(
            MunicipalityContext("Montignoso", "045011", "montignoso"),
            datetime.fromisoformat("2026-08-08T12:30:00+02:00"),
            "https://example.test/montignoso.pdf", b"fixture",
        )
        self.assertEqual([], warnings)
        self.assertEqual(4, sum(record["record_type"] == "facility" for record in records))
        self.assertEqual(58, sum(record["record_type"] == "facility_acceptance" for record in records))
        self.assertEqual(4, sum(record["record_type"] == "pickup_service" for record in records))
        mercury = next(record for record in records if record["record_type"] == "facility_acceptance" and record["payload"].get("eer_code_normalized") == "200121")
        self.assertEqual("200121", mercury["payload"]["eer_code_raw"])
        self.assertIsNone(mercury["payload"]["hazardous"])


class GeoforExtractorTest(unittest.TestCase):
    source = """<script>var rifiutario_data = [
      {"CodiceMateriale":1,"DescrizioneMateriale":"VASCHETTA PULITA","DescrizioneRifiuto":"Plastica","DescrizioneDestinazione":"Azzurro-Contenitore Multimateriale","CER":"150106","DescrizioneCer":"imballaggi in materiali misti","FlagCdR":false},
      {"CodiceMateriale":2,"DescrizioneMateriale":"TELEVISORE","DescrizioneRifiuto":"Elettronico (Raee)","DescrizioneDestinazione":"Cdr","CER":"200136","DescrizioneCer":"apparecchiature fuori uso","FlagCdR":true}
    ];</script>"""

    def test_extracts_embedded_waste_dictionary(self) -> None:
        self.assertEqual(2, len(parse_rifiutario(self.source)))
        records, _ = _waste_and_rules(
            MunicipalityContext("Bientina", "050001", "bientina"),
            datetime.fromisoformat("2026-08-06T20:00:00+02:00"),
            "https://www.geofor.it/dove-lo-butto/",
            self.source,
        )
        waste = [record for record in records if record["record_type"] == "waste_lookup"]
        self.assertEqual(2, len(waste))
        self.assertIn("EER 200136", waste[1]["payload"]["instructions_raw"])

    def test_extracts_centre_hours_coordinates_and_eer(self) -> None:
        html = """<div class="cdr"><div class="nome">Bientina CdR - Via E. Fermi
        <a href="https://www.google.com/maps/?q=43.696268,10.623202">vedi mappa</a></div>
        <table><tr><td>Lunedì</td><td>Martedì</td></tr>
        <tr><td>13:00 - 19.00</td><td>CHIUSO</td></tr></table></div>"""
        records = _facilities(
            MunicipalityContext("Bientina", "050001", "bientina"),
            datetime.fromisoformat("2026-08-06T20:00:00+02:00"),
            "https://www.geofor.it/bientina/centro-di-raccolta-bientina/",
            html,
            parse_rifiutario(self.source),
        )
        facility = next(record for record in records if record["record_type"] == "facility")
        self.assertAlmostEqual(43.696268, facility["payload"]["location"]["latitude"])
        opening = next(record for record in records if record["record_type"] == "opening_period")
        self.assertEqual([{"weekday": 1, "opens": "13:00", "closes": "19:00"}], opening["payload"]["weekly_intervals"])
        acceptance = next(record for record in records if record["record_type"] == "facility_acceptance")
        self.assertEqual("200136", acceptance["payload"]["eer_code_normalized"])


if __name__ == "__main__":
    unittest.main()
