from __future__ import annotations

from collections import deque
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import time
from typing import Any
from urllib import robotparser
from urllib.parse import urljoin, urlparse, urlunparse
from urllib.request import Request, urlopen

from .ato_costa import MunicipalityContext
from .html import Element, clean_text, parse_html
from .records import SourceDocument, make_record


GEOFOR_ROOT = "https://www.geofor.it"
GEOFOR_RIFIUTARIO = f"{GEOFOR_ROOT}/dove-lo-butto/"
GEOFOR_CENTRES = f"{GEOFOR_ROOT}/centro-di-raccolta/"
GEOFOR_PICKUP = f"{GEOFOR_ROOT}/prenotazione-servizi-e-segnalazioni/"
_RULES = (
    ("Grigio-Contenitore Indifferenziato", "Rifiuto residuo", "contenitore", "grigio", "container"),
    ("Marrone-Contenitore Organico", "Rifiuti organici", "contenitore", "marrone", "container"),
    ("Azzurro-Contenitore Multimateriale", "Imballaggi in multimateriale", "contenitore", "azzurro", "container"),
    ("Sacco-Contenitore Carta", "Carta e cartone", "sacco o contenitore", None, "mixed"),
    ("Contenitore Per Vetro-Campana Verde", "Vetro", "campana", "verde", "container"),
)


def _slug(value: str) -> str:
    value = value.casefold().translate(str.maketrans("àèéìòù", "aeeiou"))
    return re.sub(r"[^a-z0-9]+", "-", value).strip("-") or "unknown"


def _canonical(url: str) -> str:
    parsed = urlparse(url)
    path = re.sub(r"/{2,}", "/", parsed.path)
    return urlunparse((parsed.scheme or "https", parsed.netloc, path, "", parsed.query, ""))


def _links(html: str, base: str) -> list[tuple[str, str]]:
    root = parse_html(html)
    result = []
    for item in root.find_all(lambda node: node.tag == "a" and bool(node.attrs.get("href"))):
        url = _canonical(urljoin(base, item.attrs["href"]))
        if urlparse(url).netloc == "www.geofor.it":
            result.append((url, clean_text(item.text)))
    return result


def crawl_geofor(
    municipalities: list[dict[str, Any]], snapshot_root: Path, observed_at: datetime,
    user_agent: str, delay: float = 1.0, previous_manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    robots_url = f"{GEOFOR_ROOT}/robots.txt"
    with urlopen(Request(robots_url, headers={"User-Agent": user_agent}), timeout=30) as response:
        lines = response.read().decode("utf-8", errors="replace").splitlines()
    robots = robotparser.RobotFileParser(robots_url)
    robots.parse(lines)
    effective_delay = max(delay, robots.crawl_delay(user_agent) or robots.crawl_delay("*") or 1.0)

    active_homepages = {_canonical(item["homepage_url"]) for item in municipalities}
    completed = {
        page["url"]: page for page in (previous_manifest or {}).get("pages", [])
        if page["category"] != "municipality" or page["url"] in active_homepages
    }
    queue: deque[dict[str, Any]] = deque()
    queued: dict[str, dict[str, Any]] = {}

    def enqueue(url: str, category: str, istats: list[str]) -> None:
        url = _canonical(url)
        if url in completed:
            completed[url]["municipality_istats"] = sorted(set(completed[url].get("municipality_istats", []) + istats))
        elif url in queued:
            queued[url]["municipality_istats"] = sorted(set(queued[url]["municipality_istats"] + istats))
        else:
            job = {"url": url, "category": category, "municipality_istats": istats}
            queued[url] = job
            queue.append(job)

    for municipality in municipalities:
        enqueue(municipality["homepage_url"], "municipality", [municipality["istat_code"]])
    enqueue(GEOFOR_RIFIUTARIO, "waste_lookup", [])
    enqueue(GEOFOR_CENTRES, "centre_index", [])
    enqueue(GEOFOR_PICKUP, "shared_pickup", [])

    while queue:
        seed = queue.popleft()
        job = queued.pop(seed["url"])
        url = job["url"]
        if not robots.can_fetch(user_agent, url):
            completed[url] = {**job, "status": "blocked_by_robots", "final_url": None, "content_type": None, "snapshot": None, "sha256": None}
            continue
        try:
            request = Request(url, headers={"User-Agent": user_agent, "Accept": "text/html,application/pdf"})
            with urlopen(request, timeout=45) as response:
                body = response.read()
                final_url = _canonical(response.geturl())
                content_type = response.headers.get_content_type()
            digest = hashlib.sha256(body).hexdigest()
            extension = ".pdf" if content_type == "application/pdf" or final_url.lower().endswith(".pdf") else ".html"
            snapshot = snapshot_root / f"{digest}{extension}"
            snapshot.parent.mkdir(parents=True, exist_ok=True)
            if not snapshot.exists():
                snapshot.write_bytes(body)
            entry = {**job, "status": "snapshot", "final_url": final_url, "content_type": content_type, "snapshot": snapshot.name, "sha256": digest}
            completed[url] = entry
            if extension == ".html" and job["category"] in {"municipality", "calendar", "centre", "pickup", "other"}:
                html = body.decode("utf-8", errors="replace")
                base_path = urlparse(final_url).path.split("/")[1]
                for discovered, _ in _links(html, final_url):
                    path = urlparse(discovered).path
                    category = None
                    if path.lower().endswith(".pdf"):
                        category = "municipality_document"
                    elif job["category"] == "municipality" and path.startswith(f"/{base_path}/") and path != urlparse(final_url).path:
                        lowered = path.casefold()
                        category = "calendar" if "calendario" in lowered else "centre" if "centro-di-raccolta" in lowered else "pickup" if "prenota" in lowered or "ritir" in lowered else "other"
                    if category:
                        enqueue(discovered, category, job["municipality_istats"])
            time.sleep(effective_delay)
        except Exception as error:
            completed[url] = {**job, "status": "error", "final_url": None, "content_type": None, "snapshot": None, "sha256": None, "error": f"{type(error).__name__}: {error}"}
            time.sleep(effective_delay)

    pages = sorted(completed.values(), key=lambda item: (item["category"], item["url"]))
    categories = sorted({page["category"] for page in pages})
    return {
        "observed_at": observed_at.isoformat(), "publisher": "GEOFOR S.p.A.",
        "robots_url": robots_url, "crawl_delay_seconds": effective_delay, "pages": pages,
        "summary": {
            "checked": len(pages), "snapshots": sum(page["status"] == "snapshot" for page in pages),
            "blocked_by_robots": sum(page["status"] == "blocked_by_robots" for page in pages),
            "errors": sum(page["status"] == "error" for page in pages),
            "by_category": {category: sum(page["category"] == category for page in pages) for category in categories},
        },
    }


def _source(url: str, retrieved_at: datetime, content: str, parser: str) -> SourceDocument:
    return SourceDocument(url, retrieved_at, content, publisher="GEOFOR S.p.A.", parser=parser, parser_version="0.1.0")


def parse_rifiutario(html: str) -> list[dict[str, Any]]:
    marker = re.search(r"var\s+rifiutario_data\s*=\s*", html)
    if not marker:
        return []
    data, _ = json.JSONDecoder().raw_decode(html[marker.end():])
    return data


def _waste_and_rules(context: MunicipalityContext, retrieved_at: datetime, url: str, html: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    source = _source(url, retrieved_at, html, "geofor_embedded_rifiutario")
    items = parse_rifiutario(html)
    records = []
    for item in items:
        term = clean_text(str(item.get("DescrizioneMateriale") or ""))
        if not term:
            continue
        category = clean_text(str(item.get("DescrizioneRifiuto") or "")) or None
        eer = clean_text(str(item.get("CER") or "")) or None
        eer_description = clean_text(str(item.get("DescrizioneCer") or "")) or None
        instructions = [f"Categoria GEOFOR: {category}" if category else None, f"EER {eer}: {eer_description or 'descrizione non pubblicata'}" if eer else None]
        records.append(make_record(
            record_type="waste_lookup", natural_key=f"waste-lookup:{context.istat_code}:{_slug(term)}",
            payload={"municipality_ref": context.municipality_ref, "term": term, "destination_raw": clean_text(str(item.get("DescrizioneDestinazione") or "")) or None, "resolution_status": "resolved" if item.get("DescrizioneDestinazione") else "missing_destination", "instructions_raw": " | ".join(part for part in instructions if part) or None},
            source=source, evidence_kind="json", evidence_selector=f"rifiutario_data[CodiceMateriale='{item.get('CodiceMateriale')}']", evidence_quote=f"{term}: {item.get('DescrizioneDestinazione') or '[destinazione non pubblicata]'}",
        ))
    zone_ref = f"service-zone:{context.istat_code}:default"
    records.append(make_record(record_type="service_zone", natural_key=zone_ref, payload={"municipality_ref": context.municipality_ref, "name": "Intero territorio comunale", "scope_type": "municipality_default", "included_places_raw": None, "excluded_places_raw": None, "geometry_geojson": None}, source=source, evidence_kind="json", evidence_selector="rifiutario_data", evidence_quote="Destinazioni del rifiutario GEOFOR"))
    destinations = {item.get("DescrizioneDestinazione") for item in items}
    for raw, stream, container, color, mode in _RULES:
        if raw not in destinations:
            continue
        records.append(make_record(record_type="collection_rule", natural_key=f"collection-rule:{context.istat_code}:default:{_slug(stream)}", payload={"municipality_ref": context.municipality_ref, "zone_ref": zone_ref, "user_type": "all", "collection_method": "other", "stream_name": stream, "included_materials_raw": None, "container_type": container, "container_color": color, "access_credential": None, "presentation": {"mode": mode, "max_volume_l": None, "instructions_raw": raw}, "schedule_raw": "Consultare il calendario comunale GEOFOR"}, source=source, evidence_kind="json", evidence_selector="rifiutario_data", evidence_quote=raw))
    return records, items


def _time(value: str) -> str:
    match = re.search(r"([0-2]?\d)[.:]([0-5]\d)", value)
    return f"{int(match.group(1)):02d}:{match.group(2)}" if match else ""


def _facilities(context: MunicipalityContext, retrieved_at: datetime, url: str, html: str, waste_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    root = parse_html(html)
    source = _source(url, retrieved_at, html, "geofor_centre_html")
    records = []
    for index, block in enumerate(root.find_all(lambda item: item.tag == "div" and "cdr" in item.classes)):
        name_element = block.find_first(lambda item: item.tag == "div" and "nome" in item.classes)
        if not name_element:
            continue
        name = re.sub(r"\s*vedi mappa\s*$", "", name_element.text, flags=re.IGNORECASE).strip()
        facility_ref = f"geofor:facility:{_slug(name)}"
        map_link = name_element.find_first(lambda item: item.tag == "a" and "maps" in item.attrs.get("href", ""))
        coordinates = re.search(r"[?&]q=(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)", map_link.attrs.get("href", "")) if map_link else None
        location = {"latitude": float(coordinates.group(1)), "longitude": float(coordinates.group(2)), "method": "map_link", "accuracy_m": None} if coordinates else None
        address = name.split(" - ", 1)[1] if " - " in name else None
        records.append(make_record(record_type="facility", natural_key=facility_ref, payload={"name": name, "municipality_ref": context.municipality_ref, "facility_type": "collection_centre", "address_raw": address, "location": location, "phone": "800959095", "email": None, "operational_status": "unknown", "status_raw": None}, source=source, evidence_selector="div.cdr", evidence_quote=block.text[:1000]))
        records.append(make_record(record_type="facility_access", natural_key=f"{facility_ref}:access:{context.istat_code}:domestic", payload={"facility_ref": facility_ref, "municipality_ref": context.municipality_ref, "user_type": "domestic", "allowed": True, "requirements_raw": "Presentare la tessera sanitaria dell'intestatario dell'utenza domestica; scarico dei rifiuti in autonomia seguendo le indicazioni degli operatori.", "booking_required": False, "information_urls": [url], "contact_phone": "800959095", "contact_email": None}, source=source, evidence_selector="#come-funziona", evidence_quote="Lettura della tessera sanitaria e pesatura"))
        table = block.find_first(lambda item: item.tag == "table")
        intervals = []
        if table:
            rows = table.find_all(lambda item: item.tag == "tr")
            if len(rows) >= 2:
                headers = [cell.text for cell in rows[0].find_all(lambda item: item.tag in {"td", "th"})]
                values = [cell.text for cell in rows[1].find_all(lambda item: item.tag in {"td", "th"})]
                for weekday, value in enumerate(values[:len(headers)], 1):
                    ranges = re.findall(r"([0-2]?\d[.:][0-5]\d)\s*[-–]\s*([0-2]?\d[.:][0-5]\d)", value)
                    for opens, closes in ranges:
                        intervals.append({"weekday": weekday, "opens": _time(opens), "closes": _time(closes)})
        records.append(make_record(record_type="opening_period", natural_key=f"{facility_ref}:opening:published", payload={"facility_ref": facility_ref, "period_label": "Orario pubblicato", "start_month_day": None, "end_month_day": None, "weekly_intervals": intervals, "exceptions_raw": "Chiusure straordinarie e festività indicate nella pagina del centro"}, source=source, evidence_kind="table", evidence_selector="div.cdr table", evidence_quote=table.text if table else "Orari non strutturati"))
        for item in waste_items:
            eer = clean_text(str(item.get("CER") or ""))
            term = clean_text(str(item.get("DescrizioneMateriale") or ""))
            if not item.get("FlagCdR") or not eer or not term:
                continue
            category = clean_text(str(item.get("DescrizioneRifiuto") or ""))
            records.append(make_record(record_type="facility_acceptance", natural_key=f"{facility_ref}:eer:{eer}:{_slug(term)}", payload={"facility_ref": facility_ref, "eer_code_raw": eer, "eer_code_normalized": eer if re.fullmatch(r"\d{6}", eer) else None, "eer_code_status": "exact" if re.fullmatch(r"\d{6}", eer) else "malformed", "reconciliation_basis": None, "hazardous": True if "pericol" in category.casefold() else False, "description_raw": term, "operational_group": category or None, "user_type": "unspecified", "quantity_limit_raw": None, "notes_raw": clean_text(str(item.get("DescrizioneCer") or "")) or None}, source=source, evidence_kind="json", evidence_selector=f"rifiutario_data[CodiceMateriale='{item.get('CodiceMateriale')}']", evidence_quote=f"{term}: CER {eer}, FlagCdR=true"))
    return records


def _pickups(context: MunicipalityContext, retrieved_at: datetime, url: str, html: str) -> list[dict[str, Any]]:
    root = parse_html(html)
    text = root.text
    source = _source(url, retrieved_at, html, "geofor_pickup_html")
    web = next((link for link, _ in _links(html, url) if "sportello.geofor.it" in link), "https://sportello.geofor.it/")
    app = next((link for link, _ in _links(html, url) if "play.google.com" in link), None)
    methods = [{"method": "web", "value": web, "hours_raw": "Servizio online 24 ore su 24"}, {"method": "phone", "value": "800959095", "hours_raw": "Dal lunedì al venerdì 8:30-17:00"}]
    if app:
        methods.append({"method": "app", "value": app, "hours_raw": None})
    kinds = []
    for token, name in (("ingombranti", "Rifiuti ingombranti"), ("tessili", "Rifiuti tessili"), ("sfalci", "Sfalci e potature")):
        if token in text.casefold():
            kinds.append(name)
    return [make_record(record_type="pickup_service", natural_key=f"geofor:pickup:{context.istat_code}:{_slug(name)}", payload={"municipality_ref": context.municipality_ref, "zone_ref": None, "user_type": "domestic", "accepted_waste_raw": name, "booking_methods": methods, "max_items": None, "quantity_limit_raw": None, "placement_instructions_raw": text[:4000], "booking_required": True}, source=source, evidence_selector="main", evidence_quote=text[:1000]) for name in kinds]


def materialize_geofor(
    municipalities: list[dict[str, Any]], manifest: dict[str, Any], snapshot_root: Path,
    retrieved_at: datetime,
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    pages = []
    for page in manifest["pages"]:
        if page["status"] == "snapshot" and page["snapshot"].endswith(".html"):
            pages.append((page, (snapshot_root / page["snapshot"]).read_text(encoding="utf-8", errors="replace")))
    waste_page, waste_html = next((page, html) for page, html in pages if page["category"] == "waste_lookup")
    results = {}
    reports = []
    for municipality in municipalities:
        context = MunicipalityContext(municipality["name"], municipality["istat_code"], municipality["source_slug"])
        records, waste_items = _waste_and_rules(context, retrieved_at, waste_page["final_url"] or waste_page["url"], waste_html)
        relevant = [(page, html) for page, html in pages if municipality["istat_code"] in page.get("municipality_istats", [])]
        for page, html in relevant:
            url = page["final_url"] or page["url"]
            if page["category"] == "centre":
                records.extend(_facilities(context, retrieved_at, url, html, waste_items))
            elif page["category"] == "pickup":
                records.extend(_pickups(context, retrieved_at, url, html))
        pdf_count = sum(page["category"] == "municipality_document" and municipality["istat_code"] in page.get("municipality_istats", []) and page["status"] == "snapshot" for page in manifest["pages"])
        warnings = []
        if pdf_count:
            warnings.append({"code": "calendar_pdfs_inventoried", "detail": f"{pdf_count} PDF comunali acquisiti; estrazione strutturata dei calendari ancora da completare", "url": municipality["homepage_url"]})
        if not any(record["record_type"] == "facility" for record in records):
            warnings.append({"code": "facility_page_missing", "detail": "Nessun centro comunale pubblicato o pagina non disponibile", "url": municipality["homepage_url"]})
        counts: dict[str, int] = {}
        for record in records:
            counts[record["record_type"]] = counts.get(record["record_type"], 0) + 1
        results[municipality["source_slug"]] = records
        available = sum(municipality["istat_code"] in page.get("municipality_istats", []) and page["status"] == "snapshot" for page in manifest["pages"])
        reports.append({"municipality": municipality["name"], "istat_code": municipality["istat_code"], "pages_available": available + 1, "pages_materialized": available + 1 - pdf_count, "equivalent_pages": [], "records": len(records), "records_by_type": counts, "warnings": warnings})
    return results, reports
