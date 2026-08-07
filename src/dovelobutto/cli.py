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
from .catalog import build_catalog_from_paths, write_catalog
from .eer import build_eer_register, validate_acquired_eer, write_json
from .packaging_marks import build_packaging_material_register
from .vision_corpus import validate_vision_corpus, write_json as write_vision_json
from .vision_bootstrap import build_vision_bootstrap
from .ato_costa import (
    MunicipalityContext as CostaMunicipalityContext,
    extract_aamps_waste_lookup,
    extract_esa_bundle,
    extract_rea_waste_lookup,
)
from .html import clean_text, parse_html
from .records import write_jsonl
from .rea import crawl_rea_services, materialize_rea_services
from .geofor import crawl_geofor, materialize_geofor
from .alia import fetch_alia_bundle, materialize_alia
from .boundary import (
    build_boundary_registry,
    fetch_boundary_bundle,
    materialize_boundary,
)
from .local_operators import (
    OPERATOR_CONFIGS,
    crawl_local_operator,
    materialize_local_operator,
)
from .registry import (
    extract_ato_centro_municipality_registry,
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
from .sync import (
    apply_manifest_package,
    apply_update_plan,
    load_canonical_entities,
    publish_release,
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
    centro_registry = subparsers.add_parser(
        "build-ato-centro-registry",
        help="Build the official ATO Centro municipality registry from ISTAT",
    )
    centro_registry.add_argument("--istat-csv", type=Path, required=True)
    centro_registry.add_argument("--retrieved-at", required=True)
    centro_registry.add_argument("--output", type=Path, required=True)
    centro_registry.add_argument("--report", type=Path, required=True)
    boundary_registry = subparsers.add_parser(
        "build-boundary-registry",
        help="Build the registry of Tuscan municipalities assigned to extra-regional ATOs",
    )
    boundary_registry.add_argument("--istat-csv", type=Path, required=True)
    boundary_registry.add_argument("--retrieved-at", required=True)
    boundary_registry.add_argument("--output", type=Path, required=True)
    boundary_registry.add_argument("--report", type=Path, required=True)
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
    rea_services_fetch = subparsers.add_parser(
        "fetch-rea-services",
        help="Crawl linked REA municipality, service, centre and PDF pages",
    )
    rea_services_fetch.add_argument("--registry", type=Path, required=True)
    rea_services_fetch.add_argument("--snapshot-root", type=Path, required=True)
    rea_services_fetch.add_argument("--manifest", type=Path, required=True)
    rea_services_fetch.add_argument("--report", type=Path, required=True)
    rea_services_fetch.add_argument("--observed-at", required=True)
    rea_services_fetch.add_argument("--user-agent", required=True)
    rea_services_fetch.add_argument("--delay", type=float, default=1.0)
    rea_services = subparsers.add_parser(
        "materialize-rea-services",
        help="Combine REA's waste dictionary with municipality and centre pages",
    )
    rea_services.add_argument("--registry", type=Path, required=True)
    rea_services.add_argument("--manifest", type=Path, required=True)
    rea_services.add_argument("--snapshot-root", type=Path, required=True)
    rea_services.add_argument("--rifiutario-json", type=Path, required=True)
    rea_services.add_argument("--retrieved-at", required=True)
    rea_services.add_argument("--output-dir", type=Path, required=True)
    rea_services.add_argument("--report", type=Path, required=True)
    geofor_fetch = subparsers.add_parser(
        "fetch-geofor",
        help="Crawl GEOFOR municipality, calendar, centre, pickup and PDF pages",
    )
    geofor_fetch.add_argument("--registry", type=Path, required=True)
    geofor_fetch.add_argument("--snapshot-root", type=Path, required=True)
    geofor_fetch.add_argument("--manifest", type=Path, required=True)
    geofor_fetch.add_argument("--report", type=Path, required=True)
    geofor_fetch.add_argument("--observed-at", required=True)
    geofor_fetch.add_argument("--user-agent", required=True)
    geofor_fetch.add_argument("--delay", type=float, default=1.0)
    geofor_materialize = subparsers.add_parser(
        "materialize-geofor",
        help="Materialize GEOFOR waste, collection, centre and pickup records",
    )
    geofor_materialize.add_argument("--registry", type=Path, required=True)
    geofor_materialize.add_argument("--manifest", type=Path, required=True)
    geofor_materialize.add_argument("--snapshot-root", type=Path, required=True)
    geofor_materialize.add_argument("--retrieved-at", required=True)
    geofor_materialize.add_argument("--output-dir", type=Path, required=True)
    geofor_materialize.add_argument("--report", type=Path, required=True)
    alia_fetch = subparsers.add_parser(
        "fetch-alia",
        help="Fetch the public AliaEstra waste dictionary, centres and mobile points",
    )
    alia_fetch.add_argument("--catalog", type=Path, required=True)
    alia_fetch.add_argument("--bundle", type=Path, required=True)
    alia_fetch.add_argument("--report", type=Path, required=True)
    alia_fetch.add_argument("--observed-at", required=True)
    alia_fetch.add_argument("--user-agent", required=True)
    alia_fetch.add_argument("--delay", type=float, default=1.0)
    alia_materialize = subparsers.add_parser(
        "materialize-alia",
        help="Materialize normalized ATO Centro records from an AliaEstra bundle",
    )
    alia_materialize.add_argument("--registry", type=Path, required=True)
    alia_materialize.add_argument("--bundle", type=Path, required=True)
    alia_materialize.add_argument("--retrieved-at", required=True)
    alia_materialize.add_argument("--output-dir", type=Path, required=True)
    alia_materialize.add_argument("--report", type=Path, required=True)
    boundary_fetch = subparsers.add_parser(
        "fetch-boundary",
        help="Fetch Hera and Marche Multiservizi sources for the four boundary municipalities",
    )
    boundary_fetch.add_argument("--bundle", type=Path, required=True)
    boundary_fetch.add_argument("--report", type=Path, required=True)
    boundary_fetch.add_argument("--observed-at", required=True)
    boundary_fetch.add_argument("--user-agent", required=True)
    boundary_fetch.add_argument("--delay", type=float, default=0.5)
    boundary_materialize = subparsers.add_parser(
        "materialize-boundary",
        help="Materialize the four Tuscan municipalities assigned to extra-regional ATOs",
    )
    boundary_materialize.add_argument("--registry", type=Path, required=True)
    boundary_materialize.add_argument("--bundle", type=Path, required=True)
    boundary_materialize.add_argument("--retrieved-at", required=True)
    boundary_materialize.add_argument("--output-dir", type=Path, required=True)
    boundary_materialize.add_argument("--report", type=Path, required=True)
    local_fetch = subparsers.add_parser(
        "fetch-local-operator",
        help="Fetch the declared public sources for one ATO Costa local operator",
    )
    local_fetch.add_argument("--operator", choices=sorted(OPERATOR_CONFIGS), required=True)
    local_fetch.add_argument("--registry", type=Path, required=True)
    local_fetch.add_argument("--snapshot-root", type=Path, required=True)
    local_fetch.add_argument("--manifest", type=Path, required=True)
    local_fetch.add_argument("--report", type=Path, required=True)
    local_fetch.add_argument("--observed-at", required=True)
    local_fetch.add_argument("--user-agent", required=True)
    local_fetch.add_argument("--delay", type=float, default=1.0)
    local_materialize = subparsers.add_parser(
        "materialize-local-operator",
        help="Materialize normalized records for one ATO Costa local operator",
    )
    local_materialize.add_argument("--operator", choices=sorted(OPERATOR_CONFIGS), required=True)
    local_materialize.add_argument("--registry", type=Path, required=True)
    local_materialize.add_argument("--manifest", type=Path, required=True)
    local_materialize.add_argument("--snapshot-root", type=Path, required=True)
    local_materialize.add_argument("--retrieved-at", required=True)
    local_materialize.add_argument("--output-dir", type=Path, required=True)
    local_materialize.add_argument("--report", type=Path, required=True)
    aamps = subparsers.add_parser(
        "materialize-aamps-rifiutario",
        help="Extract the AAMPS two-column waste guide from pdftotext bbox XHTML",
    )
    aamps.add_argument("--registry", type=Path, required=True)
    aamps.add_argument("--bbox-html", type=Path, required=True)
    aamps.add_argument("--retrieved-at", required=True)
    aamps.add_argument("--output-dir", type=Path, required=True)
    aamps.add_argument("--report", type=Path, required=True)
    catalog = subparsers.add_parser(
        "build-waste-catalog",
        help="Build the canonical waste vocabulary from acquired waste dictionaries",
    )
    catalog.add_argument("--input-dir", type=Path, action="append", required=True)
    catalog.add_argument("--registry", type=Path, action="append", required=True)
    catalog.add_argument("--generated-at", required=True)
    catalog.add_argument("--eer-register", type=Path)
    catalog.add_argument("--output", type=Path, required=True)
    catalog.add_argument("--report", type=Path, required=True)
    publish = subparsers.add_parser(
        "publish-data-release",
        help="Build the canonical SQLite state and signed snapshot/delta artifacts",
    )
    publish.add_argument("--input-dir", type=Path, action="append", required=True)
    publish.add_argument("--registry", type=Path, action="append", required=True)
    publish.add_argument("--catalog", type=Path)
    publish.add_argument("--eer-register", type=Path)
    publish.add_argument("--packaging-material-register", type=Path)
    publish.add_argument("--database", type=Path, required=True)
    publish.add_argument("--artifact-dir", type=Path, required=True)
    publish.add_argument("--manifest", type=Path, required=True)
    publish.add_argument("--revision", type=int, required=True)
    publish.add_argument("--generated-at", required=True)
    publish.add_argument("--private-key", type=Path, required=True)
    publish.add_argument("--key-id", required=True)
    publish.add_argument("--base-url", required=True)
    publish.add_argument("--report", type=Path, required=True)
    apply_update = subparsers.add_parser(
        "apply-data-update",
        help="Verify and atomically apply one manifest package to a client SQLite database",
    )
    apply_update.add_argument("--database", type=Path, required=True)
    apply_update.add_argument("--manifest", type=Path, required=True)
    apply_update.add_argument("--package-id", required=True)
    apply_update.add_argument("--artifact-root", type=Path, required=True)
    apply_update.add_argument("--public-key", type=Path, required=True)
    apply_plan = subparsers.add_parser(
        "apply-data-plan",
        help="Choose the smallest valid update path and apply it to a client database",
    )
    apply_plan.add_argument("--database", type=Path, required=True)
    apply_plan.add_argument("--manifest", type=Path, required=True)
    apply_plan.add_argument("--artifact-root", type=Path, required=True)
    apply_plan.add_argument("--public-key", type=Path, required=True)
    eer = subparsers.add_parser(
        "build-eer-register",
        help="Build the official Italian EER register and validate acquired centre codes",
    )
    eer.add_argument("--base-html", type=Path, required=True)
    eer.add_argument("--amendment-html", type=Path, required=True)
    eer.add_argument("--corrigendum-html", type=Path, required=True)
    eer.add_argument("--input-dir", type=Path, action="append", default=[])
    eer.add_argument("--generated-at", required=True)
    eer.add_argument("--output", type=Path, required=True)
    eer.add_argument("--report", type=Path, required=True)
    packaging_marks = subparsers.add_parser(
        "build-packaging-material-register",
        help="Build the EU 97/129/EC packaging material identification register",
    )
    packaging_marks.add_argument("--transcription-csv", type=Path, required=True)
    packaging_marks.add_argument("--source-pdf", type=Path, required=True)
    packaging_marks.add_argument("--source-html", type=Path, required=True)
    packaging_marks.add_argument("--extracted-text", type=Path, required=True)
    packaging_marks.add_argument("--generated-at", required=True)
    packaging_marks.add_argument("--output", type=Path, required=True)
    packaging_marks.add_argument("--report", type=Path, required=True)
    vision_corpus = subparsers.add_parser(
        "validate-vision-corpus",
        help="Validate visual corpus rights, splits, annotations, and asset hashes",
    )
    vision_corpus.add_argument("--manifest", type=Path, required=True)
    vision_corpus.add_argument("--taxonomy", type=Path, required=True)
    vision_corpus.add_argument("--assets-root", type=Path)
    vision_corpus.add_argument("--report", type=Path, required=True)
    vision_bootstrap = subparsers.add_parser(
        "build-vision-bootstrap",
        help="Render official reference pages and deterministic synthetic packaging marks",
    )
    vision_bootstrap.add_argument("--register", type=Path, required=True)
    vision_bootstrap.add_argument("--taxonomy", type=Path, required=True)
    vision_bootstrap.add_argument("--guidelines-pdf", type=Path, required=True)
    vision_bootstrap.add_argument("--decree-pdf", type=Path, required=True)
    vision_bootstrap.add_argument("--legal-notice-pdf", type=Path, required=True)
    vision_bootstrap.add_argument("--font", type=Path, required=True)
    vision_bootstrap.add_argument("--assets-root", type=Path, required=True)
    vision_bootstrap.add_argument("--generated-at", required=True)
    vision_bootstrap.add_argument("--manifest", type=Path, required=True)
    vision_bootstrap.add_argument("--report", type=Path, required=True)
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
    if args.command == "publish-data-release":
        entities = load_canonical_entities(
            args.input_dir, args.registry, args.catalog, args.eer_register,
            args.packaging_material_register,
        )
        report = publish_release(
            entities, args.database, args.artifact_dir, args.manifest,
            args.revision, datetime.fromisoformat(args.generated_at),
            args.private_key, args.key_id, args.base_url,
        )
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return 0
    if args.command == "apply-data-update":
        changed = apply_manifest_package(
            args.database, args.manifest, args.package_id,
            args.artifact_root, args.public_key,
        )
        print("applied" if changed else "already_applied")
        return 0
    if args.command == "apply-data-plan":
        packages = apply_update_plan(
            args.database, args.manifest, args.artifact_root, args.public_key,
        )
        print(json.dumps({"applied_packages": packages}, ensure_ascii=False))
        return 0
    if args.command == "fetch-boundary":
        bundle = fetch_boundary_bundle(
            args.bundle, datetime.fromisoformat(args.observed_at), args.user_agent, args.delay,
        )
        report = {
            "observed_at": bundle["observed_at"], "access_preflight": bundle["access"],
            "errors": bundle["errors"],
            "coverage": {
                "hera_municipalities": len(bundle["hera"]),
                "hera_products": sum(len(item.get("products", [])) for item in bundle["hera"].values()),
                "hera_product_details": sum(len(item.get("product_data", {})) for item in bundle["hera"].values()),
                "hera_stations": sum(len(item.get("stations", {})) for item in bundle["hera"].values()),
                "mms_public_pages": sum(page.get("status") == "snapshot" for page in bundle["mms"]["pages"].values()),
            },
        }
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        complete_hera = all(
            len(item.get("products", [])) == len(item.get("product_data", {}))
            for item in bundle["hera"].values()
        )
        return 0 if not bundle["errors"] and len(bundle["hera"]) == 3 and complete_hera else 1
    if args.command == "materialize-boundary":
        municipalities = [
            json.loads(line)["payload"]
            for line in args.registry.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        report = materialize_boundary(
            municipalities,
            json.loads(args.bundle.read_text(encoding="utf-8")),
            datetime.fromisoformat(args.retrieved_at), args.output_dir,
        )
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return 0 if report["extraction"]["municipalities"] == 4 and not report["errors"] else 1
    if args.command == "fetch-alia":
        bundle = fetch_alia_bundle(
            json.loads(args.catalog.read_text(encoding="utf-8")),
            args.bundle,
            datetime.fromisoformat(args.observed_at),
            args.user_agent,
            args.delay,
        )
        report = {
            "observed_at": bundle["observed_at"],
            "access_preflight": bundle["access"],
            "errors": bundle["errors"],
            "coverage": {
                "autocomplete_queries": len(bundle["junker"]["queries"]),
                "waste_terms": len(bundle["junker"]["details"]),
                "centres": len(bundle["centres"]),
                "eco_trucks": len(bundle["eco_trucks"]),
                "sitecore_details": len(bundle["centre_details"]),
            },
        }
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return 0 if not bundle["errors"] and bundle["junker"]["details"] else 1
    if args.command == "materialize-alia":
        municipalities = [
            json.loads(line)["payload"]
            for line in args.registry.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        report = materialize_alia(
            municipalities,
            json.loads(args.bundle.read_text(encoding="utf-8")),
            datetime.fromisoformat(args.retrieved_at),
            args.output_dir,
        )
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return 0 if len(municipalities) == 65 and not report["errors"] else 1
    if args.command in {"fetch-local-operator", "materialize-local-operator"}:
        municipalities = [
            json.loads(line)["payload"]
            for line in args.registry.read_text(encoding="utf-8").splitlines()
            if line.strip()
            and json.loads(line)["payload"].get("local_operator_ref") == args.operator
        ]
        if args.command == "fetch-local-operator":
            manifest = crawl_local_operator(
                args.operator, municipalities, args.snapshot_root,
                datetime.fromisoformat(args.observed_at), args.user_agent, args.delay,
            )
            args.manifest.parent.mkdir(parents=True, exist_ok=True)
            args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            errors = [
                {"url": page["url"], "code": page["status"], "detail": page.get("error")}
                for page in manifest["pages"] if page["status"] not in {"snapshot", "partial_snapshot"}
            ]
            report = {
                "observed_at": manifest["observed_at"],
                "operator_ref": args.operator,
                "robots_url": manifest["robots_url"],
                "robots_status": manifest["robots_status"],
                "pages_checked": manifest["summary"]["checked"],
                "pages_remaining": 0,
                "municipalities_touched": len(municipalities),
                "pages_by_status": {
                    "snapshot": manifest["summary"]["snapshots"],
                    "blocked_by_robots": manifest["summary"]["blocked_by_robots"],
                    "error": manifest["summary"]["errors"],
                },
                "errors": errors,
            }
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            return 0 if not errors else 1
        retrieved_at = datetime.fromisoformat(args.retrieved_at)
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        results, municipality_reports = materialize_local_operator(
            args.operator, municipalities, manifest, args.snapshot_root, retrieved_at,
        )
        args.output_dir.mkdir(parents=True, exist_ok=True)
        for municipality in municipalities:
            slug = municipality["source_slug"]
            write_jsonl(args.output_dir / f"{slug}-acquisition.jsonl", results[slug])
            municipal_report = next(report for report in municipality_reports if report["istat_code"] == municipality["istat_code"])
            (args.output_dir / f"{slug}-report.json").write_text(json.dumps(municipal_report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        report = {
            "observed_at": retrieved_at.isoformat(),
            "operator_ref": args.operator,
            "pages_checked": manifest["summary"]["checked"],
            "pages_remaining": 0,
            "municipalities_touched": len(municipalities),
            "pages_by_status": {
                "snapshot": manifest["summary"]["snapshots"],
                "blocked_by_robots": manifest["summary"]["blocked_by_robots"],
                "error": manifest["summary"]["errors"],
            },
            "errors": [
                {"url": page["url"], "code": page["status"], "detail": page.get("error")}
                for page in manifest["pages"] if page["status"] not in {"snapshot", "partial_snapshot"}
            ],
            "extraction": {
                "municipalities": len(municipalities),
                "records": sum(report["records"] for report in municipality_reports),
                "warnings": sum(len(report["warnings"]) for report in municipality_reports),
                "municipality_reports": municipality_reports,
            },
        }
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return 0
    if args.command == "build-eer-register":
        register, report = build_eer_register(
            args.base_html,
            args.amendment_html,
            args.corrigendum_html,
            datetime.fromisoformat(args.generated_at),
        )
        if args.input_dir:
            report["acquired_validation"] = validate_acquired_eer(
                register, args.input_dir
            )
        write_json(args.output, register)
        write_json(args.report, report)
        return 0
    if args.command == "build-packaging-material-register":
        register, report = build_packaging_material_register(
            args.transcription_csv,
            args.source_pdf,
            args.source_html,
            args.extracted_text,
            datetime.fromisoformat(args.generated_at),
        )
        write_json(args.output, register)
        write_json(args.report, report)
        return 0
    if args.command == "validate-vision-corpus":
        report = validate_vision_corpus(
            args.manifest, args.taxonomy, args.assets_root,
        )
        write_vision_json(args.report, report)
        return 0
    if args.command == "build-vision-bootstrap":
        manifest, report = build_vision_bootstrap(
            args.register,
            args.taxonomy,
            args.guidelines_pdf,
            args.decree_pdf,
            args.legal_notice_pdf,
            args.font,
            args.assets_root,
            datetime.fromisoformat(args.generated_at),
        )
        write_vision_json(args.manifest, manifest)
        write_vision_json(args.report, report)
        return 0
    if args.command == "build-waste-catalog":
        catalog, report = build_catalog_from_paths(
            args.input_dir,
            args.registry,
            datetime.fromisoformat(args.generated_at),
            args.eer_register,
        )
        write_catalog(args.output, catalog)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return 0 if catalog["concepts"] else 1
    if args.command == "fetch-geofor":
        municipalities = [
            json.loads(line)["payload"] for line in args.registry.read_text(encoding="utf-8").splitlines()
            if line.strip()
            and json.loads(line)["payload"].get("local_operator_ref") == "geofor"
            and json.loads(line)["payload"].get("assignment_status") in {"active", "pending_subentry"}
        ]
        previous = json.loads(args.manifest.read_text(encoding="utf-8")) if args.manifest.exists() else None
        manifest = crawl_geofor(municipalities, args.snapshot_root, datetime.fromisoformat(args.observed_at), args.user_agent, args.delay, previous)
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        errors = [{"url": page["url"], "code": page["status"], "detail": page.get("error")} for page in manifest["pages"] if page["status"] != "snapshot"]
        report = {"observed_at": manifest["observed_at"], "pages_checked": manifest["summary"]["checked"], "pages_remaining": 0, "municipalities_touched": len(municipalities), "pages_by_status": {"snapshot": manifest["summary"]["snapshots"], "blocked_by_robots": manifest["summary"]["blocked_by_robots"], "error": manifest["summary"]["errors"]}, "pages_by_category": manifest["summary"]["by_category"], "errors": errors}
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return 0 if not errors else 1
    if args.command == "materialize-geofor":
        retrieved_at = datetime.fromisoformat(args.retrieved_at)
        municipalities = [
            json.loads(line)["payload"] for line in args.registry.read_text(encoding="utf-8").splitlines()
            if line.strip()
            and json.loads(line)["payload"].get("local_operator_ref") == "geofor"
            and json.loads(line)["payload"].get("assignment_status") in {"active", "pending_subentry"}
        ]
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        results, municipality_reports = materialize_geofor(municipalities, manifest, args.snapshot_root, retrieved_at)
        args.output_dir.mkdir(parents=True, exist_ok=True)
        for municipality in municipalities:
            slug = municipality["source_slug"]
            write_jsonl(args.output_dir / f"{slug}-acquisition.jsonl", results[slug])
            municipal_report = next(report for report in municipality_reports if report["istat_code"] == municipality["istat_code"])
            (args.output_dir / f"{slug}-report.json").write_text(json.dumps(municipal_report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        crawl_errors = [{"url": page["url"], "code": page["status"], "detail": page.get("error")} for page in manifest["pages"] if page["status"] != "snapshot"]
        report = {"observed_at": retrieved_at.isoformat(), "pages_checked": manifest["summary"]["checked"], "pages_remaining": 0, "municipalities_touched": len(municipalities), "pages_by_status": {"snapshot": manifest["summary"]["snapshots"], "blocked_by_robots": manifest["summary"]["blocked_by_robots"], "error": manifest["summary"]["errors"]}, "pages_by_category": manifest["summary"]["by_category"], "errors": crawl_errors, "extraction": {"municipalities": len(municipalities), "records": sum(report["records"] for report in municipality_reports), "warnings": sum(len(report["warnings"]) for report in municipality_reports), "municipality_reports": municipality_reports}}
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return 0
    if args.command == "fetch-rea-services":
        municipalities = [
            json.loads(line)["payload"]
            for line in args.registry.read_text(encoding="utf-8").splitlines()
            if line.strip() and json.loads(line)["payload"].get("local_operator_ref") == "rea"
        ]
        previous_manifest = (
            json.loads(args.manifest.read_text(encoding="utf-8"))
            if args.manifest.exists() else None
        )
        manifest = crawl_rea_services(
            municipalities, args.snapshot_root, datetime.fromisoformat(args.observed_at),
            args.user_agent, args.delay, previous_manifest,
        )
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        errors = [
            {"url": page["url"], "code": page["status"], "detail": page.get("error")}
            for page in manifest["pages"] if page["status"] != "snapshot"
        ]
        report = {
            "observed_at": manifest["observed_at"],
            "pages_checked": manifest["summary"]["checked"],
            "pages_remaining": 0,
            "municipalities_touched": len(municipalities),
            "pages_by_status": {
                "snapshot": manifest["summary"]["snapshots"],
                "blocked_by_robots": manifest["summary"]["blocked_by_robots"],
                "error": manifest["summary"]["errors"],
            },
            "pages_by_category": manifest["summary"]["by_category"],
            "errors": errors,
        }
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return 0 if not errors else 1
    if args.command == "materialize-rea-services":
        retrieved_at = datetime.fromisoformat(args.retrieved_at)
        municipalities = [
            json.loads(line)["payload"]
            for line in args.registry.read_text(encoding="utf-8").splitlines()
            if line.strip() and json.loads(line)["payload"].get("local_operator_ref") == "rea"
        ]
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        results, municipality_reports = materialize_rea_services(
            municipalities, manifest, args.snapshot_root,
            args.rifiutario_json.read_text(encoding="utf-8"), retrieved_at,
        )
        args.output_dir.mkdir(parents=True, exist_ok=True)
        for municipality in municipalities:
            slug = municipality["source_slug"]
            write_jsonl(args.output_dir / f"{slug}-acquisition.jsonl", results[slug])
            municipal_report = next(report for report in municipality_reports if report["istat_code"] == municipality["istat_code"])
            (args.output_dir / f"{slug}-report.json").write_text(json.dumps(municipal_report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        report = {
            "observed_at": retrieved_at.isoformat(),
            "pages_checked": manifest["summary"]["checked"],
            "pages_remaining": 0,
            "municipalities_touched": len(municipalities),
            "pages_by_status": {
                "snapshot": manifest["summary"]["snapshots"],
                "blocked_by_robots": manifest["summary"]["blocked_by_robots"],
                "error": manifest["summary"]["errors"],
            },
            "pages_by_category": manifest["summary"]["by_category"],
            "errors": [{"url": page["url"], "code": page["status"], "detail": page.get("error")} for page in manifest["pages"] if page["status"] != "snapshot"],
            "extraction": {
                "municipalities": len(municipalities),
                "records": sum(report["records"] for report in municipality_reports),
                "warnings": sum(len(report["warnings"]) for report in municipality_reports),
                "municipality_reports": municipality_reports,
            },
        }
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return 0
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
    if args.command == "build-ato-centro-registry":
        records, warnings = extract_ato_centro_municipality_registry(
            retrieved_at=datetime.fromisoformat(args.retrieved_at),
            istat_by_name=read_istat_municipalities(args.istat_csv),
        )
        write_jsonl(args.output, records)
        province_counts: dict[str, int] = {}
        for record in records:
            province = record["payload"]["province_code"]
            province_counts[province] = province_counts.get(province, 0) + 1
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps({
            "source_url": records[0]["source"]["url"] if records else None,
            "municipalities": len(records),
            "municipalities_by_province": province_counts,
            "operator": "plures-alia",
            "excluded_municipalities": sorted(["Firenzuola", "Marradi", "Palazzuolo sul Senio"]),
            "warnings": warnings,
        }, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return 0 if len(records) == 65 and not warnings else 1
    if args.command == "build-boundary-registry":
        records, warnings = build_boundary_registry(
            datetime.fromisoformat(args.retrieved_at),
            read_istat_municipalities(args.istat_csv),
        )
        write_jsonl(args.output, records)
        ato_counts: dict[str, int] = {}
        province_counts: dict[str, int] = {}
        for record in records:
            payload = record["payload"]
            ato_counts[payload["ato_ref"]] = ato_counts.get(payload["ato_ref"], 0) + 1
            province_counts[payload["province_code"]] = province_counts.get(payload["province_code"], 0) + 1
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps({
            "municipalities": len(records), "municipalities_by_ato": ato_counts,
            "municipalities_by_province": province_counts,
            "scope": "Tuscan municipalities assigned to ATOs with headquarters outside Tuscany",
            "warnings": warnings,
        }, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return 0 if len(records) == 4 and not warnings else 1
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
