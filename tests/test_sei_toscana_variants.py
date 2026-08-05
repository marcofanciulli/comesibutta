from __future__ import annotations

from datetime import datetime
from pathlib import Path
import unittest

from dovelobutto.registry import extract_sei_municipality_registry, read_istat_municipalities
from dovelobutto.sei_toscana import MunicipalityContext, extract_municipality_bundle


FIXTURES = Path(__file__).parent / "fixtures" / "sei_toscana"
RETRIEVED_AT = datetime.fromisoformat("2026-08-05T11:00:00+02:00")


def extract(slug: str, name: str, istat: str, page_names: tuple[str, ...]):
    pages = [
        (
            f"https://seitoscana.it/comuni/{slug}/{page_name}",
            (FIXTURES / slug / f"{page_name}.html").read_text(encoding="utf-8"),
        )
        for page_name in page_names
    ]
    return extract_municipality_bundle(
        context=MunicipalityContext(name, istat, slug),
        retrieved_at=RETRIEVED_AT,
        pages=pages,
    )


class CastagnetoExtractorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.records, cls.warnings = extract(
            "castagneto-carducci",
            "Castagneto Carducci",
            "049006",
            ("raccolta-rifiuti", "centri-di-raccolta", "ritiro-ingombranti"),
        )

    def records_of_type(self, record_type: str):
        return [record for record in self.records if record["record_type"] == record_type]

    def test_extracts_three_distinct_door_to_door_zones(self) -> None:
        zones = {record["payload"]["name"] for record in self.records_of_type("service_zone")}
        self.assertIn("ZONA A - Bolgheri, Marina di Castagneto e Donoratico", zones)
        self.assertIn("ZONA B - Castagneto Carducci e Donoratico", zones)
        self.assertIn("ZONA C - Donoratico", zones)
        schedules = self.records_of_type("collection_schedule")
        self.assertEqual(12, len(schedules))

    def test_extracts_temporary_green_waste_area(self) -> None:
        points = self.records_of_type("collection_point")
        temporary = [point for point in points if point["payload"]["point_type"] == "temporary"]
        self.assertEqual(1, len(temporary))
        self.assertEqual("via del Seggio, Marina di Castagneto Carducci", temporary[0]["payload"]["address_raw"])
        self.assertIn("lunedì, venerdì e sabato", temporary[0]["payload"]["opening_hours_raw"])

    def test_facility_has_stable_name_based_identity(self) -> None:
        facility = self.records_of_type("facility")[0]
        self.assertEqual(
            "sei-toscana:castagneto-carducci:facility:centro-di-raccolta-castagneto-carducci",
            facility["natural_key"],
        )


class SienaExtractorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.records, cls.warnings = extract(
            "siena",
            "Siena",
            "052032",
            ("raccolta-rifiuti", "centro-di-raccolta", "ritiro-ingombranti"),
        )

    def records_of_type(self, record_type: str):
        return [record for record in self.records if record["record_type"] == record_type]

    def test_assigns_each_table_to_its_zone(self) -> None:
        zones = self.records_of_type("service_zone")
        self.assertEqual(9, len(zones))
        pispini = next(record for record in zones if record["payload"]["name"] == "Fuori Porta Pispini")
        self.assertEqual("2026-03-02", pispini["validity"]["valid_from"])
        self.assertFalse(pispini["validity"]["inferred"])

    def test_extracts_explicit_glass_calendars(self) -> None:
        schedules = self.records_of_type("collection_schedule")
        date_lists = [
            record for record in schedules
            if record["payload"]["events"] and record["payload"]["events"][0]["kind"] == "date_list"
        ]
        self.assertEqual(2, len(date_lists))
        self.assertEqual(22, len(date_lists[0]["payload"]["events"][0]["dates"]))

    def test_separates_stream_from_bag_or_bin(self) -> None:
        rule = next(
            record for record in self.records_of_type("collection_rule")
            if record["payload"]["zone_ref"].endswith(":fuori-porta-pispini")
            and record["payload"]["stream_name"] == "Carta e cartone"
        )
        self.assertEqual("sacco", rule["payload"]["container_type"])
        self.assertEqual("paper_bag", rule["payload"]["presentation"]["mode"])

    def test_extracts_special_points_and_ecosites(self) -> None:
        points = self.records_of_type("collection_point")
        self.assertEqual(20, len(points))
        ecosites = [point for point in points if point["payload"]["point_type"] == "container_station"]
        self.assertEqual(2, len(ecosites))
        self.assertTrue(all(point["payload"]["access_credential"] == "6Card" for point in ecosites))


class IntermunicipalAccessTest(unittest.TestCase):
    def test_sassetta_points_to_castagneto_facility(self) -> None:
        records, warnings = extract(
            "sassetta",
            "Sassetta",
            "049019",
            ("centro-di-raccolta",),
        )
        self.assertEqual([], warnings)
        self.assertEqual(1, len(records))
        access = records[0]
        self.assertEqual("facility_access", access["record_type"])
        self.assertEqual("istat:049019", access["payload"]["municipality_ref"])
        self.assertEqual(
            "sei-toscana:castagneto-carducci:facility:centro-di-raccolta-castagneto-carducci",
            access["payload"]["facility_ref"],
        )


class CampigliaMarittimaExtractorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.records, cls.warnings = extract(
            "campiglia-marittima",
            "Campiglia Marittima",
            "049002",
            ("raccolta-rifiuti", "centro-di-raccolta", "ritiro-ingombranti"),
        )

    def records_of_type(self, record_type: str):
        return [record for record in self.records if record["record_type"] == record_type]

    def test_extracts_two_seasonal_opening_periods(self) -> None:
        periods = self.records_of_type("opening_period")
        self.assertEqual(2, len(periods))
        ranges = {
            (record["payload"]["start_month_day"], record["payload"]["end_month_day"])
            for record in periods
        }
        self.assertEqual({("06-01", "09-15"), ("09-16", "05-31")}, ranges)
        self.assertTrue(all(record["payload"]["weekly_intervals"] for record in periods))

    def test_extracts_facility_acceptances_and_collection_rules(self) -> None:
        self.assertEqual(1, len(self.records_of_type("facility")))
        self.assertGreater(len(self.records_of_type("facility_acceptance")), 20)
        self.assertGreater(len(self.records_of_type("collection_rule")), 5)
        self.assertEqual([], self.warnings)


class MunicipalityRegistryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        workspace = Path(__file__).parents[1]
        cls.records, cls.warnings = extract_sei_municipality_registry(
            html=(FIXTURES / "index" / "comuni.html").read_text(encoding="utf-8"),
            url="https://seitoscana.it/comuni",
            retrieved_at=RETRIEVED_AT,
            istat_by_name=read_istat_municipalities(
                workspace / "data" / "sources" / "istat" / "toscana-comuni-2026-02-21.csv"
            ),
        )

    def test_matches_all_sei_municipalities_to_istat(self) -> None:
        self.assertEqual(104, len(self.records))
        self.assertEqual([], self.warnings)
        counts: dict[str, int] = {}
        for record in self.records:
            province = record["payload"]["province_code"]
            counts[province] = counts.get(province, 0) + 1
        self.assertEqual({"AR": 35, "GR": 28, "LI": 6, "SI": 35}, counts)

    def test_keeps_service_entry_points(self) -> None:
        campiglia = next(record for record in self.records if record["payload"]["name"] == "Campiglia Marittima")
        self.assertEqual("049002", campiglia["payload"]["istat_code"])
        self.assertEqual("campiglia-marittima", campiglia["payload"]["source_slug"])
        self.assertEqual(
            ["https://seitoscana.it/comuni/campiglia-marittima/centro-di-raccolta"],
            campiglia["payload"]["service_urls"]["facilities"],
        )


if __name__ == "__main__":
    unittest.main()
