from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from dovelobutto.boundary import build_boundary_registry, materialize_boundary
from dovelobutto.registry import read_istat_municipalities


WORKSPACE = Path(__file__).parents[1]
RETRIEVED_AT = datetime.fromisoformat("2026-08-07T12:00:00+02:00")


class BoundaryTests(unittest.TestCase):
    def test_registry_has_all_four_extra_regional_ato_municipalities(self) -> None:
        records, warnings = build_boundary_registry(
            RETRIEVED_AT,
            read_istat_municipalities(WORKSPACE / "data/sources/istat/toscana-comuni-2026-02-21.csv"),
        )
        self.assertEqual([], warnings)
        self.assertEqual(4, len(records))
        assignments = {record["payload"]["name"]: record["payload"]["ato_ref"] for record in records}
        self.assertEqual("ato-marche-1-pesaro-urbino", assignments["Sestino"])
        self.assertEqual("ato-emilia-romagna-bologna", assignments["Firenzuola"])

    def test_materializes_address_scoped_rules_bags_and_station(self) -> None:
        registry = [{
            "name": "Firenzuola", "istat_code": "048018", "source_slug": "firenzuola",
            "operator_ref": "hera", "ato_ref": "ato-emilia-romagna-bologna",
        }]
        result = {
            "zone": [{"zona_id": 100}],
            "macroprodotti": [{
                "id": 2, "descrizione": "Abiti usati", "pittogrammaColore": "F4901D",
                "note": "<p>Conferire all'interno di sacchetti di plastica chiusi.</p>",
                "conferimenti": [{"descrizione": "Contenitori stradali abiti usati"}],
            }],
            "puntiDiRaccoltaFissiAbitiUsati": [{
                "id": 9, "nome": "Contenitore abiti usati", "indirizzo": "Via Roma",
                "latitudine": 44.1, "longitudine": 11.3,
                "macroProdotti": [{"descrizione": "Abiti usati"}],
            }],
            "stazioniEcologiche": [{"id": 71}],
        }
        bundle = {
            "access": {}, "errors": [], "mms": {"pages": {}},
            "hera": {"firenzuola": {
                "name": "Firenzuola", "istat_code": "048018", "hera_id": 76,
                "sample": {"address": "Via Roma", "address_id": 1, "civic": "1", "civic_id": 2},
                "products": [{"id": 1, "nome": "Abiti usati", "keywords": "vestiti"}],
                "product_data": {"1": result},
                "stations": {"71": {
                    "id": 71, "comune": "Firenzuola", "nome": "Stazione Ecologica di Firenzuola",
                    "indirizzo": "Via degli Alpini 44", "latitudine": 44.11, "longitudine": 11.38,
                    "descrizioneServizi": "Accesso con Carta Smeraldo.",
                    "aperture": [{
                        "giorno": 1, "orarioInizio": "09:00", "orarioFine": "13:00",
                        "dataInizio": "2026-05-01T00:00:00+00:00", "dataFine": "2026-10-31T00:00:00+00:00",
                        "note": "Orario Estivo",
                    }],
                    "chiusure": [],
                    "macroprodotti": [{"descrizione": "Legno", "limite": "2 mc", "prodotti": []}],
                }},
            }},
        }
        with TemporaryDirectory() as directory:
            report = materialize_boundary(registry, bundle, RETRIEVED_AT, Path(directory))
            records = [json.loads(line) for line in (Path(directory) / "firenzuola-acquisition.jsonl").read_text(encoding="utf-8").splitlines()]
        rule = next(record for record in records if record["record_type"] == "collection_rule")
        self.assertEqual("plastic_bag", rule["payload"]["presentation"]["mode"])
        self.assertIn("indirizzo campione", rule["payload"]["schedule_raw"])
        self.assertEqual("named_area", next(record for record in records if record["record_type"] == "service_zone")["payload"]["scope_type"])
        self.assertEqual("2 mc", next(record for record in records if record["record_type"] == "facility_acceptance")["payload"]["quantity_limit_raw"])
        self.assertEqual(1, report["extraction"]["municipalities"])

    def test_sestino_is_partial_and_explicitly_reports_robots_gap(self) -> None:
        registry = [{
            "name": "Sestino", "istat_code": "051035", "source_slug": "sestino",
            "operator_ref": "marche-multiservizi", "ato_ref": "ato-marche-1-pesaro-urbino",
        }]
        bundle = {
            "access": {}, "errors": [], "hera": {},
            "mms": {"pages": {"pickup": {
                "url": "https://example.test/pickup", "status": "snapshot",
                "html": "<p>Ritiro ingombranti e RAEE. Numero verde 800.600.999.</p>",
            }}},
        }
        with TemporaryDirectory() as directory:
            report = materialize_boundary(registry, bundle, RETRIEVED_AT, Path(directory))
        municipality = report["extraction"]["municipality_reports"][0]
        self.assertEqual(1, municipality["records_by_type"]["pickup_service"])
        self.assertIn("municipality_source_blocked_by_robots", {warning["code"] for warning in municipality["warnings"]})
        self.assertNotIn("collection_rule", municipality["records_by_type"])


if __name__ == "__main__":
    unittest.main()
