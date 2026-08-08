from __future__ import annotations

from collections import Counter
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import string
import subprocess
import time
from typing import Any
from urllib import robotparser
from urllib.parse import urlencode, urljoin, urlparse
from urllib.request import Request, urlopen

from .html import clean_text, parse_html
from .records import SourceDocument, make_record


OPERATOR_CONFIGS: dict[str, dict[str, Any]] = {
    "aamps": {
        "publisher": "AAMPS S.p.A.",
        "root": "https://www.aamps.livorno.it",
        "pages": {
            "waste_guide": "https://www.aamps.livorno.it/wp-content/uploads/2023/04/Dove_lo_butto_2023.pdf",
            "facilities_guide": "https://www.aamps.livorno.it/wp-content/uploads/2024/07/CALENDARIO-PENTAGONO-DEF-UD.pdf",
        },
    },
    "ascit": {
        "publisher": "ASCIT Servizi Ambientali S.p.A.",
        "root": "https://www.ascit.it",
        "pages": {
            "waste_lookup": "https://www.ascit.it/",
            "centres": "https://www.ascit.it/centri-di-raccolta/utenza-domestica/",
            "centre_index": "https://www.ascit.it/servizi/elenco-centri-di-raccolta/",
            "pickup": "https://www.ascit.it/servizi/rifiuti-ingombranti-2/",
        },
    },
    "lunigiana-ambiente": {
        "publisher": "Lunigiana Ambiente S.r.l.",
        "root": "https://www.lunigianaambiente.it",
        "pages": {
            "home": "https://www.lunigianaambiente.it/",
            "manual": "https://www.lunigianaambiente.it/manuale-della-raccolta-differenziata/",
            "centre_pontremoli": "https://www.lunigianaambiente.it/centro-di-raccolta-novoleto-pontremoli/",
            "centre_mulazzo": "https://www.lunigianaambiente.it/centro-di-raccolta-in-loc-boceda-mulazzo/",
            "pickup": "https://www.lunigianaambiente.it/prenota-un-servizio/",
        },
        "municipality_path": "/comuni/{slug}/",
        "dynamic_waste": "lunigiana",
    },
    "gea": {
        "publisher": "Garfagnana Ecologia Ambiente S.r.l.",
        "root": "https://geasrl.org",
        "pages": {
            "home": "https://geasrl.org/",
            "company": "https://geasrl.org/societa/",
            "pickup": "https://geasrl.org/la-societa/ingrombranti/",
            "centre": "https://geasrl.org/la-societa/ecocentro/",
            "centres": "https://geasrl.org/centri-di-raccolta/",
            "centre_hours": "https://geasrl.org/2026/06/04/orario-conferimento-ecocentro/",
            "collection_guide": "https://geasrl.org/wp-content/uploads/2026/04/web-brochure-porta-a-porta.pdf",
        },
    },
    "ersu": {
        "publisher": "ERSU S.p.A.",
        "root": "https://ersu.it",
        "pages": {
            "home": "https://ersu.it/",
            "centre_hours": "https://ersu.it/orari-centri-di-raccolta-2024/",
            "centre_update": "https://ersu.it/festivita-2-giugno-2026-orario-apertura-centri-di-raccolta/",
            "collection_guide": "https://ersu.it/wp-content/uploads/2021/02/Libello-ERSU-Camaiore.pdf",
            "montignoso_guide": "https://ersu.it/wp-content/uploads/2021/02/Libello-ERSU-Montignoso.pdf",
            "quality_charter": "https://ersu.it/wp-content/uploads/2023/01/Carta_Unica_Qualita_CAMAIORE.pdf",
        },
        "municipality_path": "/territori/{slug}/",
        "discover_facility_links": True,
    },
    "asmiu": {
        "publisher": "ASMIU S.r.l.",
        "root": "https://www.asmiu.it",
        "pages": {
            "waste_lookup": "https://www.asmiu.it/rifiutario/",
            "collection": "https://www.asmiu.it/come-differenziare-i-rifiuti/",
            "centre": "https://www.asmiu.it/centro-di-raccolta-via-dorsale/",
            "pickup": "https://www.asmiu.it/ritiro-ingombranti/",
        },
    },
    "sea-ambiente": {
        "publisher": "SEA Ambiente S.p.A.",
        "root": "https://www.seaambiente-spa.it",
        "pages": {
            "collection": "https://www.seaambiente-spa.it/it/raccolta-porta-a-porta/come-si-fa-la-raccolta",
            "centres": "https://www.seaambiente-spa.it/it/centri-di-raccolta",
        },
    },
    "retiambiente-carrara": {
        "publisher": "RetiAmbiente Carrara S.r.l.",
        "root": "https://www.retiambientecarrara.it",
        "pages": {
            "collection": "https://www.retiambientecarrara.it/raccolta-porta-a-porta/",
            "street_collection": "https://www.retiambientecarrara.it/isole-ecologiche-centro-citta/",
            "pickup": "https://www.retiambientecarrara.it/igiene-urbana/",
        },
    },
    "sistema-ambiente": {
        "publisher": "Sistema Ambiente S.p.A.",
        "root": "https://www.sistemaambientelucca.it",
        "pages": {
            "centres": "https://www.sistemaambientelucca.it/it/centri-raccolta/",
            "historic_centre": "https://www.sistemaambientelucca.it/it/la-raccolta/la-raccolta-differenziata-nel-centro-storico/",
            "services": "https://www.sistemaambientelucca.it/it/la-raccolta/servizi/",
        },
    },
    "esa": {
        "publisher": "ESA S.p.A.",
        "root": "https://www.esaspa.it",
        "pages": {
            "collection": "https://www.esaspa.it/cittadini/raccolta-differenziata/",
            "centre_index": "https://www.esaspa.it/centri-di-raccolta/",
        },
        "discover_facility_path_prefix": "/centri-di-raccolta/centro-",
        "discover_facility_exclude_paths": {"/centri-di-raccolta/centro-di-raccolta"},
        "discover_centre_signs": True,
    },
}


def _slug(value: str) -> str:
    value = value.casefold().translate(str.maketrans("àèéìòù", "aeeiou"))
    return re.sub(r"[^a-z0-9]+", "-", value).strip("-") or "unknown"


def _snapshot(body: bytes, content_type: str, final_url: str, root: Path) -> tuple[str, str]:
    digest = hashlib.sha256(body).hexdigest()
    extension = (
        ".json" if content_type == "application/json"
        else ".pdf" if content_type == "application/pdf" or final_url.lower().endswith(".pdf")
        else ".jpeg" if content_type in {"image/jpeg", "image/jpg"} or final_url.lower().endswith((".jpeg", ".jpg"))
        else ".png" if content_type == "image/png" or final_url.lower().endswith(".png")
        else ".html"
    )
    path = root / f"{digest}{extension}"
    root.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_bytes(body)
    return path.name, digest


def _request(url: str, user_agent: str, data: bytes | None = None) -> tuple[bytes, str, str]:
    headers = {"User-Agent": user_agent, "Accept": "text/html,application/json,application/pdf,image/jpeg,image/png"}
    if data is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    try:
        with urlopen(Request(url, data=data, headers=headers), timeout=60) as response:
            return response.read(), response.headers.get_content_type(), response.geturl()
    except Exception as error:
        if data is not None or "CERTIFICATE_VERIFY_FAILED" not in str(error):
            raise
        result = subprocess.run(
            ["curl", "-fsSL", "--max-time", "60", "-A", user_agent, url],
            check=True, capture_output=True,
        )
        content_type = (
            "application/pdf" if url.lower().endswith(".pdf")
            else "image/jpeg" if url.lower().endswith((".jpeg", ".jpg"))
            else "image/png" if url.lower().endswith(".png")
            else "text/plain" if url.lower().endswith("robots.txt")
            else "text/html"
        )
        return result.stdout, content_type, url


def crawl_local_operator(
    operator_ref: str,
    municipalities: list[dict[str, Any]],
    snapshot_root: Path,
    observed_at: datetime,
    user_agent: str,
    delay: float = 1.0,
) -> dict[str, Any]:
    config = OPERATOR_CONFIGS[operator_ref]
    robots_url = f"{config['root']}/robots.txt"
    try:
        body, _, _ = _request(robots_url, user_agent)
        robots_lines = body.decode("utf-8", errors="replace").splitlines()
        robots_status = "available"
    except Exception as error:
        robots_lines = []
        robots_status = f"error: {type(error).__name__}: {error}"
    robots = robotparser.RobotFileParser(robots_url)
    robots.parse(robots_lines)
    effective_delay = max(delay, robots.crawl_delay(user_agent) or robots.crawl_delay("*") or 1.0)
    jobs = [{"category": category, "url": url, "municipality_istats": []} for category, url in config["pages"].items()]
    if config.get("municipality_path"):
        for municipality in municipalities:
            source_slug = {
                "casola-in-lunigiana": "casola-di-lunigiana",
            }.get(municipality["source_slug"], municipality["source_slug"])
            jobs.append({
                "category": "municipality",
                "url": f"{config['root']}{config['municipality_path'].format(slug=source_slug)}",
                "municipality_istats": [municipality["istat_code"]],
            })
    pages = []
    for job in jobs:
        if robots_status != "available":
            pages.append({**job, "status": "error", "final_url": None, "content_type": None, "snapshot": None, "sha256": None, "error": f"robots.txt unavailable: {robots_status}"})
            continue
        if robots_status == "available" and not robots.can_fetch(user_agent, job["url"]):
            pages.append({**job, "status": "blocked_by_robots", "final_url": None, "content_type": None, "snapshot": None, "sha256": None})
            continue
        try:
            body, content_type, final_url = _request(job["url"], user_agent)
            snapshot, digest = _snapshot(body, content_type, final_url, snapshot_root)
            pages.append({**job, "status": "snapshot", "final_url": final_url, "content_type": content_type, "snapshot": snapshot, "sha256": digest})
        except Exception as error:
            pages.append({**job, "status": "error", "final_url": None, "content_type": None, "snapshot": None, "sha256": None, "error": f"{type(error).__name__}: {error}"})
        time.sleep(effective_delay)
    if config.get("discover_facility_links") or config.get("discover_facility_path_prefix"):
        discovered: dict[str, set[str]] = {}
        for page in pages:
            valid_source = (
                page["category"] == "municipality"
                or page["category"] == "centre_index" and config.get("discover_facility_path_prefix")
            )
            if not valid_source or page["status"] != "snapshot" or not page.get("snapshot"):
                continue
            html = (snapshot_root / page["snapshot"]).read_text(encoding="utf-8", errors="replace")
            root = parse_html(html)
            for anchor in root.find_all(lambda node: node.tag == "a" and bool(node.attrs.get("href"))):
                label = clean_text(anchor.text).casefold()
                path_prefix = config.get("discover_facility_path_prefix")
                href_path = urlparse(urljoin(page.get("final_url") or page["url"], anchor.attrs["href"])).path
                if href_path.rstrip("/") in config.get("discover_facility_exclude_paths", set()):
                    continue
                matches_label = config.get("discover_facility_links") and any(
                    marker in label for marker in ("centro di raccolta", "isola ecologica", "impianto verde")
                )
                matches_path = path_prefix and href_path.startswith(path_prefix)
                if not (matches_label or matches_path):
                    continue
                url = urljoin(page.get("final_url") or page["url"], anchor.attrs["href"])
                if urlparse(url).netloc != urlparse(config["root"]).netloc:
                    continue
                discovered.setdefault(url, set()).update(page.get("municipality_istats", []))
        for url, municipality_istats in sorted(discovered.items()):
            job = {"category": "centre_detail", "url": url, "municipality_istats": sorted(municipality_istats)}
            if robots_status == "available" and not robots.can_fetch(user_agent, url):
                pages.append({**job, "status": "blocked_by_robots", "final_url": None, "content_type": None, "snapshot": None, "sha256": None})
                continue
            try:
                body, content_type, final_url = _request(url, user_agent)
                snapshot, digest = _snapshot(body, content_type, final_url, snapshot_root)
                pages.append({**job, "status": "snapshot", "final_url": final_url, "content_type": content_type, "snapshot": snapshot, "sha256": digest})
            except Exception as error:
                pages.append({**job, "status": "error", "final_url": None, "content_type": None, "snapshot": None, "sha256": None, "error": f"{type(error).__name__}: {error}"})
            time.sleep(effective_delay)
    if config.get("discover_centre_signs"):
        discovered_signs = set()
        for page in pages:
            if page["category"] != "centre_detail" or page["status"] != "snapshot" or not page.get("snapshot"):
                continue
            html = (snapshot_root / page["snapshot"]).read_text(encoding="utf-8", errors="replace")
            root = parse_html(html)
            for anchor in root.find_all(lambda node: node.tag == "a" and bool(node.attrs.get("href"))):
                url = urljoin(page.get("final_url") or page["url"], anchor.attrs["href"])
                if urlparse(url).netloc == urlparse(config["root"]).netloc and url.lower().endswith((".jpeg", ".jpg", ".png")):
                    discovered_signs.add(url)
        for url in sorted(discovered_signs):
            job = {"category": "centre_sign", "url": url, "municipality_istats": []}
            if not robots.can_fetch(user_agent, url):
                pages.append({**job, "status": "blocked_by_robots", "final_url": None, "content_type": None, "snapshot": None, "sha256": None})
                continue
            try:
                body, content_type, final_url = _request(url, user_agent)
                snapshot, digest = _snapshot(body, content_type, final_url, snapshot_root)
                pages.append({**job, "status": "snapshot", "final_url": final_url, "content_type": content_type, "snapshot": snapshot, "sha256": digest})
            except Exception as error:
                pages.append({**job, "status": "error", "final_url": None, "content_type": None, "snapshot": None, "sha256": None, "error": f"{type(error).__name__}: {error}"})
            time.sleep(effective_delay)
    if config.get("dynamic_waste") == "lunigiana":
        endpoint = f"{config['root']}/wp-admin/admin-ajax.php"
        if robots_status != "available":
            pages.append({"category": "waste_lookup_json", "url": endpoint, "municipality_istats": [], "status": "error", "final_url": None, "content_type": None, "snapshot": None, "sha256": None, "error": f"robots.txt unavailable: {robots_status}"})
        elif not robots.can_fetch(user_agent, endpoint):
            pages.append({"category": "waste_lookup_json", "url": endpoint, "municipality_istats": [], "status": "blocked_by_robots", "final_url": None, "content_type": None, "snapshot": None, "sha256": None})
        else:
            items: dict[str, list[str]] = {}
            errors = []
            for letter in string.ascii_lowercase:
                try:
                    payload = urlencode({"action": "cpws_ajax", "format": "U", "cmd": "find", "cerca": letter}).encode()
                    body, _, _ = _request(endpoint, user_agent, payload)
                    response = json.loads(body.decode("utf-8"))
                    for item in response.get("result", []):
                        if len(item) >= 3:
                            items[clean_text(str(item[0])).casefold()] = [clean_text(str(value)) for value in item[:3]]
                except Exception as error:
                    errors.append(f"{letter}: {type(error).__name__}: {error}")
                time.sleep(effective_delay)
            body = json.dumps({"items": sorted(items.values()), "errors": errors}, ensure_ascii=False, sort_keys=True).encode("utf-8")
            snapshot, digest = _snapshot(body, "application/json", endpoint, snapshot_root)
            pages.append({"category": "waste_lookup_json", "url": endpoint, "municipality_istats": [], "status": "snapshot" if not errors else "partial_snapshot", "final_url": endpoint, "content_type": "application/json", "snapshot": snapshot, "sha256": digest, "query_errors": errors})
    return {
        "observed_at": observed_at.isoformat(),
        "operator_ref": operator_ref,
        "publisher": config["publisher"],
        "robots_url": robots_url,
        "robots_status": robots_status,
        "crawl_delay_seconds": effective_delay,
        "pages": pages,
        "summary": {
            "checked": len(pages),
            "snapshots": sum(page["status"] in {"snapshot", "partial_snapshot"} for page in pages),
            "blocked_by_robots": sum(page["status"] == "blocked_by_robots" for page in pages),
            "errors": sum(page["status"] == "error" for page in pages),
        },
    }


def _source(page: dict[str, Any], content: str, retrieved_at: datetime, publisher: str, parser: str) -> SourceDocument:
    return SourceDocument(page.get("final_url") or page["url"], retrieved_at, content, publisher=publisher, parser=parser, parser_version="0.1.0")


def _waste_records(operator_ref: str, municipality: dict[str, Any], pages: dict[str, tuple[dict[str, Any], str]], retrieved_at: datetime, publisher: str) -> list[dict[str, Any]]:
    items: list[tuple[str, str, str | None, SourceDocument, str]] = []
    if operator_ref == "ascit" and "waste_lookup" in pages:
        page, html = pages["waste_lookup"]
        source = _source(page, html, retrieved_at, publisher, "ascit_embedded_rifiutario")
        root = parse_html(html)
        for element in root.find_all(lambda node: node.tag == "li" and bool(node.attrs.get("data-name"))):
            term = clean_text(element.attrs["data-name"])
            destination = clean_text(element.attrs.get("data-destination", ""))
            if term and destination:
                items.append((term, destination, None, source, "li[data-name][data-destination]"))
    elif operator_ref == "lunigiana-ambiente" and "waste_lookup_json" in pages:
        page, content = pages["waste_lookup_json"]
        source = _source(page, content, retrieved_at, publisher, "lunigiana_ajax_rifiutario")
        for term, material, destination in json.loads(content).get("items", []):
            items.append((term, destination, f"Categoria pubblicata: {material}", source, f"result[{term!r}]"))
    elif operator_ref == "asmiu" and "waste_lookup" in pages:
        page, html = pages["waste_lookup"]
        source = _source(page, html, retrieved_at, publisher, "asmiu_rifiutario_index")
        root = parse_html(html)
        select = root.find_first(lambda node: node.tag == "select" and node.attrs.get("id") == "rid")
        if select:
            for option in select.find_all(lambda node: node.tag == "option" and bool(node.attrs.get("value"))):
                term = clean_text(option.text).lstrip("\ufeff")
                if term:
                    items.append((term, "Destinazione disponibile selezionando la voce nella fonte ASMIU", "Destinazione non inclusa nell'indice HTML: acquisizione dettagliata necessaria", source, f"option[value='{option.attrs['value']}']"))
    records = []
    for term, destination, instructions, source, selector in items:
        unresolved = operator_ref == "asmiu"
        records.append(make_record(
            record_type="waste_lookup",
            natural_key=f"waste-lookup:{municipality['istat_code']}:{_slug(term)}",
            payload={"municipality_ref": municipality["municipality_ref"], "term": term, "destination_raw": destination if not unresolved else None, "resolution_status": "source_detail_not_acquired" if unresolved else "resolved", "instructions_raw": instructions},
            source=source,
            evidence_kind="json" if operator_ref == "lunigiana-ambiente" else "html",
            evidence_selector=selector,
            evidence_quote=f"{term}: {destination}",
            confidence="medium" if unresolved else "high",
        ))
    return records


_STREAM_MARKERS = (
    ("organico", "Rifiuti organici"),
    ("carta", "Carta e cartone"),
    ("multimateriale", "Imballaggi in multimateriale"),
    ("plastica", "Imballaggi in plastica"),
    ("vetro", "Vetro"),
    ("indifferenziato", "Rifiuto urbano residuo"),
    ("rifiuto urbano residuo", "Rifiuto urbano residuo"),
)


def _rule_records(municipality: dict[str, Any], pages: dict[str, tuple[dict[str, Any], str]], retrieved_at: datetime, publisher: str) -> list[dict[str, Any]]:
    source_pages = [(page, content) for page, content in pages.values() if (page.get("content_type") or "").startswith("text/html") or page.get("content_type") == "application/pdf"]
    if not source_pages:
        return []
    combined = "\n".join(clean_text(parse_html(content).text) if (page.get("content_type") or "").startswith("text/html") else clean_text(content) for page, content in source_pages)
    zone_ref = f"service-zone:{municipality['istat_code']}:default"
    source_page, source_content = max(source_pages, key=lambda item: len(item[1]))
    source = _source(source_page, source_content, retrieved_at, publisher, "local_operator_html")
    evidence_kind = "pdf" if source_page.get("content_type") == "application/pdf" else "html"
    records = [make_record(record_type="service_zone", natural_key=zone_ref, payload={"municipality_ref": municipality["municipality_ref"], "name": "Intero territorio comunale", "scope_type": "municipality_default", "included_places_raw": None, "excluded_places_raw": None, "geometry_geojson": None}, source=source, evidence_kind=evidence_kind, evidence_selector="document" if evidence_kind == "pdf" else "main", evidence_quote=combined[:500])]
    found = set()
    folded = combined.casefold()
    for marker, stream in _STREAM_MARKERS:
        if marker not in folded or stream in found:
            continue
        found.add(stream)
        records.append(make_record(
            record_type="collection_rule",
            natural_key=f"collection-rule:{municipality['istat_code']}:default:{_slug(stream)}",
            payload={"municipality_ref": municipality["municipality_ref"], "zone_ref": zone_ref, "user_type": "all", "collection_method": "other", "stream_name": stream, "included_materials_raw": None, "container_type": None, "container_color": None, "access_credential": None, "presentation": {"mode": "source_specific", "max_volume_l": None, "instructions_raw": "Consultare le istruzioni del gestore collegate alla fonte"}, "schedule_raw": None},
            source=source,
            evidence_kind=evidence_kind,
            evidence_selector="document" if evidence_kind == "pdf" else "main",
            evidence_quote=marker,
            confidence="medium",
        ))
    return records


def _facility_records(operator_ref: str, municipality: dict[str, Any], pages: dict[str, tuple[dict[str, Any], str]], retrieved_at: datetime, publisher: str) -> list[dict[str, Any]]:
    if operator_ref == "ersu":
        ersu = _ersu_facility_records(municipality, pages, retrieved_at, publisher)
        if ersu:
            return ersu
    static = _static_facility_records(operator_ref, municipality, pages, retrieved_at, publisher)
    if operator_ref in _STATIC_FACILITIES:
        return static
    candidates = []
    for category, (page, content) in pages.items():
        if "centre" not in category or not (page.get("content_type") or "").startswith("text/html"):
            continue
        text = clean_text(parse_html(content).text)
        candidates.append((page, content, text))
    if not candidates:
        return []
    records = []
    for index, (page, content, text) in enumerate(candidates, 1):
        names = re.findall(r"(?:Centro di Raccolta|Ricicleria)[^\n.!]{0,100}", text, flags=re.IGNORECASE)
        name = clean_text(names[0]) if names else f"Centro di raccolta ({publisher})"
        if len(name) > 140:
            name = name[:140].rsplit(" ", 1)[0]
        facility_ref = f"{operator_ref}:facility:{_slug(name)}:{index}"
        source = _source(page, content, retrieved_at, publisher, "local_operator_facility_html")
        records.append(make_record(record_type="facility", natural_key=facility_ref, payload={"name": name, "municipality_ref": municipality["municipality_ref"], "facility_type": "collection_centre", "address_raw": None, "location": None, "phone": None, "email": None, "operational_status": "unknown", "status_raw": None}, source=source, evidence_selector="main", evidence_quote=text[:1000], confidence="medium"))
        records.append(make_record(record_type="facility_access", natural_key=f"{facility_ref}:access:{municipality['istat_code']}", payload={"facility_ref": facility_ref, "municipality_ref": municipality["municipality_ref"], "user_type": "domestic", "allowed": True, "requirements_raw": text[:2500], "booking_required": False, "information_urls": [page.get("final_url") or page["url"]], "contact_phone": None, "contact_email": None}, source=source, evidence_selector="main", evidence_quote=text[:1000], confidence="medium"))
    return records


_ERSU_HOST_REFS = {
    "camaiore": "istat:046005",
    "forte dei marmi": "istat:046013",
    "massarosa": "istat:046018",
    "pietrasanta": "istat:046024",
    "seravezza": "istat:046028",
    "stazzema": "istat:046030",
}


def _ersu_facility_records(municipality: dict[str, Any], pages: dict[str, tuple[dict[str, Any], str]], retrieved_at: datetime, publisher: str) -> list[dict[str, Any]]:
    records = []
    for category, (page, content) in pages.items():
        if not category.startswith("centre_detail") or not (page.get("content_type") or "").startswith("text/html"):
            continue
        root = parse_html(content)
        heading = root.find_first(lambda node: node.tag == "h1")
        text = clean_text(root.text)
        name = clean_text(heading.text) if heading else clean_text(text.split("| ERSU", 1)[0])
        if not name:
            continue
        facility_ref = f"ersu:facility:{_slug(name)}"
        folded = text.casefold()
        host_ref = municipality["municipality_ref"]
        for host_name, candidate_ref in _ERSU_HOST_REFS.items():
            if f"situato nel comune di {host_name}" in folded or host_name in name.casefold():
                host_ref = candidate_ref
                break
        address_match = re.search(r"INFO IMPIANTO\s+(.{3,180}?\(LU\))", text, flags=re.IGNORECASE)
        address = clean_text(address_match.group(1)) if address_match else None
        source = _source(page, content, retrieved_at, publisher, "ersu_facility_html")
        facility_type = "collection_centre" if "centro di raccolta" in name.casefold() else "ecological_island" if "isola ecologica" in name.casefold() else "collection_point"
        records.append(make_record(record_type="facility", natural_key=facility_ref, payload={"name": name, "municipality_ref": host_ref, "facility_type": facility_type, "address_raw": address, "location": None, "phone": "800942540", "email": None, "operational_status": "active", "status_raw": None}, source=source, evidence_selector="h1", evidence_quote=f"{name}: {address or 'indirizzo non pubblicato'}"))
        requirements = "Utenze domestiche residenti con tessera sanitaria; per le seconde case può accedere l'intestatario TARI con tessera sanitaria."
        records.append(make_record(record_type="facility_access", natural_key=f"{facility_ref}:access:{municipality['istat_code']}:domestic", payload={"facility_ref": facility_ref, "municipality_ref": municipality["municipality_ref"], "user_type": "domestic", "allowed": True, "requirements_raw": requirements, "booking_required": False, "information_urls": [page.get("final_url") or page["url"]], "contact_phone": "800942540", "contact_email": None}, source=source, evidence_selector="main", evidence_quote="Sono spazi dedicati esclusivamente alle Utenze Domestiche"))
        acceptance_text = text.split("COSA CONFERIRE:", 1)[1].split("Legenda:", 1)[0] if "COSA CONFERIRE:" in text else ""
        for match in re.finditer(r"(.+?)\s+CER\s+(\d{6})\s*(\*)?", acceptance_text, flags=re.IGNORECASE):
            description = clean_text(match.group(1)).strip(" -;:")
            code = match.group(2)
            hazardous = bool(match.group(3))
            raw_code = code + ("*" if hazardous else "")
            records.append(make_record(record_type="facility_acceptance", natural_key=f"{facility_ref}:eer:{code}:{_slug(description)}", payload={"facility_ref": facility_ref, "eer_code_raw": raw_code, "eer_code_normalized": code, "eer_code_status": "exact", "reconciliation_basis": None, "hazardous": hazardous, "description_raw": description, "operational_group": None, "user_type": "domestic", "quantity_limit_raw": None, "notes_raw": None}, source=source, evidence_selector="main", evidence_quote=f"{description} CER {raw_code}"))
        winter = re.search(r"Orario invernale:(.+?)(?:Orario estivo:|ERSU Spa)", text, flags=re.IGNORECASE)
        summer = re.search(r"Orario estivo:(.+?)(?:ERSU Spa)", text, flags=re.IGNORECASE)
        for label, match in (("Orario invernale", winter), ("Orario estivo", summer)):
            if not match:
                continue
            records.append(make_record(record_type="opening_period", natural_key=f"{facility_ref}:opening:{_slug(label)}", payload={"facility_ref": facility_ref, "period_label": label, "start_month_day": "10-01" if label.endswith("invernale") else "06-01", "end_month_day": "05-31" if label.endswith("invernale") else "09-30", "weekly_intervals": [], "exceptions_raw": clean_text(match.group(1))}, source=source, evidence_selector="main", evidence_quote=clean_text(match.group(0))))
    return records


_STATIC_FACILITIES: dict[str, list[dict[str, Any]]] = {
    "ascit": [
        {"name": "Il Cerro", "address": None, "municipality_ref": "istat:046001", "category": "centre_index", "phone": "800942951", "allowed_istats": ["046001"]},
        {"name": "Le Ravacce", "address": None, "municipality_ref": "istat:046002", "category": "centre_index", "phone": "800942951", "allowed_istats": ["046002"]},
        {"name": "Chitarrino", "address": None, "municipality_ref": "istat:046003", "category": "centre_index", "phone": "800942951", "allowed_istats": ["046003"]},
        {"name": "Socciglia", "address": None, "municipality_ref": "istat:046004", "category": "centre_index", "phone": "800942951", "allowed_istats": ["046004"]},
        {"name": "Colle di Compito", "address": None, "municipality_ref": "istat:046007", "category": "centre_index", "phone": "800942951", "allowed_istats": ["046007"]},
        {"name": "Coselli", "address": None, "municipality_ref": "istat:046007", "category": "centre_index", "phone": "800942951", "allowed_istats": ["046007"]},
        {"name": "Lammari", "address": None, "municipality_ref": "istat:046007", "category": "centre_index", "phone": "800942951", "allowed_istats": ["046007"]},
        {"name": "Ghivizzano", "address": None, "municipality_ref": "istat:046011", "category": "centre_index", "phone": "800942951", "allowed_istats": ["046011"]},
        {"name": "Piegaio", "address": None, "municipality_ref": "istat:046022", "category": "centre_index", "phone": "800942951", "allowed_istats": ["046022"]},
        {"name": "Salanetti 1 (Centro di Stoccaggio)", "address": None, "municipality_ref": "istat:046007", "category": "centre_index", "phone": "800942951"},
        {"name": "Salanetti 2", "address": None, "municipality_ref": "istat:046007", "category": "centre_index", "phone": "800942951"},
    ],
    "lunigiana-ambiente": [
        {"name": "Centro di raccolta Boceda", "address": "Zona Industriale Boceda, Mulazzo", "municipality_ref": "istat:045012", "category": "centre_mulazzo", "phone": None, "weekly_intervals": [{"weekday": 1, "opens": "08:00", "closes": "14:00"}, {"weekday": 2, "opens": "13:00", "closes": "19:00"}, {"weekday": 3, "opens": "08:00", "closes": "14:00"}, {"weekday": 4, "opens": "13:00", "closes": "19:00"}, {"weekday": 5, "opens": "08:00", "closes": "14:00"}, {"weekday": 6, "opens": "13:00", "closes": "19:00"}], "exceptions": None},
        {"name": "Centro di raccolta Novoleto", "address": "Localita Novoleto, Pontremoli", "municipality_ref": "istat:045014", "category": "centre_pontremoli", "phone": None, "allowed_istats": ["045014"], "weekly_intervals": [{"weekday": 1, "opens": "08:00", "closes": "14:00"}, {"weekday": 2, "opens": "13:00", "closes": "19:00"}, {"weekday": 3, "opens": "08:00", "closes": "14:00"}, {"weekday": 4, "opens": "13:00", "closes": "19:00"}, {"weekday": 5, "opens": "08:00", "closes": "14:00"}, {"weekday": 6, "opens": "13:00", "closes": "19:00"}], "exceptions": None},
    ],
    "gea": [{"name": "Ecocentro GEA", "address": "Via Pio La Torre 2/C, Castelnuovo di Garfagnana", "municipality_ref": "istat:046009", "category": "centre", "hours_category": "centre_hours", "phone": "05836581", "weekly_intervals": [{"weekday": 1, "opens": "08:00", "closes": "12:30"}, {"weekday": 2, "opens": "08:00", "closes": "13:00"}, {"weekday": 2, "opens": "14:00", "closes": "17:30"}, {"weekday": 3, "opens": "08:00", "closes": "12:30"}, {"weekday": 4, "opens": "08:00", "closes": "12:30"}, {"weekday": 5, "opens": "08:00", "closes": "12:30"}, {"weekday": 6, "opens": "08:00", "closes": "13:00"}, {"weekday": 6, "opens": "14:00", "closes": "17:30"}], "exceptions": "Chiuso nei giorni festivi."}],
    "asmiu": [{"name": "Centro di raccolta Ricicleria", "address": "Via Dorsale 24, Massa", "municipality_ref": "istat:045010", "category": "centre", "phone": "0585606891", "allowed_istats": ["045010"], "weekly_intervals": [{"weekday": day, "opens": "07:30", "closes": "13:00"} for day in range(1, 7)] + [{"weekday": 6, "opens": "14:00", "closes": "17:00"}], "exceptions": "Chiuso nei giorni festivi."}],
    "sea-ambiente": [
        {"name": "Centro di raccolta Vietta dei Comparini", "address": "Vietta dei Comparini 186, Viareggio", "municipality_ref": "istat:046033", "category": "centres", "phone": "800434509", "allowed_istats": ["046033"], "weekly_intervals": [{"weekday": day, "opens": "08:00", "closes": "12:15"} for day in range(1, 7)] + [{"weekday": day, "opens": "14:30", "closes": "17:45"} for day in range(1, 6)], "exceptions": "Chiuso la domenica e nei giorni festivi."},
        {"name": "Centro di raccolta Poggio alle Viti", "address": "Via della Migliarina 33, Viareggio", "municipality_ref": "istat:046033", "category": "centres", "phone": "800434509", "allowed_istats": ["046033"], "weekly_intervals": [{"weekday": day, "opens": "08:00", "closes": "12:15"} for day in range(1, 7)] + [{"weekday": day, "opens": "14:30", "closes": "17:45"} for day in range(1, 6)], "exceptions": "Chiuso la domenica e nei giorni festivi."},
    ],
    "retiambiente-carrara": [{"name": "Ricicleria RetiAmbiente Carrara", "address": "Via Camillo Berneri 9, Avenza", "municipality_ref": "istat:045003", "category": "collection", "phone": "800015821", "allowed_istats": ["045003"], "weekly_intervals": [{"weekday": day, "opens": "07:00", "closes": "19:00"} for day in range(1, 7)], "exceptions": None}],
}


def _static_facility_records(operator_ref: str, municipality: dict[str, Any], pages: dict[str, tuple[dict[str, Any], str]], retrieved_at: datetime, publisher: str) -> list[dict[str, Any]]:
    definitions = _STATIC_FACILITIES.get(operator_ref, [])
    records = []
    for definition in definitions:
        if definition.get("allowed_istats") and municipality["istat_code"] not in definition["allowed_istats"]:
            continue
        if definition["category"] not in pages:
            continue
        page, content = pages[definition["category"]]
        source = _source(page, content, retrieved_at, publisher, "local_operator_facility_source")
        facility_ref = f"{operator_ref}:facility:{_slug(definition['name'])}"
        records.append(make_record(record_type="facility", natural_key=facility_ref, payload={"name": definition["name"], "municipality_ref": definition["municipality_ref"], "facility_type": "collection_centre", "address_raw": definition["address"], "location": None, "phone": definition["phone"], "email": None, "operational_status": "active", "status_raw": None}, source=source, evidence_selector="main", evidence_quote=definition["name"], confidence="high"))
        records.append(make_record(record_type="facility_access", natural_key=f"{facility_ref}:access:{municipality['istat_code']}:domestic", payload={"facility_ref": facility_ref, "municipality_ref": municipality["municipality_ref"], "user_type": "domestic", "allowed": True, "requirements_raw": clean_text(parse_html(content).text)[:2500], "booking_required": False, "information_urls": [page.get("final_url") or page["url"]], "contact_phone": definition["phone"], "contact_email": None}, source=source, evidence_selector="main", evidence_quote=definition["address"] or definition["name"], confidence="medium"))
        if definition.get("weekly_intervals"):
            hours_page, hours_content = pages.get(definition.get("hours_category"), (page, content))
            hours_source = _source(hours_page, hours_content, retrieved_at, publisher, "local_operator_opening_hours")
            records.append(make_record(record_type="opening_period", natural_key=f"{facility_ref}:opening:published", payload={"facility_ref": facility_ref, "period_label": "Orario pubblicato", "start_month_day": None, "end_month_day": None, "weekly_intervals": definition["weekly_intervals"], "exceptions_raw": definition.get("exceptions")}, source=hours_source, evidence_selector="main", evidence_quote=clean_text(parse_html(hours_content).text)[:1000]))
    return records


def _ersu_camaiore_records(municipality: dict[str, Any], pages: dict[str, tuple[dict[str, Any], str]], retrieved_at: datetime, publisher: str) -> list[dict[str, Any]]:
    if municipality["istat_code"] != "046005" or "collection_guide" not in pages:
        return []
    page, text = pages["collection_guide"]
    source = _source(page, text, retrieved_at, publisher, "ersu_camaiore_pdf")
    zone_ref = f"service-zone:{municipality['istat_code']}:default"
    records = [make_record(record_type="service_zone", natural_key=zone_ref, payload={"municipality_ref": municipality["municipality_ref"], "name": "Comune di Camaiore", "scope_type": "municipality_default", "included_places_raw": "Lido di Camaiore; Terre di Camaiore; centro storico e colline", "excluded_places_raw": None, "geometry_geojson": None}, source=source, evidence_kind="pdf", evidence_selector="page:7", evidence_quote="Il territorio del Comune di Camaiore è stato suddiviso in tre zone")]
    rules = [
        ("Rifiuti organici", "mastello", "marrone", "Sacchetto compostabile da 10 litri nel mastello marrone da 20 litri; non usare sacchetti di plastica.", "page:8"),
        ("Vetro", "mastello", "verde", "Imballaggi in vetro sfusi nel mastello verde da 40 litri, completamente vuoti e senza sacchetti.", "page:10"),
        ("Carta e cartone", "sacco", None, "Sacco di carta da 35 litri; il cartone va piegato e, per grandi quantità, appiattito e legato.", "page:12"),
        ("Imballaggi in multimateriale", "sacco", "giallo", "Sacco giallo da 90 litri, ben chiuso; schiacciare gli imballaggi per ridurne il volume.", "page:14"),
        ("Rifiuto urbano residuo", "mastello", "grigio", "Sacco ben chiuso nel mastello grigio da 40 litri.", "page:16"),
    ]
    for stream, container, color, instructions, selector in rules:
        records.append(make_record(record_type="collection_rule", natural_key=f"collection-rule:{municipality['istat_code']}:default:{_slug(stream)}", payload={"municipality_ref": municipality["municipality_ref"], "zone_ref": zone_ref, "user_type": "domestic", "collection_method": "door_to_door", "stream_name": stream, "included_materials_raw": None, "container_type": container, "container_color": color, "access_credential": "RFID tag", "presentation": {"mode": "bag_in_container" if container == "mastello" and stream != "Vetro" else "loose_in_container" if stream == "Vetro" else "bag", "max_volume_l": 40 if container == "mastello" else 90 if color == "giallo" else 35, "instructions_raw": instructions}, "schedule_raw": "Consultare il calendario ERSU per la propria zona"}, source=source, evidence_kind="pdf", evidence_selector=selector, evidence_quote=instructions))
    records.append(make_record(record_type="pickup_service", natural_key="ersu:pickup:046005:ingombranti", payload={"municipality_ref": municipality["municipality_ref"], "zone_ref": None, "user_type": "domestic", "accepted_waste_raw": "Rifiuti ingombranti domestici", "booking_methods": [{"method": "web", "value": "https://ersu.it/", "hours_raw": None}, {"method": "app", "value": "portAPPorta", "hours_raw": None}, {"method": "phone", "value": "800942540", "hours_raw": None}], "max_items": 5, "quantity_limit_raw": "Fino a 5 pezzi", "placement_instructions_raw": None, "booking_required": True}, source=source, evidence_kind="pdf", evidence_selector="page:20", evidence_quote="Il servizio di ritiro a domicilio è gratuito fino a 5 pezzi."))
    return records


def _pickup_records(municipality: dict[str, Any], pages: dict[str, tuple[dict[str, Any], str]], retrieved_at: datetime, publisher: str, operator_ref: str) -> list[dict[str, Any]]:
    if "pickup" not in pages:
        return []
    page, content = pages["pickup"]
    if not (page.get("content_type") or "").startswith("text/html"):
        return []
    text = clean_text(parse_html(content).text)
    source = _source(page, content, retrieved_at, publisher, "local_operator_pickup_html")
    return [make_record(record_type="pickup_service", natural_key=f"{operator_ref}:pickup:{municipality['istat_code']}:ingombranti", payload={"municipality_ref": municipality["municipality_ref"], "zone_ref": None, "user_type": "domestic", "accepted_waste_raw": "Rifiuti ingombranti", "booking_methods": [{"method": "web", "value": page.get("final_url") or page["url"], "hours_raw": None}], "max_items": None, "quantity_limit_raw": None, "placement_instructions_raw": text[:4000], "booking_required": True}, source=source, evidence_selector="main", evidence_quote=text[:1000], confidence="medium")]


def materialize_local_operator(operator_ref: str, municipalities: list[dict[str, Any]], manifest: dict[str, Any], snapshot_root: Path, retrieved_at: datetime) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    publisher = OPERATOR_CONFIGS[operator_ref]["publisher"]
    if operator_ref == "aamps":
        from .ato_costa import MunicipalityContext, extract_aamps_2023_bundle

        pages = {
            page["category"]: (page, (snapshot_root / page["snapshot"]).read_bytes())
            for page in manifest["pages"]
            if page["status"] in {"snapshot", "partial_snapshot"} and page.get("snapshot")
        }
        results: dict[str, list[dict[str, Any]]] = {}
        reports: list[dict[str, Any]] = []
        for municipality in municipalities:
            records, warnings = extract_aamps_2023_bundle(
                MunicipalityContext(municipality["name"], municipality["istat_code"], municipality["source_slug"]),
                retrieved_at,
                pages["waste_guide"][0].get("final_url") or pages["waste_guide"][0]["url"],
                pages["waste_guide"][1],
                pages["facilities_guide"][0].get("final_url") or pages["facilities_guide"][0]["url"],
                pages["facilities_guide"][1],
            )
            counts = Counter(record["record_type"] for record in records)
            results[municipality["source_slug"]] = records
            reports.append({"municipality": municipality["name"], "istat_code": municipality["istat_code"], "slug": municipality["source_slug"], "observed_at": retrieved_at.isoformat(), "pages_available": len(pages), "pages_materialized": len(pages), "records": len(records), "records_by_type": dict(sorted(counts.items())), "warnings": warnings, "errors": [], "equivalent_pages": []})
        return results, reports
    loaded_pages: list[tuple[dict[str, Any], str]] = []
    for page in manifest["pages"]:
        if page["status"] not in {"snapshot", "partial_snapshot"} or not page.get("snapshot"):
            continue
        path = snapshot_root / page["snapshot"]
        if path.suffix in {".html", ".json"}:
            loaded_pages.append((page, path.read_text(encoding="utf-8", errors="replace")))
        elif path.suffix == ".pdf":
            extracted = subprocess.run(["pdftotext", "-layout", str(path), "-"], check=True, capture_output=True).stdout.decode("utf-8", errors="replace")
            loaded_pages.append((page, extracted))
    results = {}
    reports = []
    for municipality in municipalities:
        municipality = {**municipality, "municipality_ref": f"istat:{municipality['istat_code']}"}
        relevant_pages = [
            (page, content) for page, content in loaded_pages
            if not page.get("municipality_istats") or municipality["istat_code"] in page["municipality_istats"]
            if not (operator_ref == "ersu" and page.get("category") == "montignoso_guide")
        ]
        pages = {}
        for page, content in relevant_pages:
            key = page["category"]
            if key in pages:
                key = f"{key}:{sum(existing.startswith(page['category']) for existing in pages)}"
            pages[key] = (page, content)
        if operator_ref == "ersu" and municipality["istat_code"] == "046005":
            records = _ersu_camaiore_records(municipality, pages, retrieved_at, publisher)
            records.extend(_facility_records(operator_ref, municipality, pages, retrieved_at, publisher))
        else:
            records = _waste_records(operator_ref, municipality, pages, retrieved_at, publisher)
            records.extend(_rule_records(municipality, pages, retrieved_at, publisher))
            records.extend(_facility_records(operator_ref, municipality, pages, retrieved_at, publisher))
            records.extend(_pickup_records(municipality, pages, retrieved_at, publisher, operator_ref))
        counts = Counter(record["record_type"] for record in records)
        warnings = []
        warning_url = relevant_pages[0][0].get("final_url") or relevant_pages[0][0]["url"] if relevant_pages else None
        if not counts.get("waste_lookup"):
            warnings.append({"code": "waste_lookup_not_published_or_not_structured", "detail": "Rifiutario non pubblicato o non disponibile in forma strutturata nella fonte acquisita", "url": warning_url})
        if not counts.get("collection_rule"):
            warnings.append({"code": "collection_rules_not_published_or_not_structured", "detail": "Regole di raccolta non pubblicate o non disponibili in forma strutturata nella fonte acquisita", "url": warning_url})
        if not counts.get("facility"):
            warnings.append({"code": "facility_page_not_published_or_not_structured", "detail": "Centro di raccolta non pubblicato, non attribuito esplicitamente al comune o non disponibile in forma strutturata", "url": warning_url})
        blocked = [page["url"] for page in manifest["pages"] if page["status"] == "blocked_by_robots"]
        warnings.extend({"code": "blocked_by_robots", "detail": "URL non acquisita per le regole pubblicate in robots.txt", "url": url} for url in blocked)
        results[municipality["source_slug"]] = records
        reports.append({"municipality": municipality["name"], "istat_code": municipality["istat_code"], "slug": municipality["source_slug"], "observed_at": retrieved_at.isoformat(), "pages_available": len(relevant_pages), "pages_materialized": len(relevant_pages), "records": len(records), "records_by_type": dict(sorted(counts.items())), "warnings": warnings, "errors": [], "equivalent_pages": []})
    return results, reports
