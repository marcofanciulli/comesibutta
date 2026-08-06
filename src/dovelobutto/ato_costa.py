from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import re
from typing import Any
import xml.etree.ElementTree as ET

from .html import clean_text, parse_html
from .records import SourceDocument, make_record


@dataclass(frozen=True)
class MunicipalityContext:
    name: str
    istat_code: str
    slug: str

    @property
    def municipality_ref(self) -> str:
        return f"istat:{self.istat_code}"


ESA_STREAMS = (
    "Rifiuti organici",
    "Plastica e metallo",
    "Carta e cartone",
    "Vetro",
    "Rifiuto residuo",
)


def extract_esa_bundle(
    context: MunicipalityContext,
    retrieved_at: datetime,
    pages: list[tuple[str, str]],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    records: list[dict[str, Any]] = []
    warnings: list[dict[str, str]] = []
    for url, html in pages:
        source = SourceDocument(
            url,
            retrieved_at,
            html,
            publisher="ESA S.p.A.",
            parser="esa_html",
            parser_version="0.1.0",
        )
        if "/raccolta-differenziata/" in url:
            records.extend(_extract_esa_collection(context, source, html))
        elif "/centri-di-raccolta/" in url:
            records.extend(_extract_esa_facilities(context, source, html))
    if not any(record["record_type"] == "waste_lookup" for record in records):
        warnings.append({
            "code": "waste_lookup_missing",
            "detail": "Il rifiutario ESA non contiene coppie nome-destinazione",
            "url": next((url for url, _ in pages if "/raccolta-differenziata/" in url), ""),
        })
    return records, warnings


def extract_rea_waste_lookup(
    context: MunicipalityContext,
    retrieved_at: datetime,
    url: str,
    json_text: str,
) -> list[dict[str, Any]]:
    source = SourceDocument(
        url,
        retrieved_at,
        json_text,
        publisher="REA S.p.A.",
        parser="rea_rifiutario_json",
        parser_version="0.1.0",
    )
    data = json.loads(json_text)
    return [
        make_record(
            record_type="waste_lookup",
            natural_key=f"waste-lookup:{context.istat_code}:{_slug(item['name'])}",
            payload={
                "municipality_ref": context.municipality_ref,
                "term": clean_text(item["name"]),
                "destination_raw": clean_text(item.get("destination", "")) or None,
                "resolution_status": (
                    "resolved" if clean_text(item.get("destination", "")) else "missing_destination"
                ),
                "instructions_raw": (
                    f"Categoria REA: {clean_text(item['category'])}"
                    if item.get("category") else None
                ),
            },
            source=source,
            evidence_kind="json",
            evidence_selector=f"items[id='{item.get('id', '')}']",
            evidence_quote=f"{item['name']}: {item.get('destination') or '[destinazione non pubblicata]'}",
        )
        for item in data["items"]
        if item.get("name")
    ]


def extract_aamps_waste_lookup(
    context: MunicipalityContext,
    retrieved_at: datetime,
    url: str,
    bbox_html: str,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    source = SourceDocument(
        url,
        retrieved_at,
        bbox_html,
        publisher="AAMPS S.p.A.",
        parser="aamps_pdf_bbox",
        parser_version="0.1.0",
    )
    root = ET.fromstring(bbox_html)
    namespace = {"x": "http://www.w3.org/1999/xhtml"}
    pairs: list[tuple[int, str, str]] = []
    warnings: list[dict[str, str]] = []
    for page_number, page in enumerate(root.findall(".//x:page", namespace), 1):
        columns: dict[int, list[tuple[float, str]]] = {0: [], 1: [], 2: [], 3: []}
        for line in page.findall(".//x:line", namespace):
            x = float(line.attrib["xMin"])
            y = float(line.attrib["yMin"])
            if y < 100 or y > 520:
                continue
            text = clean_text(" ".join(word.text or "" for word in line.findall("x:word", namespace)))
            column = 0 if x < 200 else 1 if x < 440 else 2 if x < 630 else 3
            columns[column].append((y, text))
        for item_column, destination_column in ((0, 1), (2, 3)):
            destinations = columns[destination_column]
            for y, term in columns[item_column]:
                if len(term) == 1 and term.isalpha():
                    continue
                candidates = [
                    (abs(destination_y - y), destination)
                    for destination_y, destination in destinations
                    if abs(destination_y - y) <= 1.0
                ]
                destination = min(candidates)[1] if candidates else ""
                if not destination:
                    warnings.append({
                        "code": "pdf_destination_missing",
                        "detail": f"Pagina {page_number}: {term}",
                        "url": url,
                    })
                elif _suspicious_aamps_destination(destination):
                    warnings.append({
                        "code": "possible_pdf_column_wrap",
                        "detail": f"Pagina {page_number}: {term} -> {destination}",
                        "url": url,
                    })
                pairs.append((page_number, term, destination))
    records = [
        make_record(
            record_type="waste_lookup",
            natural_key=f"waste-lookup:{context.istat_code}:{_slug(term)}",
            payload={
                "municipality_ref": context.municipality_ref,
                "term": term,
                "destination_raw": destination or None,
                "resolution_status": "resolved" if destination else "missing_destination",
                "instructions_raw": "Guida AAMPS pubblicata nel 2017",
            },
            source=source,
            evidence_kind="pdf",
            evidence_selector=f"page:{page_number}",
            evidence_quote=f"{term}: {destination or '[destinazione non leggibile]'}",
            confidence="medium" if _suspicious_aamps_destination(destination) else "high",
        )
        for page_number, term, destination in pairs
    ]
    return records, warnings


def _suspicious_aamps_destination(value: str) -> bool:
    compact = value.casefold().replace(" ", "")
    return (
        value.casefold().startswith("raccolta o servizio")
        or "biancocentri" in compact
        or "ingombranticentri" in compact
    )


def _extract_esa_collection(
    context: MunicipalityContext,
    source: SourceDocument,
    html: str,
) -> list[dict[str, Any]]:
    root = parse_html(html)
    records: list[dict[str, Any]] = []
    zone_ref = f"service-zone:{context.istat_code}:default"
    introduction = next((
        element.text for element in root.find_all(lambda item: item.tag == "p")
        if "In tutta l’Isola d’Elba è attiva" in element.text
    ), "Raccolta differenziata porta a porta attiva in tutta l'Isola d'Elba")
    records.append(make_record(
        record_type="service_zone",
        natural_key=zone_ref,
        payload={
            "municipality_ref": context.municipality_ref,
            "name": "Intero territorio comunale",
            "scope_type": "municipality_default",
            "included_places_raw": None,
            "excluded_places_raw": None,
            "geometry_geojson": None,
        },
        source=source,
        evidence_selector="main",
        evidence_quote=introduction,
    ))
    for stream in ESA_STREAMS:
        records.append(make_record(
            record_type="collection_rule",
            natural_key=f"collection-rule:{context.istat_code}:default:{_slug(stream)}",
            payload={
                "municipality_ref": context.municipality_ref,
                "zone_ref": zone_ref,
                "user_type": "domestic",
                "collection_method": "door_to_door",
                "stream_name": stream,
                "included_materials_raw": introduction,
                "container_type": "kit ESA con sacchetti e bidoncini specifici",
                "container_color": None,
                "access_credential": None,
                "presentation": {
                    "mode": "unspecified",
                    "max_volume_l": None,
                    "instructions_raw": (
                        "Utilizzare i sacchetti e i contenitori in dotazione o con "
                        "caratteristiche analoghe; rispettare il calendario comunale."
                    ),
                },
                "schedule_raw": "Secondo il calendario in vigore nel Comune",
            },
            source=source,
            evidence_selector="main",
            evidence_quote=introduction,
        ))
    for item in root.find_all(
        lambda element: element.tag == "li"
        and bool(element.attrs.get("data-name"))
        and bool(element.attrs.get("data-destination"))
    ):
        term = clean_text(item.attrs["data-name"])
        destination = clean_text(item.attrs["data-destination"])
        records.append(make_record(
            record_type="waste_lookup",
            natural_key=f"waste-lookup:{context.istat_code}:{_slug(term)}",
            payload={
                "municipality_ref": context.municipality_ref,
                "term": term,
                "destination_raw": destination,
                "instructions_raw": None,
            },
            source=source,
            evidence_selector=f"li[data-name='{term}']",
            evidence_quote=f"{term}: {destination}",
        ))
    return records


def _extract_esa_facilities(
    context: MunicipalityContext,
    source: SourceDocument,
    html: str,
) -> list[dict[str, Any]]:
    root = parse_html(html)
    records: list[dict[str, Any]] = []
    access_quote = next((
        element.text for element in root.find_all(lambda item: item.tag == "p")
        if "regolarmente iscritte a ruolo TARI" in element.text
    ), None)
    for link in root.find_all(lambda element: element.tag == "a"):
        name = clean_text(link.text)
        if not name.startswith("CDR ") or not _facility_belongs_to(name, context.name):
            continue
        facility_ref = f"facility:esa:{_slug(name)}"
        records.append(make_record(
            record_type="facility",
            natural_key=facility_ref,
            payload={
                "name": name,
                "municipality_ref": context.municipality_ref,
                "facility_type": "collection_centre",
                "address_raw": re.sub(r"^CDR\s+", "", name),
                "location": None,
                "phone": "800 688 850",
                "email": None,
                "operational_status": "open",
                "status_raw": None,
            },
            source=source,
            evidence_selector=f"a[href='{link.attrs.get('href', '')}']",
            evidence_quote=name,
        ))
        records.append(make_record(
            record_type="facility_access",
            natural_key=f"facility-access:{context.istat_code}:{facility_ref}:domestic",
            payload={
                "facility_ref": facility_ref,
                "municipality_ref": context.municipality_ref,
                "user_type": "domestic",
                "allowed": True,
                "requirements_raw": access_quote,
                "booking_required": False,
                "information_urls": [link.attrs["href"]] if link.attrs.get("href") else [],
                "contact_phone": "800 688 850",
                "contact_email": None,
            },
            source=source,
            evidence_selector="main",
            evidence_quote=access_quote,
        ))
    return records


def _facility_belongs_to(facility_name: str, municipality: str) -> bool:
    name = facility_name.casefold()
    municipality_key = municipality.casefold()
    if municipality == "Campo nell'Elba":
        return "campo dell'elba" in name
    if municipality == "Capoliveri":
        return "capoliveri" in name or "lacona" in name
    if municipality == "Rio":
        return "cavo" in name or re.search(r"\brio\b", name) is not None
    if municipality == "Marciana":
        return "marciana" in name and "marina" not in name
    return municipality_key in name


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
