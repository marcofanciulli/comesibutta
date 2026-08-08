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


ATO_COSTA_SOURCE_URL = (
    "https://www.atotoscanacosta.it/wp-content/plugins/allegati-rev2/"
    "includes/download.php?id=3140"
)

ATO_CENTRO_SOURCE_URL = "https://www.atotoscanacentro.it/servizi/menu/dinamica.aspx?ID=16915"
ATO_CENTRO_SCOPE_STATEMENT = (
    "ATO Toscana Centro comprende i Comuni delle province di Firenze, Prato e "
    "Pistoia, esclusi Marradi, Palazzuolo sul Senio e Firenzuola."
)
ATO_CENTRO_EXCLUDED = {"Marradi", "Palazzuolo sul Senio", "Firenzuola"}

LOCAL_OPERATORS = {
    "aamps": ("AAMPS S.p.A.", "https://www.aamps.livorno.it/"),
    "ascit": ("ASCIT S.p.A.", "https://www.ascit.it/"),
    "esa": ("ESA S.p.A.", "https://www.esaspa.it/"),
    "geofor": ("GEOFOR S.p.A.", "https://www.geofor.it/"),
    "rea": ("REA S.p.A.", "https://www.reaspa.it/"),
    "sea-ambiente": ("SEA Ambiente S.p.A.", "https://www.seaambiente-spa.it/"),
    "ersu": ("ERSU S.p.A.", "https://ersu.it/"),
    "lunigiana-ambiente": ("Lunigiana Ambiente S.r.l.", "https://www.lunigianaambiente.it/"),
    "gea": ("GEA S.r.l.", "https://www.geasrl.org/"),
    "asmiu": ("ASMIU S.r.l.", "https://www.asmiu.it/"),
    "retiambiente-carrara": ("RetiAmbiente Carrara S.r.l.", "https://www.retiambientecarrara.it/"),
    "sistema-ambiente": ("Sistema Ambiente S.p.A.", "https://www.sistemaambientelucca.it/"),
}

ATO_COSTA_ISTAT_NAME_ALIASES = {
    "vagli di sotto": "Vagli Sotto",
}


def extract_ato_costa_municipality_registry(
    csv_text: str,
    retrieved_at: datetime,
    istat_by_name: dict[str, dict[str, str]],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    source = SourceDocument(
        ATO_COSTA_SOURCE_URL,
        retrieved_at,
        csv_text,
        publisher="ATO Toscana Costa",
        parser="ato_costa_assignment_csv",
        parser_version="0.1.0",
    )
    records: list[dict[str, Any]] = []
    warnings: list[dict[str, str]] = []
    rows = list(csv.DictReader(csv_text.splitlines()))
    seen_istat: set[str] = set()
    for row in rows:
        name = row["name"]
        istat_name = ATO_COSTA_ISTAT_NAME_ALIASES.get(_name_key(name), name)
        istat = istat_by_name.get(_name_key(istat_name))
        if not istat:
            warnings.append({"code": "istat_match_missing", "detail": name})
            continue
        if istat["province_code"] != row["province_code"]:
            warnings.append({
                "code": "province_mismatch",
                "detail": f"{name}: fonte {row['province_code']}, ISTAT {istat['province_code']}",
            })
            continue
        if istat["istat_code"] in seen_istat:
            warnings.append({"code": "duplicate_municipality", "detail": name})
            continue
        seen_istat.add(istat["istat_code"])
        local_operator_ref = row["local_operator_ref"]
        local_operator_name, local_operator_url = LOCAL_OPERATORS[local_operator_ref]
        slug = _slugify(istat["name"])
        records.append(make_record(
            record_type="municipality",
            natural_key=f"istat:{istat['istat_code']}",
            payload={
                "istat_code": istat["istat_code"],
                "name": istat["name"],
                "province_code": istat["province_code"],
                "region_code": istat["region_code"],
                "ato_ref": "ato-toscana-costa",
                "operator_ref": "retiambiente",
                "local_operator_ref": local_operator_ref,
                "local_operator_name": local_operator_name,
                "local_operator_url": local_operator_url,
                "assignment_status": row["assignment_status"],
                "assignment_note": row["assignment_note"] or None,
                "source_slug": slug,
                "homepage_url": _ato_costa_homepage(local_operator_ref, slug),
                "service_urls": _ato_costa_service_urls(local_operator_ref, slug),
            },
            source=source,
            evidence_kind="pdf",
            evidence_selector=f"row:{row['order']}",
            evidence_quote=(
                f"{row['order']} {row['province_code']} {name} - {local_operator_name}"
                + (f" - {row['assignment_note']}" if row["assignment_note"] else "")
            ),
        ))
    return records, warnings


def read_istat_municipalities(path: Path) -> dict[str, dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    return {_name_key(row["name"]): row for row in rows}


def extract_ato_centro_municipality_registry(
    retrieved_at: datetime,
    istat_by_name: dict[str, dict[str, str]],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    source = SourceDocument(
        ATO_CENTRO_SOURCE_URL,
        retrieved_at,
        ATO_CENTRO_SCOPE_STATEMENT,
        publisher="ATO Toscana Centro",
        parser="ato_centro_istat_scope",
        parser_version="0.1.0",
    )
    municipalities = sorted(
        (
            municipality for municipality in istat_by_name.values()
            if municipality["province_code"] in {"FI", "PO", "PT"}
            and municipality["name"] not in ATO_CENTRO_EXCLUDED
        ),
        key=lambda municipality: (municipality["province_code"], municipality["name"]),
    )
    records = []
    for municipality in municipalities:
        slug = _slugify(municipality["name"])
        homepage = f"https://aliaestra.it/ambiente/comuni/{slug}"
        records.append(make_record(
            record_type="municipality",
            natural_key=f"istat:{municipality['istat_code']}",
            payload={
                "istat_code": municipality["istat_code"],
                "name": municipality["name"],
                "province_code": municipality["province_code"],
                "region_code": municipality["region_code"],
                "ato_ref": "ato-toscana-centro",
                "operator_ref": "plures-alia",
                "local_operator_ref": "plures-alia",
                "local_operator_name": "Plures Alia",
                "local_operator_url": "https://aliaestra.it/ambiente",
                "assignment_status": "active",
                "assignment_note": None,
                "source_slug": slug,
                "homepage_url": homepage,
                "service_urls": {
                    "collection": [
                        homepage,
                        "https://aliaestra.it/ambiente/raccolta-e-pulizia-strade/sistemi-di-raccolta/",
                        "https://aliaestra.it/ambiente/raccolta-e-pulizia-strade/kit-raccolta",
                    ],
                    "facilities": [
                        "https://aliaestra.it/ambiente/raccolta-e-pulizia-strade/dove-lo-porto",
                    ],
                    "pickup": ["https://aliaestra.it/ambiente/ritiri-ondemand"],
                    "street_cleaning": [],
                    "other": ["https://aliaestra.it/ambiente"],
                },
            },
            source=source,
            evidence_selector="main",
            evidence_quote=f"{ATO_CENTRO_SCOPE_STATEMENT} Comune incluso: {municipality['name']}.",
        ))
    warnings = []
    if len(municipalities) != 65:
        warnings.append({
            "code": "unexpected_municipality_count",
            "detail": f"Attesi 65 comuni, trovati {len(municipalities)}",
        })
    return records, warnings


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


def _slugify(value: str) -> str:
    return _name_key(value).replace(" ", "-")


def _ato_costa_homepage(local_operator_ref: str, slug: str) -> str:
    if local_operator_ref == "rea":
        overrides = {
            "castelnuovo-di-val-di-cecina": "https://www.reaspa.it/comuni/comune-di-castelnuovo-val-di-cecina/servizi/",
            "guardistallo": "https://www.reaspa.it/comuni/comune-guardistallo/",
            "monteverdi-marittimo": "https://www.reaspa.it/comuni/comune-di-monteverdi/",
        }
        if slug in overrides:
            return overrides[slug]
        return f"https://www.reaspa.it/comuni/comune-di-{slug}/"
    if local_operator_ref == "geofor":
        geofor_slug = {
            "montopoli-in-val-d-arno": "montopoli",
            "san-giuliano-terme": "s-giuliano-terme",
        }.get(slug, slug)
        return f"https://www.geofor.it/{geofor_slug}/"
    return LOCAL_OPERATORS[local_operator_ref][1]


def _ato_costa_service_urls(local_operator_ref: str, slug: str) -> dict[str, list[str]]:
    urls: dict[str, list[str]] = {
        "collection": [],
        "facilities": [],
        "pickup": [],
        "street_cleaning": [],
        "other": [],
    }
    if local_operator_ref == "aamps":
        urls["collection"] = [
            "https://www.aamps.livorno.it/wp-content/uploads/2023/04/Dove_lo_butto_2023.pdf"
        ]
        urls["facilities"] = [
            "https://www.aamps.livorno.it/wp-content/uploads/2024/07/CALENDARIO-PENTAGONO-DEF-UD.pdf"
        ]
    elif local_operator_ref == "esa":
        urls["collection"] = ["https://www.esaspa.it/cittadini/raccolta-differenziata/"]
        urls["facilities"] = ["https://www.esaspa.it/centri-di-raccolta/"]
    elif local_operator_ref == "rea":
        urls["collection"] = [_ato_costa_homepage(local_operator_ref, slug)]
        urls["facilities"] = ["https://www.reaspa.it/centri-di-raccolta/"]
        urls["other"] = ["https://www.reaspa.it/ritiro-e-rifornimenti-kit/"]
    elif local_operator_ref == "geofor":
        urls["collection"] = [
            _ato_costa_homepage(local_operator_ref, slug),
            "https://www.geofor.it/dove-lo-butto/",
        ]
        urls["facilities"] = ["https://www.geofor.it/centro-di-raccolta/"]
        urls["pickup"] = ["https://www.geofor.it/prenotazione-servizi-e-segnalazioni/"]
    return urls
