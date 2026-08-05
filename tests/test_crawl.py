from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from dovelobutto.crawl import (
    CrawlState,
    FixtureFetcher,
    HttpFetcher,
    RobotsAccessError,
    SnapshotStore,
    SweepRunner,
    discover_municipality_jobs,
    read_registry_jobs,
)
from dovelobutto.cli import _read_selection_file


WORKSPACE = Path(__file__).parents[1]
REGISTRY = WORKSPACE / "outputs" / "sei-toscana-municipalities.jsonl"
FIXTURES = Path(__file__).parent / "fixtures" / "sei_toscana"
OBSERVED_AT = datetime.fromisoformat("2026-08-05T13:00:00+02:00")


class SweepRunnerTest(unittest.TestCase):
    def test_http_fetcher_preflights_all_initial_urls_against_robots(self) -> None:
        jobs = [job for job in read_registry_jobs(REGISTRY) if job.slug == "manciano"]

        class RobotsResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return b"User-agent: *\nAllow: /comuni/\nDisallow: /area-riservata/\n"

        with patch("dovelobutto.crawl.urlopen", return_value=RobotsResponse()):
            result = HttpFetcher("DoveLoButtoData/0.1 (+mailto:test@example.com)").validate(jobs)
        self.assertTrue(result["allowed"])
        self.assertEqual(2, result["initial_urls_checked"])

    def test_robots_preflight_reports_every_blocked_url(self) -> None:
        jobs = [job for job in read_registry_jobs(REGISTRY) if job.slug == "manciano"]

        class RobotsResponse:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return b"User-agent: *\nDisallow: /comuni/\n"

        with patch("dovelobutto.crawl.urlopen", return_value=RobotsResponse()):
            with self.assertRaises(RobotsAccessError) as raised:
                HttpFetcher("DoveLoButtoData/0.1 (+mailto:test@example.com)").validate(jobs)
        self.assertEqual([job.url for job in jobs], raised.exception.blocked_urls)

    def test_batch_file_ignores_comments_and_blank_lines(self) -> None:
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "batch.txt"
            path.write_text("# lotto\n\nmanciano\n  grosseto  \n", encoding="utf-8")
            self.assertEqual({"manciano", "grosseto"}, _read_selection_file(path))

    def test_registry_creates_two_authoritative_jobs_per_municipality(self) -> None:
        jobs = read_registry_jobs(REGISTRY)
        self.assertEqual(208, len(jobs))
        self.assertEqual({"collection", "facilities"}, {job.category for job in jobs})

    def test_discovers_pickup_only_inside_the_same_municipality(self) -> None:
        job = next(job for job in read_registry_jobs(REGISTRY) if job.slug == "manciano")
        html = (FIXTURES / "manciano" / "raccolta-rifiuti.html").read_text(encoding="utf-8")
        discovered = discover_municipality_jobs(job, html, job.url)
        pickup = [item for item in discovered if item.category == "pickup"]
        self.assertEqual(1, len(pickup))
        self.assertEqual(
            "https://seitoscana.it/comuni/manciano/ritiro-ingombranti",
            pickup[0].url,
        )

    def test_sweep_is_resumable_and_deduplicates_snapshots(self) -> None:
        jobs = [job for job in read_registry_jobs(REGISTRY) if job.slug == "manciano"]
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            state = CrawlState(root / "state.json")
            runner = SweepRunner(SnapshotStore(root / "snapshots"), state)
            first = runner.run(jobs, FixtureFetcher(FIXTURES), OBSERVED_AT)
            self.assertEqual(3, first["pages_checked"])
            self.assertEqual({"new": 3}, first["pages_by_status"])
            snapshots = list((root / "snapshots").rglob("*.html"))
            self.assertEqual(3, len(snapshots))

            second = runner.run(jobs, FixtureFetcher(FIXTURES), OBSERVED_AT)
            self.assertEqual({"unchanged": 3}, second["pages_by_status"])
            self.assertEqual(snapshots, list((root / "snapshots").rglob("*.html")))
            persisted = json.loads((root / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(3, len(persisted["documents"]))

    def test_redirected_facility_url_is_not_crawled_twice(self) -> None:
        jobs = [job for job in read_registry_jobs(REGISTRY) if job.slug == "castagneto-carducci"]
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            report = SweepRunner(
                SnapshotStore(root / "snapshots"), CrawlState(root / "state.json")
            ).run(jobs, FixtureFetcher(FIXTURES), OBSERVED_AT)
            self.assertEqual(3, report["pages_checked"])
            self.assertEqual({"collection": 1, "facilities": 1, "pickup": 1}, report["pages_by_category"])


if __name__ == "__main__":
    unittest.main()
