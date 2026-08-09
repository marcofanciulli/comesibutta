from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from dovelobutto.missing_queries import MissingQueryStore


class MissingQueryStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.database = Path(self.temporary.name) / "missing.sqlite"
        self.store = MissingQueryStore(self.database)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_repeated_query_is_aggregated_without_user_identifiers(self) -> None:
        first = datetime(2026, 8, 9, 10, 0, tzinfo=timezone.utc)
        second = datetime(2026, 8, 9, 11, 0, tzinfo=timezone.utc)
        self.store.record(
            "  Una Cosa Misteriosa  ", municipality_istat="053014",
            zone_id=None, user_type="domestic", dataset_revision=7,
            reason="unknown_term", observed_at=first,
        )
        self.store.record(
            "una cosa misteriosa", municipality_istat="053014",
            zone_id=None, user_type="domestic", dataset_revision=8,
            reason="unknown_term", observed_at=second,
        )

        report = self.store.report()

        self.assertEqual(1, len(report["entries"]))
        entry = report["entries"][0]
        self.assertEqual("una cosa misteriosa", entry["normalized_query"])
        self.assertEqual(2, entry["occurrence_count"])
        self.assertEqual(7, entry["first_dataset_revision"])
        self.assertEqual(8, entry["last_dataset_revision"])
        self.assertFalse(report["privacy"]["stores_ip"])
        self.assertNotIn("user_id", entry)

    def test_territorial_contexts_are_aggregated_separately(self) -> None:
        for municipality in ("053014", "053011"):
            self.store.record(
                "Oggetto locale", municipality_istat=municipality,
                zone_id=None, user_type="domestic", dataset_revision=1,
                reason="unknown_term",
            )
        self.assertEqual(2, len(self.store.report()["entries"]))

    def test_privacy_filter_rejects_contact_details_and_urls(self) -> None:
        for text in (
            "scrivi a nome@example.it", "guarda https://example.it",
            "telefono 3331234567",
        ):
            result = self.store.record(
                text, municipality_istat="053014", zone_id=None,
                user_type="domestic", dataset_revision=1,
                reason="unknown_term",
            )
            self.assertFalse(result["recorded"])
        self.assertEqual([], self.store.report()["entries"])

    def test_editorial_status_closes_the_review_cycle(self) -> None:
        result = self.store.record(
            "Oggetto da valutare", municipality_istat="053014", zone_id=None,
            user_type="domestic", dataset_revision=1, reason="unknown_term",
        )

        updated = self.store.set_review_status(
            result["fingerprint"], "accepted", "Aggiungere sinonimo revisionato",
        )

        self.assertTrue(updated)
        entry = self.store.report()["entries"][0]
        self.assertEqual("accepted", entry["review_status"])
        self.assertEqual("Aggiungere sinonimo revisionato", entry["review_note"])


if __name__ == "__main__":
    unittest.main()
