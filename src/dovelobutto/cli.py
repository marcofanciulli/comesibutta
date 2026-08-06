from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import sys
import time
import string
from typing import Any
from urllib import robotparser
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .crawl import (
    CrawlState,
    FixtureFetcher,
    HttpFetcher,
    RobotsAccessError,
    SnapshotStore,
    SweepRunner,
    read_registry_jobs,
)
from .ato_costa import (
    MunicipalityContext as CostaMunicipalityContext,
    extract_aamps_waste_lookup,
    extract_esa_bundle,
    extract_rea_waste_lookup,
)
from .html import clean_text, parse_html
from .records import write_jsonl
from .registry import (
    extract_ato_costa_municipality_registry,
    extract_sei_municipality_registry,
    read_istat_municipalities,
)
from .sei_toscana import (
    MunicipalityContext,
    build_eer_description_reference,
    extract_municipality_bundle,
    reconcile_eer_records,
)


PAGE_NAMES = ("raccolta-rifiuti", "centro-di-raccolta", "centri-di-raccolta", "ritiro-ingombranti")


def _read_selection_file(path: Path) -> set[str]:
    return {
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }


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
    costa_registry = subparsers.add_parser(
        "build-ato-costa-registry",
        help="Join the official ATO Costa municipality/SOL table with ISTAT",
    )
    costa_registry.add_argument("--assignment-csv", type=Path, required=True)
    costa_registry.add_argument("--istat-csv", type=Path, required=True)
    costa_registry.add_argument("--retrieved-at", required=True)
    costa_registry.add_argument("--output", type=Path, required=True)
    costa_registry.add_argument("--report", type=Path, required=True)
    esa = subparsers.add_parser(
        "materialize-esa",
        help="Extract the shared ESA collection and facility pages for Elba municipalities",
    )
    esa.add_argument("--registry", type=Path, required=True)
    esa.add_argument("--collection-html", type=Path, required=True)
    esa.add_argument("--facilities-html", type=Path, required=True)
    esa.add_argument("--retrieved-at", required=True)
    esa.add_argument("--output-dir", type=Path, required=True)
    esa.add_argument("--report", type=Path, required=True)
    rea_fetch = subparsers.add_parser(
        "fetch-rea-rifiutario",
        help="Fetch the public REA waste dictionary through its read-only AJAX endpoint",
    )
    rea_fetch.add_argument("--output", type=Path, required=True)
    rea_fetch.add_argument("--report", type=Path, required=True)
    rea_fetch.add_argument("--user-agent", required=True)
    rea_fetch.add_argument("--delay", type=float, default=1.0)
    rea = subparsers.add_parser(
        "materialize-rea-rifiutario",
        help="Materialize the shared REA waste dictionary for REA municipalities",
    )
    rea.add_argument("--registry", type=Path, required=True)
    rea.add_argument("--rifiutario-json", type=Path, required=True)
    rea.add_argument("--retrieved-at", required=True)
    rea.add_argument("--output-dir", type=Path, required=True)
    rea.add_argument("--report", type=Path, required=True)
    aamps = subparsers.add_parser(
        "materialize-aamps-rifiutario",
        help="Extract the AAMPS two-column waste guide from pdftotext bbox XHTML",
    )
    aamps.add_argument("--registry", type=Path, required=True)
    aamps.add_argument("--bbox-html", type=Path, required=True)
    aamps.add_argument("--retrieved-at", required=True)
    aamps.add_argument("--output-dir", type=Path, required=True)
    aamps.add_argument("--report", type=Path, required=True)
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
    sweep.add_argument("--municipality-file", type=Path)
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
    if args.command == "materialize-aamps-rifiutario":
        retrieved_at = datetime.fromisoformat(args.retrieved_at)
        bbox_html = args.bbox_html.read_text(encoding="utf-8")
        municipality = next(
            json.loads(line)["payload"]
            for line in args.registry.read_text(encoding="utf-8").splitlines()
            if line.strip()
            and json.loads(line)["payload"].get("local_operator_ref") == "aamps"
        )
        records, warnings = extract_aamps_waste_lookup(
            CostaMunicipalityContext(
                municipality["name"], municipality["istat_code"], municipality["source_slug"]
            ),
            retrieved_at,
            "https://www.aamps.livorno.it/wp-content/uploads/2017/04/Dove-lo-butto_logo-nuovo.pdf",
            bbox_html,
        )
        args.output_dir.mkdir(parents=True, exist_ok=True)
        write_jsonl(args.output_dir / "livorno-acquisition.jsonl", records)
        municipality_report = {
            "municipality": municipality["name"],
            "istat_code": municipality["istat_code"],
            "pages_available": 1,
            "pages_materialized": 1,
            "equivalent_pages": [],
            "records": len(records),
            "records_by_type": {"waste_lookup": len(records)},
            "warnings": warnings,
        }
        (args.output_dir / "livorno-report.json").write_text(
            json.dumps(municipality_report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        report = {
            "observed_at": retrieved_at.isoformat(),
            "pages_checked": 1,
            "pages_remaining": 0,
            "municipalities_touched": 1,
            "pages_by_status": {"snapshot": 1},
            "pages_by_category": {"waste_lookup": 1},
            "errors": [],
            "extraction": {
                "municipalities": 1,
                "records": len(records),
                "warnings": len(warnings),
                "municipality_reports": [municipality_report],
            },
        }
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return 0 if records else 1
    if args.command == "fetch-rea-rifiutario":
        endpoint = "https://www.reaspa.it/wp-admin/admin-ajax.php"
        robots_url = "https://www.reaspa.it/robots.txt"
        robots_request = Request(robots_url, headers={"User-Agent": args.user_agent})
        with urlopen(robots_request, timeout=30) as response:
            robots_lines = response.read().decode("utf-8").splitlines()
        robots = robotparser.RobotFileParser(robots_url)
        robots.parse(robots_lines)
        if not robots.can_fetch(args.user_agent, endpoint):
            report = {
                "source_url": endpoint,
                "robots_url": robots_url,
                "allowed": False,
                "queried_prefixes": [],
                "items": 0,
                "errors": [{"code": "blocked_by_robots", "prefix": None}],
            }
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
            return 1
        items: dict[str, dict[str, Any]] = {}
        errors = []
        empty_prefixes = []
        queried = []
        for prefix in string.ascii_lowercase:
            body = urlencode({
                "action": "rifiutario_ajax",
                "params[action]": "autocomplete-search",
                "params[data][value]": prefix,
            }).encode("ascii")
            request = Request(
                endpoint,
                data=body,
                headers={
                    "User-Agent": args.user_agent,
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json",
                },
            )
            try:
                with urlopen(request, timeout=30) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                queried.append(prefix)
                response_data = payload.get("data") or {}
                result_items = response_data.get("result", []) if isinstance(response_data, dict) else []
                if payload.get("status") == 500 and not result_items:
                    empty_prefixes.append(prefix)
                elif payload.get("status") != 200:
                    errors.append({"code": "api_status", "prefix": prefix, "detail": payload})
                for item in result_items:
                    items[str(item.get("id") or item["name"])] = item
            except Exception as error:
                errors.append({
                    "code": "request_failed",
                    "prefix": prefix,
                    "detail": f"{type(error).__name__}: {error}",
                })
            time.sleep(args.delay)
        result = {
            "source_url": endpoint,
            "queried_prefixes": queried,
            "empty_prefixes": empty_prefixes,
            "items": sorted(items.values(), key=lambda item: item["name"].casefold()),
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps({
            "source_url": endpoint,
            "robots_url": robots_url,
            "allowed": True,
            "queried_prefixes": queried,
            "empty_prefixes": empty_prefixes,
            "items": len(items),
            "errors": errors,
        }, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return 0 if len(queried) == 26 and items and not errors else 1
    if args.command == "materialize-rea-rifiutario":
        retrieved_at = datetime.fromisoformat(args.retrieved_at)
        json_text = args.rifiutario_json.read_text(encoding="utf-8")
        source_data = json.loads(json_text)
        source_url = source_data["source_url"]
        unresolved_entries = sum(not item.get("destination") for item in source_data["items"])
        municipalities = []
        for line in args.registry.read_text(encoding="utf-8").splitlines():
            if line.strip():
                payload = json.loads(line)["payload"]
                if payload.get("local_operator_ref") == "rea":
                    municipalities.append(payload)
        municipality_reports = []
        total_records = 0
        args.output_dir.mkdir(parents=True, exist_ok=True)
        for municipality in municipalities:
            records = extract_rea_waste_lookup(
                CostaMunicipalityContext(
                    municipality["name"], municipality["istat_code"], municipality["source_slug"]
                ),
                retrieved_at,
                source_url,
                json_text,
            )
            write_jsonl(
                args.output_dir / f"{municipality['source_slug']}-acquisition.jsonl", records
            )
            municipality_report = {
                "municipality": municipality["name"],
                "istat_code": municipality["istat_code"],
                "pages_available": 1,
                "pages_materialized": 1,
                "equivalent_pages": [],
                "records": len(records),
                "records_by_type": {"waste_lookup": len(records)},
                "warnings": ([{
                    "code": "waste_lookup_destinations_missing",
                    "detail": f"{unresolved_entries} voci REA non hanno una destinazione pubblicata",
                    "url": source_url,
                }] if unresolved_entries else []),
            }
            (args.output_dir / f"{municipality['source_slug']}-report.json").write_text(
                json.dumps(municipality_report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            municipality_reports.append(municipality_report)
            total_records += len(records)
        report = {
            "observed_at": retrieved_at.isoformat(),
            "pages_checked": 1,
            "pages_remaining": 0,
            "municipalities_touched": len(municipalities),
            "pages_by_status": {"snapshot": 1},
            "pages_by_category": {"waste_lookup": 1},
            "errors": [],
            "extraction": {
                "municipalities": len(municipalities),
                "records": total_records,
                "warnings": len(municipalities) if unresolved_entries else 0,
                "unresolved_entries_per_municipality": unresolved_entries,
                "municipality_reports": municipality_reports,
            },
        }
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return 0 if len(municipalities) == 17 and total_records else 1
    if args.command == "materialize-esa":
        retrieved_at = datetime.fromisoformat(args.retrieved_at)
        pages = [
            (
                "https://www.esaspa.it/cittadini/raccolta-differenziata/",
                args.collection_html.read_text(encoding="utf-8"),
            ),
            (
                "https://www.esaspa.it/centri-di-raccolta/",
                args.facilities_html.read_text(encoding="utf-8"),
            ),
        ]
        municipalities = []
        for line in args.registry.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            payload = json.loads(line)["payload"]
            if payload.get("local_operator_ref") == "esa":
                municipalities.append(payload)
        municipality_reports = []
        total_records = 0
        total_warnings = 0
        args.output_dir.mkdir(parents=True, exist_ok=True)
        for municipality in municipalities:
            records, warnings = extract_esa_bundle(
                CostaMunicipalityContext(
                    municipality["name"],
                    municipality["istat_code"],
                    municipality["source_slug"],
                ),
                retrieved_at,
                pages,
            )
            write_jsonl(
                args.output_dir / f"{municipality['source_slug']}-acquisition.jsonl",
                records,
            )
            counts: dict[str, int] = {}
            for record in records:
                counts[record["record_type"]] = counts.get(record["record_type"], 0) + 1
            municipality_report = {
                "municipality": municipality["name"],
                "istat_code": municipality["istat_code"],
                "pages_available": len(pages),
                "pages_materialized": len(pages),
                "equivalent_pages": [],
                "records": len(records),
                "records_by_type": counts,
                "warnings": warnings,
            }
            (args.output_dir / f"{municipality['source_slug']}-report.json").write_text(
                json.dumps(municipality_report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            municipality_reports.append(municipality_report)
            total_records += len(records)
            total_warnings += len(warnings)
        report = {
            "observed_at": retrieved_at.isoformat(),
            "pages_checked": len(pages),
            "pages_remaining": 0,
            "municipalities_touched": len(municipalities),
            "pages_by_status": {"snapshot": len(pages)},
            "pages_by_category": {"collection": 1, "facilities": 1},
            "errors": [],
            "extraction": {
                "municipalities": len(municipalities),
                "records": total_records,
                "warnings": total_warnings,
                "municipality_reports": municipality_reports,
            },
        }
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return 0 if len(municipalities) == 7 and not total_warnings else 1
    if args.command == "build-ato-costa-registry":
        csv_text = args.assignment_csv.read_text(encoding="utf-8")
        records, warnings = extract_ato_costa_municipality_registry(
            csv_text=csv_text,
            retrieved_at=datetime.fromisoformat(args.retrieved_at),
            istat_by_name=read_istat_municipalities(args.istat_csv),
        )
        write_jsonl(args.output, records)
        province_counts: dict[str, int] = {}
        operator_counts: dict[str, int] = {}
        status_counts: dict[str, int] = {}
        for record in records:
            payload = record["payload"]
            for counts, key in (
                (province_counts, payload["province_code"]),
                (operator_counts, payload["local_operator_ref"]),
                (status_counts, payload["assignment_status"]),
            ):
                counts[key] = counts.get(key, 0) + 1
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps({
            "source_url": records[0]["source"]["url"] if records else None,
            "municipalities": len(records),
            "municipalities_by_province": province_counts,
            "municipalities_by_local_operator": operator_counts,
            "municipalities_by_assignment_status": status_counts,
            "warnings": warnings,
        }, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return 0 if len(records) == 100 and not warnings else 1
    if args.command == "sweep-sei":
        observed_at = datetime.fromisoformat(args.observed_at)
        jobs = read_registry_jobs(args.registry)
        selected = set(args.municipalities or [])
        if args.municipality_file:
            selected.update(_read_selection_file(args.municipality_file))
        if selected:
            jobs = [job for job in jobs if job.slug in selected or job.istat_code in selected]
        if not args.fixture_root and not args.user_agent:
            print("error: --user-agent is required for live sweeps", file=sys.stderr)
            return 2
        fetcher = (
            FixtureFetcher(args.fixture_root)
            if args.fixture_root
            else HttpFetcher(args.user_agent, args.delay)
        )
        access_preflight = None
        if isinstance(fetcher, HttpFetcher):
            try:
                access_preflight = fetcher.validate(jobs)
            except Exception as error:
                blocked_urls = error.blocked_urls if isinstance(error, RobotsAccessError) else []
                errors = (
                    [
                        {
                            "url": url,
                            "status": "blocked_by_robots",
                            "error": "robots.txt does not allow this URL",
                        }
                        for url in blocked_urls
                    ]
                    if blocked_urls
                    else [{
                        "url": "https://seitoscana.it/robots.txt",
                        "status": "access_preflight_failed",
                        "error": f"{type(error).__name__}: {error}",
                    }]
                )
                report = {
                    "observed_at": observed_at.isoformat(),
                    "pages_checked": 0,
                    "pages_remaining": len(jobs),
                    "municipalities_touched": 0,
                    "pages_by_status": {},
                    "pages_by_category": {},
                    "access_preflight": {
                        "robots_url": "https://seitoscana.it/robots.txt",
                        "allowed": False,
                        "initial_urls_checked": len(jobs),
                        "blocked_urls": blocked_urls,
                        "error": f"{type(error).__name__}: {error}",
                    },
                    "errors": errors,
                    "extraction": {
                        "municipalities": 0,
                        "records": 0,
                        "warnings": 0,
                        "municipality_reports": [],
                    },
                }
                args.report.parent.mkdir(parents=True, exist_ok=True)
                args.report.write_text(
                    json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                return 1
        state = CrawlState(args.state)
        selected_istat = {job.istat_code for job in jobs}
        report = SweepRunner(SnapshotStore(args.snapshot_root), state).run(
            jobs=jobs,
            fetcher=fetcher,
            observed_at=observed_at,
            max_pages=args.max_pages,
        )
        report["access_preflight"] = access_preflight
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
    prepared: list[dict[str, Any]] = []
    for istat_code, documents in sorted(grouped.items()):
        first = documents[0]
        documents, equivalent_pages = _deduplicate_materialization_documents(documents)
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
        prepared.append({
            "first": first,
            "istat_code": istat_code,
            "documents": documents,
            "pages": pages,
            "equivalent_pages": equivalent_pages,
            "records": records,
            "warnings": warnings,
        })

    reference = build_eer_description_reference(item["records"] for item in prepared)
    for item in prepared:
        first = item["first"]
        records, warnings = reconcile_eer_records(
            item["records"], item["warnings"], reference
        )
        output_dir.mkdir(parents=True, exist_ok=True)
        write_jsonl(output_dir / f"{first['slug']}-acquisition.jsonl", records)
        counts: dict[str, int] = {}
        for record in records:
            counts[record["record_type"]] = counts.get(record["record_type"], 0) + 1
        municipality_report = {
            "municipality": first["municipality"],
            "istat_code": item["istat_code"],
            "pages_available": len(item["documents"]) + len(item["equivalent_pages"]),
            "pages_materialized": len(item["pages"]),
            "equivalent_pages": item["equivalent_pages"],
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


def _deduplicate_materialization_documents(
    documents: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    unique: list[dict[str, Any]] = []
    equivalent_pages: list[dict[str, str]] = []
    seen: dict[tuple[str, str], dict[str, Any]] = {}
    for document in sorted(
        documents,
        key=lambda item: (
            item["category"],
            "/centri-di-raccolta" in item.get("url", ""),
            item.get("url", ""),
        ),
    ):
        html = Path(document["snapshot_path"]).read_text(encoding="utf-8")
        fingerprint = _materialization_fingerprint(document["category"], html)
        key = (document["category"], fingerprint)
        original = seen.get(key)
        if original is None:
            seen[key] = document
            unique.append(document)
            continue
        equivalent_pages.append({
            "url": document.get("final_url") or document["url"],
            "equivalent_to": original.get("final_url") or original["url"],
            "category": document["category"],
        })
    return unique, equivalent_pages


def _materialization_fingerprint(category: str, html: str) -> str:
    root = parse_html(html)
    main = root.find_first(lambda element: element.tag == "main") or root
    links: list[str] = []
    for element in main.descendants(include_self=True):
        for attribute in ("href", "src"):
            value = element.attrs.get(attribute)
            if not value:
                continue
            value = re.sub(
                r"/centri?-di-raccolta(?=($|[#?]))",
                "/centro-di-raccolta",
                value,
            )
            links.append(f"{element.tag}:{attribute}:{value}")
    content = f"{category}\n{clean_text(main.text)}\n" + "\n".join(links)
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
