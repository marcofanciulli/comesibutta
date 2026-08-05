from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
import re
import unicodedata
from typing import Any
from urllib.parse import urlparse

from .html import Element, clean_text, has_class, parse_html
from .records import SourceDocument, make_record


def read_istat_municipalities(path: Path) -> dict[str, dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return {_name_key(row["name"]): row for row in rows}


def extract_sei_municipality_registry(
    html: str,
    url: str,
    retrieved_at: datetime,
    istat_by_name: dict[str, dict[str, str]],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    source = SourceDocument(url, retrieved_at, html)
    root = parse_html(html)
    records: list[dict[str, Any]] = []
    warnings: list[dict[str, str]] = []
    for link in root.find_all(has_class("comune")):
        name = link.text
        istat = istat_by_name.get(_name_key(name))
        if not istat:
            warnings.append({"code": "istat_match_missing", "detail": name})
            continue
        municipality_item = _ancestor(link, "li")
        links = municipality_item.find_all(lambda element: element.tag == "a") if municipality_item else [link]
        homepage_url = link.attrs.get("href", "")
        service_urls = _service_urls(links, homepage_url)
        slug = urlparse(homepage_url).path.rstrip("/").split("/")[-1]
        records.append(make_record(
            record_type="municipality",
            natural_key=f"istat:{istat['istat_code']}",
            payload={
                "istat_code": istat["istat_code"],
                "name": istat["name"],
                "province_code": istat["province_code"],
                "region_code": istat["region_code"],
                "ato_ref": "ato-toscana-sud",
                "operator_ref": "sei-toscana",
                "source_slug": slug,
                "homepage_url": homepage_url,
                "service_urls": service_urls,
            },
            source=source,
            evidence_selector=f"a.comune[data-provincia='{link.attrs.get('data-provincia', '')}']",
            evidence_quote=municipality_item.text[:1000] if municipality_item else name,
        ))
    return records, warnings


def _service_urls(links: list[Element], homepage_url: str) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {
        "collection": [],
        "facilities": [],
        "pickup": [],
        "street_cleaning": [],
        "other": [],
    }
    for link in links:
        href = link.attrs.get("href", "")
        if not href or href == homepage_url:
            continue
        path = urlparse(href).path.lower()
        if path.endswith("/raccolta-rifiuti"):
            category = "collection"
        elif re.search(r"/centr[oi]-di-raccolta$", path):
            category = "facilities"
        elif path.endswith("/ritiro-ingombranti"):
            category = "pickup"
        elif path.endswith("/spazzamento-lavaggio-stradale"):
            category = "street_cleaning"
        else:
            category = "other"
        if href not in result[category]:
            result[category].append(href)
    return result


def _ancestor(element: Element, tag: str) -> Element | None:
    parent = element.parent
    while parent:
        if parent.tag == tag:
            return parent
        parent = parent.parent
    return None


def _name_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    ascii_text = "".join(character for character in normalized if not unicodedata.combining(character))
    return re.sub(r"[^a-z0-9]+", " ", clean_text(ascii_text)).strip()
