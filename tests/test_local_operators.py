from datetime import datetime
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from dovelobutto.local_operators import crawl_local_operator, materialize_local_operator


RETRIEVED_AT = datetime.fromisoformat("2026-08-06T20:00:00+02:00")


def _municipality(operator: str, name: str = "Comune di prova", istat: str = "099999") -> dict[str, str]:
    return {
        "name": name,
        "istat_code": istat,
        "source_slug": "comune-di-prova",
        "local_operator_ref": operator,
    }


def _manifest(root: Path, category: str, content: str, suffix: str, content_type: str) -> dict:
    digest = hashlib.sha256(content.encode()).hexdigest()
    snapshot = f"{digest}{suffix}"
    (root / snapshot).write_text(content, encoding="utf-8")
    return {
        "summary": {"checked": 1, "snapshots": 1, "blocked_by_robots": 0, "errors": 0},
        "pages": [{
            "category": category,
            "url": "https://example.test/source",
            "final_url": "https://example.test/source",
            "content_type": content_type,
            "status": "snapshot",
            "snapshot": snapshot,
            "sha256": digest,
            "municipality_istats": [],
        }],
    }


class LocalOperatorMaterializationTest(unittest.TestCase):
    def test_crawler_stops_when_robots_is_unavailable(self) -> None:
        with TemporaryDirectory() as directory, patch(
            "dovelobutto.local_operators._request",
            side_effect=OSError("network unavailable"),
        ) as request:
            manifest = crawl_local_operator(
                "ascit", [_municipality("ascit")], Path(directory), RETRIEVED_AT, "DoveLoButtoData/0.1",
            )

        self.assertEqual(1, request.call_count)
        self.assertEqual(4, manifest["summary"]["errors"])
        self.assertTrue(all(page["status"] == "error" for page in manifest["pages"]))

    def test_ascit_assigns_only_local_and_all_municipalities_centres(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = _manifest(
                root,
                "centre_index",
                "<main>Il Cerro - Comune di Altopascio; Salanetti 1 - Tutti i Comuni; Salanetti 2 - Tutti i Comuni</main>",
                ".html",
                "text/html",
            )
            results, _ = materialize_local_operator(
                "ascit", [_municipality("ascit", "Altopascio", "046001")], manifest, root, RETRIEVED_AT,
            )

        facilities = [record["payload"]["name"] for record in results["comune-di-prova"] if record["record_type"] == "facility"]
        self.assertEqual(["Il Cerro", "Salanetti 1 (Centro di Stoccaggio)", "Salanetti 2"], facilities)

    def test_sea_does_not_assign_viareggio_centres_to_montignoso(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = _manifest(root, "centres", "<main>Centri di raccolta di Viareggio</main>", ".html", "text/html")
            results, reports = materialize_local_operator(
                "sea-ambiente", [_municipality("sea-ambiente", "Montignoso", "045011")], manifest, root, RETRIEVED_AT,
            )

        facilities = [record for record in results["comune-di-prova"] if record["record_type"] == "facility"]
        self.assertEqual([], facilities)
        self.assertIn("facility_page_not_published_or_not_structured", {warning["code"] for warning in reports[0]["warnings"]})

    def test_materializes_ascit_embedded_waste_dictionary(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            html = '<main><ul><li data-name="Tetrapak" data-destination="Multimateriale">Tetrapak</li></ul></main>'
            manifest = _manifest(root, "waste_lookup", html, ".html", "text/html")

            results, reports = materialize_local_operator(
                "ascit", [_municipality("ascit")], manifest, root, RETRIEVED_AT,
            )

        waste = next(record for record in results["comune-di-prova"] if record["record_type"] == "waste_lookup")
        self.assertEqual("Tetrapak", waste["payload"]["term"])
        self.assertEqual("Multimateriale", waste["payload"]["destination_raw"])
        self.assertEqual("resolved", waste["payload"]["resolution_status"])
        self.assertEqual(1, reports[0]["records_by_type"]["waste_lookup"])

    def test_materializes_lunigiana_ajax_dictionary(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            content = json.dumps({"items": [["Acciaio", "Metallo", "Centro di raccolta"]], "errors": []})
            manifest = _manifest(root, "waste_lookup_json", content, ".json", "application/json")

            results, _ = materialize_local_operator(
                "lunigiana-ambiente", [_municipality("lunigiana-ambiente")], manifest, root, RETRIEVED_AT,
            )

        waste = next(record for record in results["comune-di-prova"] if record["record_type"] == "waste_lookup")
        self.assertEqual("Centro di raccolta", waste["payload"]["destination_raw"])
        self.assertEqual("Categoria pubblicata: Metallo", waste["payload"]["instructions_raw"])

    def test_asmiu_index_does_not_invent_destinations(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            html = '<main><select id="rid"><option value="591">Abat-jour</option></select></main>'
            manifest = _manifest(root, "waste_lookup", html, ".html", "text/html")

            results, _ = materialize_local_operator(
                "asmiu", [_municipality("asmiu")], manifest, root, RETRIEVED_AT,
            )

        waste = next(record for record in results["comune-di-prova"] if record["record_type"] == "waste_lookup")
        self.assertIsNone(waste["payload"]["destination_raw"])
        self.assertEqual("source_detail_not_acquired", waste["payload"]["resolution_status"])
        self.assertEqual("medium", waste["confidence"])
