from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
import time
from typing import Any
from urllib import robotparser
from urllib.request import Request, urlopen

from .crawl import CrawlState, FixtureFetcher, HttpFetcher, SnapshotStore, SweepRunner, read_registry_jobs
from .records import write_jsonl
from .registry import extract_sei_municipality_registry, read_istat_municipalities
from .sei_toscana import MunicipalityContext, extract_municipality_bundle


PAGE_NAMES = ("raccolta-rifiuti", "centro-di-raccolta", "centri-di-raccolta", "ritiro-ingombranti")


def _read_fixture_pages(directory: Path, slug: str) -> list[tuple[str, str]]:
    pages = []
    for page_name in PAGE_NAMES:
        path = directory / f"{page_name}.html"
        if path.exists():
            pages.append((f"https://seitoscana.it/comuni/{slug}/{page_name}", path.read_text(encoding="utf-8")))
    return pages


def _download_pages(slug: str, user_agent: str) -> list[tuple[str, str]]:
    robots_url = "https://seitoscana.it/robots.txt"
    robots_request = Request(robots_url, headers={"User-Agent": user_agent, "Accept": "text/plain"})
    with urlopen(robots_request, timeout=30) as response:
        robots_lines = response.read().decode("utf-8").splitlines()
    robots = robotparser.RobotFileParser(robots_url)
    robots.parse(robots_lines)
    delay = robots.crawl_delay(user_agent) or robots.crawl_delay("*") or 1.0
    pages = []
    for page_name in ("raccolta-rifiuti", "centro-di-raccolta", "ritiro-ingombranti"):
        url = f"https://seitoscana.it/comuni/{slug}/{page_name}"
        if not robots.can_fetch(user_agent, url):
            print(f"warning: robots.txt does not allow {url}", file=sys.stderr)
            continue
        request = Request(url, headers={"User-Agent": user_agent, "Accept": "text/html"})
        try:
            with urlopen(request, timeout=30) as response:
                pages.append((response.geturl(), response.read().decode("utf-8")))
        except Exception as error:
            print(f"warning: unable to fetch {url}: {error}", file=sys.stderr)
        time.sleep(delay)
    return pages


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dove-lo-butto")
    subparsers = parser.add_subparsers(dest="command", required=True)
    scrape = subparsers.add_parser("scrape-sei", help="Extract normalized records from SEI Toscana pages")
    scrape.add_argument("--municipality", required=True)
    scrape.add_argument("--istat", required=True)
    scrape.add_argument("--slug", required=True)
    scrape.add_argument("--retrieved-at", required=True)
    scrape.add_argument("--fixture-dir", type=Path)
    scrape.add_argument("--output", type=Path, required=True)
    scrape.add_argument("--report", type=Path, required=True)
    scrape.add_argument(
        "--user-agent",
        help="Identifiable crawler user-agent with a project contact; required for live downloads",
    )
    registry = subparsers.add_parser(
        "build-sei-registry",
        help="Join the SEI municipality index with the official ISTAT registry",
    )
    registry.add_argument("--index-html", type=Path, required=True)
    registry.add_argument("--istat-csv", type=Path, required=True)
    registry.add_argument("--retrieved-at", required=True)
    registry.add_argument("--output", type=Path, required=True)
    registry.add_argument("--report", type=Path, required=True)
    sweep = subparsers.add_parser(
        "sweep-sei",
        help="Run a resumable and rate-limited sweep from the SEI municipality registry",
    )
    sweep.add_argument("--registry", type=Path, required=True)
    sweep.add_argument("--snapshot-root", type=Path, required=True)
    sweep.add_argument("--state", type=Path, required=True)
    sweep.add_argument("--report", type=Path, required=True)
    sweep.add_argument("--output-dir", type=Path, required=True)
    sweep.add_argument("--observed-at", required=True)
    sweep.add_argument("--municipality", action="append", dest="municipalities")
    sweep.add_argument("--max-pages", type=int)
    sweep.add_argument("--delay", type=float, default=1.0)
    sweep.add_argument("--fixture-root", type=Path)
    sweep.add_argument(
        "--user-agent",
        help="Identifiable crawler user-agent with a project contact; required for live sweeps",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "sweep-sei":
        observed_at = datetime.fromisoformat(args.observed_at)
        jobs = read_registry_jobs(args.registry)
        if args.municipalities:
            selected = set(args.municipalities)
            jobs = [job for job in jobs if job.slug in selected or job.istat_code in selected]
        if not args.fixture_root and not args.user_agent:
            print("error: --user-agent is required for live sweeps", file=sys.stderr)
            return 2
        fetcher = (
            FixtureFetcher(args.fixture_root)
            if args.fixture_root
            else HttpFetcher(args.user_agent, args.delay)
        )
        state = CrawlState(args.state)
        selected_istat = {job.istat_code for job in jobs}
        report = SweepRunner(SnapshotStore(args.snapshot_root), state).run(
            jobs=jobs,
            fetcher=fetcher,
            observed_at=observed_at,
            max_pages=args.max_pages,
        )
        report["extraction"] = _materialize_sweep(
            state, args.output_dir, observed_at, selected_istat
        )
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return 0 if not report["errors"] else 1
    if args.command == "build-sei-registry":
        html = args.index_html.read_text(encoding="utf-8")
        records, warnings = extract_sei_municipality_registry(
            html=html,
            url="https://seitoscana.it/comuni",
            retrieved_at=datetime.fromisoformat(args.retrieved_at),
            istat_by_name=read_istat_municipalities(args.istat_csv),
        )
        write_jsonl(args.output, records)
        province_counts: dict[str, int] = {}
        service_page_counts = {
            "collection": 0,
            "facilities": 0,
            "pickup": 0,
            "street_cleaning": 0,
            "other": 0,
        }
        for record in records:
            province = record["payload"]["province_code"]
            province_counts[province] = province_counts.get(province, 0) + 1
            for category, urls in record["payload"]["service_urls"].items():
                if urls:
                    service_page_counts[category] += 1
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps({
            "source_url": "https://seitoscana.it/comuni",
            "municipalities": len(records),
            "municipalities_by_province": province_counts,
            "municipalities_with_service_pages": service_page_counts,
            "warnings": warnings,
        }, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return 0 if records and not warnings else 1
    context = MunicipalityContext(args.municipality, args.istat, args.slug)
    retrieved_at = datetime.fromisoformat(args.retrieved_at)
    if not args.fixture_dir and not args.user_agent:
        print("error: --user-agent is required for live downloads", file=sys.stderr)
        return 2
    pages = (
        _read_fixture_pages(args.fixture_dir, args.slug)
        if args.fixture_dir
        else _download_pages(args.slug, args.user_agent)
    )
    records, warnings = extract_municipality_bundle(
        context=context,
        retrieved_at=retrieved_at,
        pages=pages,
    )
    write_jsonl(args.output, records)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    for record in records:
        counts[record["record_type"]] = counts.get(record["record_type"], 0) + 1
    args.report.write_text(json.dumps({
        "municipality": args.municipality,
        "istat_code": args.istat,
        "pages_processed": len(pages),
        "records": len(records),
        "records_by_type": counts,
        "warnings": warnings,
    }, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0 if pages else 1


def _materialize_sweep(
    state: CrawlState,
    output_dir: Path,
    observed_at: datetime,
    selected_istat: set[str] | None = None,
) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for document in state.documents.values():
        snapshot = document.get("snapshot_path")
        if (
            snapshot
            and document.get("category") in {"collection", "facilities", "pickup"}
            and (selected_istat is None or document.get("istat_code") in selected_istat)
        ):
            grouped.setdefault(document["istat_code"], []).append(document)
    municipalities: list[dict[str, Any]] = []
    total_records = 0
    total_warnings = 0
    for istat_code, documents in sorted(grouped.items()):
        first = documents[0]
        pages = [
            (
                document.get("final_url") or document["url"],
                Path(document["snapshot_path"]).read_text(encoding="utf-8"),
            )
            for document in documents
        ]
        records, warnings = extract_municipality_bundle(
            context=MunicipalityContext(first["municipality"], istat_code, first["slug"]),
            retrieved_at=observed_at,
            pages=pages,
        )
        output_dir.mkdir(parents=True, exist_ok=True)
        write_jsonl(output_dir / f"{first['slug']}-acquisition.jsonl", records)
        counts: dict[str, int] = {}
        for record in records:
            counts[record["record_type"]] = counts.get(record["record_type"], 0) + 1
        municipality_report = {
            "municipality": first["municipality"],
            "istat_code": istat_code,
            "pages_available": len(pages),
            "records": len(records),
            "records_by_type": counts,
            "warnings": warnings,
        }
        (output_dir / f"{first['slug']}-report.json").write_text(
            json.dumps(municipality_report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        municipalities.append(municipality_report)
        total_records += len(records)
        total_warnings += len(warnings)
    return {
        "municipalities": len(municipalities),
        "records": total_records,
        "warnings": total_warnings,
        "municipality_reports": municipalities,
    }


if __name__ == "__main__":
    raise SystemExit(main())
