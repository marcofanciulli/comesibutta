from __future__ import annotations

from collections import deque
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import time
from typing import Any, Iterable
from urllib import robotparser
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse
from urllib.request import Request, urlopen

from .ato_costa import MunicipalityContext, extract_rea_waste_lookup
from .html import Element, clean_text, parse_html
from .records import SourceDocument, make_record


REA_ROOT = "https://www.reaspa.it"
REA_CENTRES = f"{REA_ROOT}/centri-di-raccolta/"
REA_SHARED_PAGES = (
    f"{REA_ROOT}/ritiro-e-rifornimenti-kit/",
    f"{REA_ROOT}/ritiro-ingombranti/",
    f"{REA_ROOT}/ritiro-potature/",
    f"{REA_ROOT}/ritiro-raee/",
    f"{REA_ROOT}/attivazione-servizio-pannolini-e-pannoloni/",
)
_STREAMS = (
    ("organico", "Rifiuti organici"),
    ("carta e cartone", "Carta e cartone"),
    ("multimateriale", "Imballaggi in multimateriale"),
    ("vetro", "Vetro"),
    ("secco residuo", "Rifiuto residuo"),
    ("indifferenziato", "Rifiuto residuo"),
)
_CENTRE_ACCESS = {
    "casale-marittimo": {"guardistallo", "montescudaio"},
    "castellina-marittima": {"rosignano-solvay"},
    "castelnuovo-di-val-di-cecina": {"pomarance"},
    "guardistallo": {"guardistallo", "montescudaio"},
    "montecatini-val-di-cecina": {"guardistallo", "montescudaio"},
    "montescudaio": {"guardistallo", "montescudaio"},
    "collesalvetti": {"collesalvetti", "stagno"},
}
_CENTRE_OWNER = {
    "rosignano-solvay": "rosignano-marittimo",
    "stagno": "collesalvetti",
}


def _slug(value: str) -> str:
    value = value.casefold().translate(str.maketrans("àèéìòù", "aeeiou"))
    return re.sub(r"[^a-z0-9]+", "-", value).strip("-") or "unknown"


def _canonical_url(url: str) -> str:
    parsed = urlparse(url)
    query = urlencode(sorted(parse_qsl(parsed.query, keep_blank_values=True)))
    path = re.sub(r"/{2,}", "/", parsed.path)
    return urlunparse((parsed.scheme or "https", parsed.netloc, path, "", query, ""))


def _links(html: str, base_url: str) -> list[tuple[str, str]]:
    root = parse_html(html)
    result = []
    for link in root.find_all(lambda item: item.tag == "a" and bool(item.attrs.get("href"))):
        url = _canonical_url(urljoin(base_url, link.attrs["href"]))
        if urlparse(url).netloc == "www.reaspa.it":
            result.append((url, clean_text(link.text)))
    return result


def crawl_rea_services(
    municipalities: list[dict[str, Any]],
    snapshot_root: Path,
    observed_at: datetime,
    user_agent: str,
    delay: float = 1.0,
    previous_manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Crawl public GET pages linked by REA's municipality and centre indexes."""
    robots_url = f"{REA_ROOT}/robots.txt"
    with urlopen(Request(robots_url, headers={"User-Agent": user_agent}), timeout=30) as response:
        robots_lines = response.read().decode("utf-8", errors="replace").splitlines()
    robots = robotparser.RobotFileParser(robots_url)
    robots.parse(robots_lines)
    effective_delay = max(delay, robots.crawl_delay(user_agent) or robots.crawl_delay("*") or 1.0)

    queue: deque[dict[str, Any]] = deque()
    for municipality in municipalities:
        queue.append({"url": municipality["homepage_url"], "category": "municipality", "municipality_istats": [municipality["istat_code"]]})
    queue.append({"url": REA_CENTRES, "category": "centre_index", "municipality_istats": []})
    for url in REA_SHARED_PAGES:
        queue.append({"url": url, "category": "shared_service", "municipality_istats": []})

    valid_homepages = {_canonical_url(item["homepage_url"]) for item in municipalities}
    completed: dict[str, dict[str, Any]] = {
        page["url"]: page
        for page in (previous_manifest or {}).get("pages", [])
        if page["status"] == "snapshot"
        or page["category"] != "municipality"
        or page["url"] in valid_homepages
    }
    queued: dict[str, dict[str, Any]] = {}

    def enqueue(job: dict[str, Any]) -> None:
        url = _canonical_url(job["url"])
        job = {**job, "url": url}
        if url in completed:
            completed[url]["municipality_istats"] = sorted(set(completed[url]["municipality_istats"] + job["municipality_istats"]))
        elif url in queued:
            queued[url]["municipality_istats"] = sorted(set(queued[url]["municipality_istats"] + job["municipality_istats"]))
        else:
            queued[url] = job
            queue.append(job)

    initial = list(queue)
    queue.clear()
    for job in initial:
        enqueue(job)

    while queue:
        queued_job = queue.popleft()
        url = queued_job["url"]
        job = queued.pop(url)
        if not robots.can_fetch(user_agent, url):
            completed[url] = {**job, "status": "blocked_by_robots", "final_url": None, "content_type": None, "snapshot": None, "sha256": None}
            continue
        try:
            request = Request(url, headers={"User-Agent": user_agent, "Accept": "text/html,application/pdf"})
            with urlopen(request, timeout=45) as response:
                body = response.read()
                final_url = _canonical_url(response.geturl())
                content_type = response.headers.get_content_type()
            digest = hashlib.sha256(body).hexdigest()
            extension = ".pdf" if content_type == "application/pdf" or final_url.lower().endswith(".pdf") else ".html"
            snapshot = snapshot_root / f"{digest}{extension}"
            snapshot.parent.mkdir(parents=True, exist_ok=True)
            if not snapshot.exists():
                snapshot.write_bytes(body)
            entry = {**job, "status": "snapshot", "final_url": final_url, "content_type": content_type, "snapshot": snapshot.name, "sha256": digest}
            completed[url] = entry
            if extension == ".html":
                html = body.decode("utf-8", errors="replace")
                for discovered, label in _links(html, final_url):
                    path = urlparse(discovered).path
                    category = None
                    istats = entry["municipality_istats"]
                    if entry["category"] in {"municipality", "municipality_service"}:
                        if path.lower().endswith(".pdf"):
                            category = "municipality_document"
                        elif entry["category"] == "municipality" and path.startswith(urlparse(final_url).path.rstrip("/") + "/"):
                            category = "municipality_service"
                        elif path.startswith("/servizi/") and "comune=" in urlparse(discovered).query:
                            category = "municipality_service"
                    elif entry["category"] == "centre_index":
                        if re.fullmatch(r"/centri-di-raccolta/page/\d+/", path):
                            category = "centre_index"
                        elif path.startswith("/centri-di-raccolta/") and path != "/centri-di-raccolta/":
                            category = "centre_detail"
                    if category:
                        enqueue({"url": discovered, "category": category, "municipality_istats": istats, "link_text": label})
            time.sleep(effective_delay)
        except Exception as error:
            completed[url] = {**job, "status": "error", "final_url": None, "content_type": None, "snapshot": None, "sha256": None, "error": f"{type(error).__name__}: {error}"}
            time.sleep(effective_delay)

    pages = sorted(completed.values(), key=lambda item: (item["category"], item["url"]))
    categories = sorted({page["category"] for page in pages})
    return {
        "observed_at": observed_at.isoformat(), "publisher": "REA S.p.A.",
        "robots_url": robots_url, "crawl_delay_seconds": effective_delay, "pages": pages,
        "summary": {
            "checked": len(pages), "snapshots": sum(page["status"] == "snapshot" for page in pages),
            "blocked_by_robots": sum(page["status"] == "blocked_by_robots" for page in pages),
            "errors": sum(page["status"] == "error" for page in pages),
            "by_category": {category: sum(page["category"] == category for page in pages) for category in categories},
        },
    }


def _source(url: str, retrieved_at: datetime, html: str, parser: str) -> SourceDocument:
    return SourceDocument(url, retrieved_at, html, publisher="REA S.p.A.", parser=parser, parser_version="0.2.0")


def _main(root: Element) -> Element:
    return root.find_first(lambda item: "zui-content" in item.classes) or root.find_first(lambda item: item.tag == "main") or root


def _following_list(heading: Element | None) -> Element | None:
    if not heading or not heading.parent:
        return None
    siblings = heading.parent.children
    try:
        start = siblings.index(heading) + 1
    except ValueError:
        return None
    for sibling in siblings[start:]:
        if isinstance(sibling, Element) and sibling.tag == "ul":
            return sibling
        if isinstance(sibling, Element) and sibling.tag in {"h2", "h3", "h4"}:
            return None
    return heading.parent.find_first(lambda item: item.tag == "ul")


def _accepted_descriptions(content: Element) -> list[str]:
    elements = list(content.descendants())
    heading_index = next((
        index for index, item in enumerate(elements)
        if clean_text(item.text).casefold() == "cosa conferire"
    ), None)
    if heading_index is None:
        return []
    descriptions = []
    for item in elements[heading_index + 1:]:
        if clean_text(item.text).casefold().startswith("cosa non conferire"):
            break
        if item.tag == "li" and clean_text(item.text):
            descriptions.append(clean_text(item.text))
    return descriptions


def extract_rea_collection_pages(
    context: MunicipalityContext,
    retrieved_at: datetime,
    pages: Iterable[tuple[str, str]],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    records: list[dict[str, Any]] = []
    warnings: list[dict[str, str]] = []
    zone_ref = f"service-zone:{context.istat_code}:default"
    zone_added = False
    seen: set[str] = set()
    for url, html in pages:
        path = urlparse(url).path
        if not path.startswith("/servizi/"):
            continue
        root = parse_html(html)
        text = _main(root).text
        lowered = text.casefold()
        if "raccolta" not in lowered:
            continue
        source = _source(url, retrieved_at, html, "rea_services_html")
        if not zone_added:
            records.append(make_record(record_type="service_zone", natural_key=zone_ref, payload={"municipality_ref": context.municipality_ref, "name": "Intero territorio comunale", "scope_type": "municipality_default", "included_places_raw": None, "excluded_places_raw": None, "geometry_geojson": None}, source=source, evidence_selector="main", evidence_quote=text[:500]))
            zone_added = True
        if any(token in path for token in ("ingombranti", "potature", "raee")):
            accepted = "Rifiuti ingombranti" if "ingombranti" in path else "Sfalci e potature" if "potature" in path else "RAEE"
            natural_key = f"rea:pickup:{context.istat_code}:{_slug(accepted)}"
            if natural_key in seen:
                continue
            seen.add(natural_key)
            phone = root.find_first(lambda item: item.tag == "a" and item.attrs.get("href", "").startswith("tel:"))
            methods = [{"method": "web", "value": url, "hours_raw": None}]
            if phone:
                methods.append({"method": "phone", "value": phone.attrs["href"].removeprefix("tel:"), "hours_raw": None})
            records.append(make_record(record_type="pickup_service", natural_key=natural_key, payload={"municipality_ref": context.municipality_ref, "zone_ref": None, "user_type": "domestic", "accepted_waste_raw": accepted, "booking_methods": methods, "max_items": None, "quantity_limit_raw": None, "placement_instructions_raw": text[:4000], "booking_required": True}, source=source, evidence_selector="main", evidence_quote=text[:1000]))
            continue
        method = "street" if "stradale" in path else "door_to_door" if "porta" in lowered else "other"
        user_type = "all" if "utenze non domestiche" in lowered and "utenze domestiche" in lowered else "non_domestic" if "utenze non domestiche" in lowered else "domestic" if "utenze domestiche" in lowered else "all"
        for token, stream in _STREAMS:
            position = lowered.find(token)
            if position < 0:
                continue
            key = f"{method}:{user_type}:{_slug(stream)}"
            if key in seen:
                continue
            seen.add(key)
            window = lowered[max(0, position - 100):position + 700]
            container = None
            mode = "unspecified"
            if "compostabil" in window:
                container, mode = "sacco compostabile", "compostable_bag"
            elif "sacco" in window or "sacchet" in window:
                container, mode = "sacco", "bag_unspecified"
            color = next((candidate for candidate in ("giallo", "grigio", "marrone", "blu", "verde", "bianco") if candidate in window), None)
            records.append(make_record(record_type="collection_rule", natural_key=f"collection-rule:{context.istat_code}:default:{key}", payload={"municipality_ref": context.municipality_ref, "zone_ref": zone_ref, "user_type": user_type, "collection_method": method, "stream_name": stream, "included_materials_raw": None, "container_type": container, "container_color": color, "access_credential": None, "presentation": {"mode": mode, "max_volume_l": None, "instructions_raw": text[:3000]}, "schedule_raw": None}, source=source, evidence_selector="main", evidence_quote=text[:1000], confidence="medium"))
    if not zone_added:
        warnings.append({"code": "collection_rules_missing", "detail": "Nessuna regola di raccolta estraibile dalle pagine REA acquisite", "url": ""})
    return records, warnings


def extract_rea_centre(
    context: MunicipalityContext, retrieved_at: datetime, url: str, html: str,
    owner_context: MunicipalityContext | None = None,
) -> list[dict[str, Any]]:
    root = parse_html(html)
    content = _main(root)
    heading = content.find_first(lambda item: item.tag == "h1") or content.find_first(lambda item: item.tag == "h2")
    title = clean_text(heading.text if heading else urlparse(url).path.rstrip("/").split("/")[-1].replace("-", " ").title())
    text = content.text_with_breaks
    facility_ref = f"rea:facility:{_slug(title)}"
    address_match = re.search(r"Dove siamo:\s*(.+?)(?:\n|Cosa conferire|Modalità di accesso|$)", text, re.IGNORECASE)
    address = clean_text(address_match.group(1)) if address_match else None
    source = _source(url, retrieved_at, html, "rea_centre_html")
    owner_context = owner_context or context
    records = [make_record(record_type="facility", natural_key=facility_ref, payload={"name": title, "municipality_ref": owner_context.municipality_ref, "facility_type": "collection_centre", "address_raw": address, "location": None, "phone": None, "email": None, "operational_status": "open", "status_raw": None}, source=source, evidence_selector="main", evidence_quote=text[:1000])]
    records.append(make_record(record_type="facility_access", natural_key=f"{facility_ref}:access:{context.istat_code}:all", payload={"facility_ref": facility_ref, "municipality_ref": context.municipality_ref, "user_type": "all", "allowed": True, "requirements_raw": text[:5000], "booking_required": None, "information_urls": [url], "contact_phone": None, "contact_email": None}, source=source, evidence_selector="main", evidence_quote=text[:1000]))
    descriptions = _accepted_descriptions(content)
    if descriptions:
        for index, description in enumerate(descriptions):
            if description:
                records.append(make_record(record_type="facility_acceptance", natural_key=f"{facility_ref}:description:{index}:{_slug(description[:60])}", payload={"facility_ref": facility_ref, "eer_code_raw": None, "eer_code_normalized": None, "eer_code_status": "unmapped_description", "reconciliation_basis": None, "hazardous": None, "description_raw": description, "operational_group": None, "user_type": "unspecified", "quantity_limit_raw": None, "notes_raw": "La fonte REA non pubblica il codice EER per questa voce; pericolosità non determinabile dal solo elenco"}, source=source, evidence_selector="main", evidence_quote=description))
    when_match = re.search(r"Quando:\s*(.+?)\s*(?:Dove siamo:|Cosa conferire|$)", text, re.IGNORECASE | re.DOTALL)
    if when_match:
        raw = clean_text(when_match.group(1))
        records.append(make_record(record_type="opening_period", natural_key=f"{facility_ref}:opening:published", payload={"facility_ref": facility_ref, "period_label": "Orari pubblicati", "start_month_day": None, "end_month_day": None, "weekly_intervals": [], "exceptions_raw": raw}, source=source, evidence_selector="main", evidence_quote=raw))
    return records


def materialize_rea_services(
    municipalities: list[dict[str, Any]], manifest: dict[str, Any], snapshot_root: Path,
    rifiutario_json: str, retrieved_at: datetime,
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    html_pages = []
    for page in manifest["pages"]:
        if page["status"] == "snapshot" and page["content_type"] != "application/pdf" and page["snapshot"].endswith(".html"):
            html_pages.append((page, (snapshot_root / page["snapshot"]).read_text(encoding="utf-8", errors="replace")))
    centre_pages = [(page, html) for page, html in html_pages if page["category"] == "centre_detail"]
    rifiutario = json.loads(rifiutario_json)
    unresolved = sum(not item.get("destination") for item in rifiutario["items"])
    results: dict[str, list[dict[str, Any]]] = {}
    reports = []
    contexts = {
        item["source_slug"]: MunicipalityContext(item["name"], item["istat_code"], item["source_slug"])
        for item in municipalities
    }
    for municipality in municipalities:
        context = MunicipalityContext(municipality["name"], municipality["istat_code"], municipality["source_slug"])
        records = extract_rea_waste_lookup(context, retrieved_at, rifiutario["source_url"], rifiutario_json)
        relevant = [(page["final_url"] or page["url"], html) for page, html in html_pages if municipality["istat_code"] in page.get("municipality_istats", [])]
        service_records, warnings = extract_rea_collection_pages(context, retrieved_at, relevant)
        records.extend(service_records)
        linked_centres = {_canonical_url(link) for page_url, html in relevant for link, _ in _links(html, page_url) if urlparse(link).path.startswith("/centri-di-raccolta/") and not re.fullmatch(r"/centri-di-raccolta/(?:page/\d+/)?", urlparse(link).path)}
        municipal_slug = municipality["source_slug"]
        permitted_centres = _CENTRE_ACCESS.get(municipal_slug, {municipal_slug})
        for page, html in centre_pages:
            centre_url = _canonical_url(page["final_url"] or page["url"])
            centre_slug = urlparse(centre_url).path.rstrip("/").split("/")[-1]
            if centre_url in linked_centres or centre_slug in permitted_centres:
                owner_slug = _CENTRE_OWNER.get(centre_slug, centre_slug)
                records.extend(extract_rea_centre(context, retrieved_at, centre_url, html, contexts.get(owner_slug, context)))
        pdf_count = sum(page["category"] == "municipality_document" and municipality["istat_code"] in page.get("municipality_istats", []) and page["status"] == "snapshot" for page in manifest["pages"])
        if pdf_count:
            warnings.append({"code": "calendar_pdfs_inventoried", "detail": f"{pdf_count} PDF comunali acquisiti e conservati; estrazione strutturata dei calendari ancora da completare", "url": municipality["homepage_url"]})
        if unresolved:
            warnings.append({"code": "waste_lookup_destinations_missing", "detail": f"{unresolved} voci REA non hanno una destinazione pubblicata", "url": rifiutario["source_url"]})
        results[municipality["source_slug"]] = records
        counts: dict[str, int] = {}
        for record in records:
            counts[record["record_type"]] = counts.get(record["record_type"], 0) + 1
        available = sum(municipality["istat_code"] in page.get("municipality_istats", []) and page["status"] == "snapshot" for page in manifest["pages"])
        reports.append({"municipality": municipality["name"], "istat_code": municipality["istat_code"], "pages_available": available, "pages_materialized": available - pdf_count, "equivalent_pages": [], "records": len(records), "records_by_type": counts, "warnings": warnings})
    return results, reports
