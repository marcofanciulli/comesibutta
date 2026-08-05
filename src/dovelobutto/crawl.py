from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import time
from typing import Any, Callable, Iterable
from urllib.error import HTTPError
from urllib.parse import urldefrag, urljoin, urlparse
from urllib import robotparser
from urllib.request import Request, urlopen

from .html import parse_html


@dataclass(frozen=True)
class CrawlJob:
    municipality: str
    istat_code: str
    slug: str
    category: str
    url: str


@dataclass(frozen=True)
class FetchResult:
    status: int
    final_url: str
    content: bytes | None
    content_type: str | None = None
    etag: str | None = None
    last_modified: str | None = None


Fetcher = Callable[[CrawlJob, str | None, str | None], FetchResult]


class RobotsAccessError(PermissionError):
    def __init__(self, robots_url: str, blocked_urls: list[str]) -> None:
        self.robots_url = robots_url
        self.blocked_urls = blocked_urls
        super().__init__(f"robots.txt blocks {len(blocked_urls)} initial URL(s)")


def read_registry_jobs(path: Path) -> list[CrawlJob]:
    jobs: list[CrawlJob] = []
    seen: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)["payload"]
        for category in ("collection", "facilities"):
            for url in payload["service_urls"].get(category, []):
                url = _canonical_url(url)
                if url in seen:
                    continue
                seen.add(url)
                jobs.append(CrawlJob(
                    municipality=payload["name"],
                    istat_code=payload["istat_code"],
                    slug=payload["source_slug"],
                    category=category,
                    url=url,
                ))
    return jobs


class SnapshotStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def save(self, job: CrawlJob, content: bytes, observed_at: datetime) -> tuple[str, Path, bool]:
        digest = hashlib.sha256(content).hexdigest()
        relative = (
            Path(observed_at.date().isoformat())
            / job.slug
            / f"{job.category}-{digest[:16]}.html"
        )
        destination = self.root / relative
        created = not destination.exists()
        if created:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)
        return digest, destination, created


class CrawlState:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.documents: dict[str, dict[str, Any]] = {}
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            self.documents = data.get("documents", {})

    def get(self, url: str) -> dict[str, Any]:
        return self.documents.get(url, {})

    def put(self, url: str, value: dict[str, Any]) -> None:
        self.documents[url] = value

    def save(self, updated_at: datetime) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps({
            "version": 1,
            "updated_at": updated_at.isoformat(),
            "documents": self.documents,
        }, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(self.path)


class SweepRunner:
    def __init__(self, snapshot_store: SnapshotStore, state: CrawlState) -> None:
        self.snapshot_store = snapshot_store
        self.state = state

    def run(
        self,
        jobs: Iterable[CrawlJob],
        fetcher: Fetcher,
        observed_at: datetime,
        max_pages: int | None = None,
    ) -> dict[str, Any]:
        queue = list(jobs)
        selected_istat = {job.istat_code for job in queue}
        for document in self.state.documents.values():
            if (
                document.get("istat_code") in selected_istat
                and document.get("category") == "pickup"
                and document.get("url")
            ):
                queue.append(CrawlJob(
                    municipality=document["municipality"],
                    istat_code=document["istat_code"],
                    slug=document["slug"],
                    category=document["category"],
                    url=document["url"],
                ))
        queued_urls = {job.url for job in queue}
        completed_urls: set[str] = set()
        results: list[dict[str, Any]] = []
        while queue and (max_pages is None or len(results) < max_pages):
            job = queue.pop(0)
            if _canonical_url(job.url) in completed_urls:
                continue
            previous = self.state.get(job.url)
            try:
                response = fetcher(job, previous.get("etag"), previous.get("last_modified"))
                result, discovered = self._handle_response(job, response, previous, observed_at)
                completed_urls.add(_canonical_url(job.url))
                final_url = result.get("final_url")
                if final_url:
                    canonical_final = _canonical_url(final_url)
                    queued_urls.add(canonical_final)
                    completed_urls.add(canonical_final)
                for discovered_job in discovered:
                    if discovered_job.url not in queued_urls:
                        queued_urls.add(discovered_job.url)
                        queue.append(discovered_job)
            except Exception as error:
                result = self._failure(job, error, previous, observed_at)
                completed_urls.add(_canonical_url(job.url))
            results.append(result)
            self.state.save(observed_at)
        report = self._report(results, queue, observed_at)
        return report

    def _handle_response(
        self,
        job: CrawlJob,
        response: FetchResult,
        previous: dict[str, Any],
        observed_at: datetime,
    ) -> tuple[dict[str, Any], list[CrawlJob]]:
        base = self._state_base(job, observed_at)
        if response.status == 304:
            value = {
                **previous,
                **base,
                "status": "not_modified",
                "http_status": 304,
                "error": None,
            }
            self.state.put(job.url, value)
            return value, []
        if response.status != 200 or response.content is None:
            value = {
                **previous,
                **base,
                "status": "http_error",
                "http_status": response.status,
                "final_url": response.final_url,
                "error": f"HTTP {response.status}",
            }
            self.state.put(job.url, value)
            return value, []
        digest, snapshot_path, created = self.snapshot_store.save(job, response.content, observed_at)
        changed = digest != previous.get("content_sha256")
        value = {
            **base,
            "status": "new" if changed else "unchanged",
            "http_status": response.status,
            "final_url": response.final_url,
            "content_type": response.content_type,
            "etag": response.etag,
            "last_modified": response.last_modified,
            "content_sha256": digest,
            "snapshot_path": str(snapshot_path),
            "snapshot_created": created,
            "error": None,
        }
        self.state.put(job.url, value)
        html = response.content.decode("utf-8", errors="replace")
        return value, discover_municipality_jobs(job, html, response.final_url)

    def _failure(
        self,
        job: CrawlJob,
        error: Exception,
        previous: dict[str, Any],
        observed_at: datetime,
    ) -> dict[str, Any]:
        value = {
            **previous,
            **self._state_base(job, observed_at),
            "status": "failed",
            "error": f"{type(error).__name__}: {error}",
        }
        self.state.put(job.url, value)
        return value

    @staticmethod
    def _state_base(job: CrawlJob, observed_at: datetime) -> dict[str, Any]:
        return {
            "municipality": job.municipality,
            "istat_code": job.istat_code,
            "slug": job.slug,
            "category": job.category,
            "url": job.url,
            "last_checked_at": observed_at.isoformat(),
        }

    @staticmethod
    def _report(
        results: list[dict[str, Any]], remaining: list[CrawlJob], observed_at: datetime
    ) -> dict[str, Any]:
        by_status: dict[str, int] = {}
        by_category: dict[str, int] = {}
        municipalities: set[str] = set()
        for result in results:
            by_status[result["status"]] = by_status.get(result["status"], 0) + 1
            by_category[result["category"]] = by_category.get(result["category"], 0) + 1
            municipalities.add(result["istat_code"])
        return {
            "observed_at": observed_at.isoformat(),
            "pages_checked": len(results),
            "pages_remaining": len(remaining),
            "municipalities_touched": len(municipalities),
            "pages_by_status": by_status,
            "pages_by_category": by_category,
            "errors": [
                {"url": result["url"], "status": result["status"], "error": result.get("error")}
                for result in results
                if result["status"] in {"failed", "http_error"}
            ],
        }


def discover_municipality_jobs(job: CrawlJob, html: str, final_url: str) -> list[CrawlJob]:
    root = parse_html(html)
    prefix = f"/comuni/{job.slug}/"
    discovered: list[CrawlJob] = []
    seen: set[str] = set()
    for link in root.find_all(lambda element: element.tag == "a"):
        href = link.attrs.get("href", "")
        absolute = _canonical_url(urljoin(final_url, href))
        path = urlparse(absolute).path.rstrip("/")
        if not path.startswith(prefix):
            continue
        category = _linked_category(path)
        if not category or absolute in seen:
            continue
        seen.add(absolute)
        discovered.append(CrawlJob(
            municipality=job.municipality,
            istat_code=job.istat_code,
            slug=job.slug,
            category=category,
            url=absolute,
        ))
    return discovered


def _linked_category(path: str) -> str | None:
    if path.endswith("/raccolta-rifiuti"):
        return "collection"
    if re.search(r"/centr[oi]-di-raccolta$", path):
        return "facilities"
    if path.endswith("/ritiro-ingombranti"):
        return "pickup"
    return None


def _canonical_url(url: str) -> str:
    without_fragment, _ = urldefrag(url)
    return without_fragment.rstrip("/")


class HttpFetcher:
    def __init__(self, user_agent: str, delay_seconds: float = 1.0) -> None:
        self.user_agent = user_agent
        self.delay_seconds = delay_seconds
        self._last_request_at: float | None = None
        self._robots: robotparser.RobotFileParser | None = None

    def _load_robots(self) -> robotparser.RobotFileParser:
        if self._robots is not None:
            return self._robots
        robots_url = "https://seitoscana.it/robots.txt"
        request = Request(robots_url, headers={"User-Agent": self.user_agent, "Accept": "text/plain"})
        with urlopen(request, timeout=30) as response:
            lines = response.read().decode("utf-8").splitlines()
        robots = robotparser.RobotFileParser(robots_url)
        robots.parse(lines)
        crawl_delay = robots.crawl_delay(self.user_agent) or robots.crawl_delay("*")
        if crawl_delay is not None:
            self.delay_seconds = max(self.delay_seconds, float(crawl_delay))
        self._robots = robots
        return robots

    def validate(self, jobs: Iterable[CrawlJob]) -> dict[str, Any]:
        jobs = list(jobs)
        robots = self._load_robots()
        blocked = [job.url for job in jobs if not robots.can_fetch(self.user_agent, job.url)]
        if blocked:
            raise RobotsAccessError(robots.url, blocked)
        return {
            "robots_url": robots.url,
            "initial_urls_checked": len(jobs),
            "allowed": True,
            "crawl_delay_seconds": self.delay_seconds,
        }

    def __call__(self, job: CrawlJob, etag: str | None, last_modified: str | None) -> FetchResult:
        if not self._load_robots().can_fetch(self.user_agent, job.url):
            raise PermissionError(f"robots.txt does not allow {job.url}")
        if self._last_request_at is not None:
            elapsed = time.monotonic() - self._last_request_at
            if elapsed < self.delay_seconds:
                time.sleep(self.delay_seconds - elapsed)
        headers = {"User-Agent": self.user_agent, "Accept": "text/html"}
        if etag:
            headers["If-None-Match"] = etag
        if last_modified:
            headers["If-Modified-Since"] = last_modified
        request = Request(job.url, headers=headers)
        try:
            with urlopen(request, timeout=30) as response:
                content = response.read()
                return FetchResult(
                    status=response.status,
                    final_url=response.geturl(),
                    content=content,
                    content_type=response.headers.get("Content-Type"),
                    etag=response.headers.get("ETag"),
                    last_modified=response.headers.get("Last-Modified"),
                )
        except HTTPError as error:
            if error.code == 304:
                return FetchResult(304, job.url, None)
            return FetchResult(error.code, error.geturl(), None)
        finally:
            self._last_request_at = time.monotonic()


class FixtureFetcher:
    def __init__(self, root: Path) -> None:
        self.root = root

    def __call__(self, job: CrawlJob, etag: str | None, last_modified: str | None) -> FetchResult:
        candidates = {
            "collection": ("raccolta-rifiuti.html",),
            "facilities": ("centro-di-raccolta.html", "centri-di-raccolta.html"),
            "pickup": ("ritiro-ingombranti.html",),
        }.get(job.category, ())
        for filename in candidates:
            path = self.root / job.slug / filename
            if path.exists():
                final_url = job.url
                if filename == "centri-di-raccolta.html":
                    final_url = re.sub(r"/centro-di-raccolta$", "/centri-di-raccolta", final_url)
                return FetchResult(200, final_url, path.read_bytes(), "text/html; charset=utf-8")
        return FetchResult(404, job.url, None, "text/html")
