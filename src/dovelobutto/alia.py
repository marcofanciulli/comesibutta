from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import re
import time
from typing import Any
import unicodedata
from urllib import robotparser
from urllib.parse import unquote, urlencode, urljoin
from urllib.request import Request, urlopen

from .ato_costa import MunicipalityContext
from .html import clean_text, parse_html
from .records import SourceDocument, make_record, write_jsonl


ALIA_ROOT = "https://aliaestra.it"
BFF_ROOT = "https://bff.aliaserviziambientali.it"
GRAPHQL_URL = (
    "https://edge-platform.sitecorecloud.io/v1/content/api/graphql/v1"
    "?sitecoreContextId=2xCyOdwl4RABcls6jZdyHr"
)
SITECORE_API_KEY = "5CE088D0-8F1A-4B97-A624-4FE74658E601"
CENTRE_PAGE = f"{ALIA_ROOT}/ambiente/raccolta-e-pulizia-strade/dove-lo-porto"
WASTE_PAGE = f"{ALIA_ROOT}/ambiente/raccolta-e-pulizia-strade/dove-lo-butto"
PICKUP_PAGE = f"{ALIA_ROOT}/ambiente/ritiri-ondemand"
KIT_PAGE = f"{ALIA_ROOT}/ambiente/raccolta-e-pulizia-strade/kit-raccolta"
ACCESS_PAGE = f"{ALIA_ROOT}/aiuto-e-guide/Waste/raccolta-differenziata/ecocentri-ecofurgoni/Ci-sono-delle-regole"

CENTRE_QUERY = """
query EcoSearchQuery($where: ItemSearchPredicateInput!, $after: String!) {
  doveLoPorto: search(where: $where first: 100 after: $after) {
    total
    pageInfo { endCursor hasNext }
    results {
      ... on DoveLoPorto {
        extId { value }
        displayName
        cosaPuoiConferire { values { name value } }
        tooltipCosaPuoiConferire { values { name value } }
        regoleAccesso { jsonValue }
        openingHours { jsonValue }
      }
    }
  }
}
"""


class _RateLimiter:
    def __init__(self, interval: float) -> None:
        self.interval = interval
        self.last_started_at: float | None = None

    def wait(self) -> None:
        now = time.monotonic()
        if self.last_started_at is not None:
            time.sleep(max(0.0, self.interval - (now - self.last_started_at)))
        self.last_started_at = time.monotonic()


def _slug(value: str) -> str:
    normalized = "".join(
        character
        for character in unicodedata.normalize("NFKD", value.casefold())
        if not unicodedata.combining(character)
    )
    return re.sub(r"[^a-z0-9]+", "-", normalized).strip("-") or "unknown"


def _read_json(request: Request, timeout: int = 45) -> Any:
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _get_json(url: str, user_agent: str) -> Any:
    return _read_json(Request(url, headers={"User-Agent": user_agent, "Accept": "application/json"}))


def _get_text(url: str, user_agent: str) -> str:
    request = Request(url, headers={"User-Agent": user_agent, "Accept": "text/html"})
    with urlopen(request, timeout=45) as response:
        return response.read().decode("utf-8", errors="replace")


def _post_json(url: str, payload: dict[str, Any], user_agent: str, headers: dict[str, str] | None = None) -> Any:
    request_headers = {
        "User-Agent": user_agent,
        "Accept": "application/json",
        "Content-Type": "application/json",
        **(headers or {}),
    }
    return _read_json(Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=request_headers,
        method="POST",
    ))


def build_junker_queries(catalog: dict[str, Any]) -> list[str]:
    queries = set()
    for concept in catalog.get("concepts", []):
        for term in concept.get("terms", []):
            normalized = "".join(
                character
                for character in unicodedata.normalize("NFKD", term.casefold())
                if not unicodedata.combining(character)
            )
            queries.update(word[:3] for word in re.findall(r"[a-z]{3,}", normalized))
    return sorted(queries)


def _save_checkpoint(path: Path, bundle: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(bundle, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _app_info(istat_code: str) -> dict[str, str]:
    return {
        "platform": "Android",
        "platformVersion": "4.1.2",
        "deviceUid": "comesibutta-public-data",
        "codiceIstatComune": istat_code,
        "lang": "IT",
    }


def _fetch_centre_details(user_agent: str, limiter: _RateLimiter) -> list[dict[str, Any]]:
    where = {"AND": [
        {"name": "_path", "value": "8C9879C6-9EBE-4649-8529-3C7B6131257B", "operator": "CONTAINS"},
        {"name": "_language", "value": "it-IT", "operator": "EQ"},
        {"name": "_templates", "value": "0A49DE01CBE84BB1A268D23FA9766381", "operator": "CONTAINS"},
    ]}
    after = ""
    results: list[dict[str, Any]] = []
    while True:
        limiter.wait()
        response = _post_json(
            GRAPHQL_URL,
            {"query": CENTRE_QUERY, "variables": {"where": where, "after": after}},
            user_agent,
            {"sc_apikey": SITECORE_API_KEY},
        )["data"]["doveLoPorto"]
        results.extend(response["results"])
        if not response["pageInfo"]["hasNext"]:
            return results
        after = response["pageInfo"]["endCursor"]


def fetch_alia_bundle(
    catalog: dict[str, Any], output: Path, observed_at: datetime,
    user_agent: str, delay: float = 1.0,
) -> dict[str, Any]:
    limiter = _RateLimiter(delay)
    bundle = json.loads(output.read_text(encoding="utf-8")) if output.exists() else {
        "observed_at": observed_at.isoformat(),
        "publisher": "Plures S.p.A. - AliaEstra",
        "source_pages": [CENTRE_PAGE, WASTE_PAGE, PICKUP_PAGE, KIT_PAGE],
        "access": {}, "centres": [], "eco_trucks": [], "centre_details": [],
        "public_pages": {}, "junker": {"queries": {}, "details": {}}, "errors": [],
    }
    bundle["source_pages"] = [CENTRE_PAGE, WASTE_PAGE, PICKUP_PAGE, KIT_PAGE, ACCESS_PAGE]
    robots_url = f"{ALIA_ROOT}/robots.txt"
    try:
        limiter.wait()
        request = Request(robots_url, headers={"User-Agent": user_agent, "Accept": "text/plain"})
        with urlopen(request, timeout=30) as response:
            robots_text = response.read().decode("utf-8", errors="replace")
        robots = robotparser.RobotFileParser(robots_url)
        robots.parse(robots_text.splitlines())
        blocked = [url for url in bundle["source_pages"] if not robots.can_fetch(user_agent, url)]
        bundle["access"]["website_robots"] = {
            "url": robots_url, "available": True, "blocked_urls": blocked,
            "allowed": not blocked,
        }
        if blocked:
            raise PermissionError(f"robots.txt blocks {len(blocked)} AliaEstra source pages")
    except Exception as error:
        if isinstance(error, PermissionError):
            raise
        raise RuntimeError(f"Unable to verify AliaEstra robots.txt: {error}") from error
    # The browser-facing API host returns 404 for robots.txt. Calls below are only
    # the read-only endpoints invoked by the public AliaEstra interface.
    bundle["access"]["bff_robots"] = {
        "url": f"{BFF_ROOT}/robots.txt", "available": False,
        "status": 404, "basis": "public_read_only_interface",
    }
    _save_checkpoint(output, bundle)

    bundle.setdefault("public_pages", {})
    for key, url in (("pickup", PICKUP_PAGE), ("kit", KIT_PAGE), ("access", ACCESS_PAGE)):
        if key in bundle["public_pages"]:
            continue
        try:
            limiter.wait()
            bundle["public_pages"][key] = {"url": url, "html": _get_text(url, user_agent)}
        except Exception as error:
            bundle["errors"].append({"stage": f"public_page_{key}", "url": url, "error": f"{type(error).__name__}: {error}"})
        _save_checkpoint(output, bundle)

    params = urlencode({"distance": 100000, "lat": 43.7696, "lng": 11.2558})
    for key, endpoint in (
        ("centres", f"{BFF_ROOT}/public/api/v1/gis/recycling-centers?{params}"),
        ("eco_trucks", f"{BFF_ROOT}/public/api/v1/gis/eco-trucks?{params}"),
    ):
        if not bundle[key]:
            try:
                limiter.wait()
                bundle[key] = _get_json(endpoint, user_agent)
            except Exception as error:
                bundle["errors"].append({"stage": key, "error": f"{type(error).__name__}: {error}"})
            _save_checkpoint(output, bundle)
    if not bundle["centre_details"]:
        try:
            bundle["centre_details"] = _fetch_centre_details(user_agent, limiter)
        except Exception as error:
            bundle["errors"].append({"stage": "centre_details", "error": f"{type(error).__name__}: {error}"})
        _save_checkpoint(output, bundle)

    representative_istat = "048017"
    autocomplete_url = f"{BFF_ROOT}/api/v1/reserved-area/junker/autocomplete"
    detail_url = f"{BFF_ROOT}/api/v1/reserved-area/junker/details"
    for index, query in enumerate(build_junker_queries(catalog), 1):
        if query in bundle["junker"]["queries"]:
            continue
        try:
            limiter.wait()
            response = _post_json(
                autocomplete_url,
                {"appInfo": _app_info(representative_istat), "query": query},
                user_agent,
            )
            bundle["junker"]["queries"][query] = response
            bundle["errors"] = [
                error for error in bundle["errors"]
                if not (error.get("stage") == "junker_autocomplete" and error.get("query") == query)
            ]
        except Exception as error:
            failure = {"stage": "junker_autocomplete", "query": query, "error": f"{type(error).__name__}: {error}"}
            if not any(item.get("stage") == failure["stage"] and item.get("query") == query for item in bundle["errors"]):
                bundle["errors"].append(failure)
        if index % 10 == 0:
            _save_checkpoint(output, bundle)
    _save_checkpoint(output, bundle)

    generic_ids = sorted({
        int(item["genericId"])
        for items in bundle["junker"]["queries"].values()
        for item in items
        if item.get("genericId") is not None
    })
    completed_detail_ids = {int(key) for key in bundle["junker"]["details"]}
    bundle["errors"] = [
        error for error in bundle["errors"]
        if not (
            error.get("stage") == "junker_details"
            and error.get("generic_id") in completed_detail_ids
        )
    ]
    consecutive_detail_failures = 0
    for index, generic_id in enumerate(generic_ids, 1):
        key = str(generic_id)
        if key in bundle["junker"]["details"]:
            continue
        try:
            limiter.wait()
            response = _post_json(
                detail_url,
                {"appInfo": _app_info(representative_istat), "genericId": generic_id},
                user_agent,
            )
            for bin_item in response.get("bins", []):
                bin_item.pop("icon", None)
            bundle["junker"]["details"][key] = response
            consecutive_detail_failures = 0
            bundle["errors"] = [
                error for error in bundle["errors"]
                if not (
                    (error.get("stage") == "junker_details" and error.get("generic_id") == generic_id)
                    or error.get("stage") == "junker_details_circuit_breaker"
                )
            ]
        except Exception as error:
            consecutive_detail_failures += 1
            failure = {"stage": "junker_details", "generic_id": generic_id, "error": f"{type(error).__name__}: {error}"}
            if not any(item.get("stage") == failure["stage"] and item.get("generic_id") == generic_id for item in bundle["errors"]):
                bundle["errors"].append(failure)
            if consecutive_detail_failures >= 5:
                bundle["errors"] = [
                    item for item in bundle["errors"]
                    if item.get("stage") != "junker_details_circuit_breaker"
                ]
                bundle["errors"].append({
                    "stage": "junker_details_circuit_breaker",
                    "generic_id": generic_id,
                    "error": "Five consecutive detail requests failed; acquisition suspended for a later resume",
                })
                _save_checkpoint(output, bundle)
                break
        if index % 10 == 0:
            _save_checkpoint(output, bundle)
    _save_checkpoint(output, bundle)
    return bundle


def _source(url: str, retrieved_at: datetime, content: Any, parser: str) -> SourceDocument:
    return SourceDocument(
        url, retrieved_at, json.dumps(content, ensure_ascii=False, sort_keys=True),
        publisher="Plures S.p.A. - AliaEstra", parser=parser, parser_version="0.1.0",
    )


def _municipality_key(value: str) -> str:
    return _slug(value).replace("-", "")


def _normalize_time(value: Any) -> str | None:
    match = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", str(value or ""))
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2))
    if hour > 23 or minute > 59:
        return None
    return f"{hour:02d}:{minute:02d}"


def _decode_sitecore_value(value: Any) -> str:
    return unquote(str(value or "")).strip()


def _opening_hours(item: dict[str, Any]) -> list[dict[str, Any]]:
    weekdays = {"lun": 1, "mar": 2, "mer": 3, "gio": 4, "ven": 5, "sab": 6, "dom": 7}
    intervals = []
    for row in (item.get("openingHours") or {}).get("jsonValue") or []:
        fields = row.get("fields") or {}
        day = str((fields.get("day") or {}).get("value") or "")
        weekday = weekdays.get(day.casefold()[:3])
        if not weekday:
            continue
        for suffix in ("1", "2"):
            opens = _normalize_time((fields.get(f"openingTime{suffix}") or {}).get("value"))
            closes = _normalize_time((fields.get(f"closingTime{suffix}") or {}).get("value"))
            if opens and closes:
                intervals.append({"weekday": weekday, "opens": opens, "closes": closes})
    return intervals


def materialize_alia(
    municipalities: list[dict[str, Any]], bundle: dict[str, Any], retrieved_at: datetime,
    output_dir: Path,
) -> dict[str, Any]:
    by_name = {_municipality_key(item["name"]): item for item in municipalities}
    details = {
        str(item.get("extId", {}).get("value")): item
        for item in bundle.get("centre_details", [])
        if item.get("extId", {}).get("value")
    }
    centre_source = _source(CENTRE_PAGE, retrieved_at, {
        "centres": bundle.get("centres", []), "eco_trucks": bundle.get("eco_trucks", []),
        "details": bundle.get("centre_details", []),
    }, "aliaestra_public_gis_sitecore")
    waste_details = bundle.get("junker", {}).get("details", {})
    waste_source = _source(WASTE_PAGE, retrieved_at, waste_details, "aliaestra_junker_json")
    pickup_page = bundle.get("public_pages", {}).get("pickup", {})
    pickup_html = pickup_page.get("html") or ""
    pickup_source = SourceDocument(
        PICKUP_PAGE, retrieved_at, pickup_html or json.dumps({"url": PICKUP_PAGE}),
        publisher="Plures S.p.A. - AliaEstra", parser="aliaestra_pickup_page", parser_version="0.1.0",
    )
    pickup_root = parse_html(pickup_html) if pickup_html else None
    pickup_text = clean_text(pickup_root.text) if pickup_root else ""
    booking_methods = [{"method": "web", "value": PICKUP_PAGE, "hours_raw": "Servizio online"}]
    if pickup_root:
        for link in pickup_root.find_all(lambda item: item.tag == "a" and bool(item.attrs.get("href"))):
            href = urljoin(PICKUP_PAGE, link.attrs["href"])
            if href.startswith("tel:") and not any(
                method["method"] == "phone" and method["value"] == href[4:]
                for method in booking_methods
            ):
                booking_methods.append({"method": "phone", "value": href[4:], "hours_raw": None})
    access_page = bundle.get("public_pages", {}).get("access", {})
    access_html = access_page.get("html") or ""
    access_root = parse_html(access_html) if access_html else None
    access_text = clean_text(access_root.text) if access_root else ""
    access_source = SourceDocument(
        ACCESS_PAGE, retrieved_at, access_html or json.dumps({"url": ACCESS_PAGE}),
        publisher="Plures S.p.A. - AliaEstra", parser="aliaestra_access_page", parser_version="0.1.0",
    )
    records_by_istat: dict[str, list[dict[str, Any]]] = {item["istat_code"]: [] for item in municipalities}

    destinations: dict[str, dict[str, Any]] = {}
    for generic_id, item in sorted(waste_details.items(), key=lambda pair: pair[1].get("genericDesc", "")):
        term = item.get("genericDesc")
        if not term:
            continue
        bins = item.get("bins") or []
        destination = ", ".join(bin_item.get("desc", "") for bin_item in bins if bin_item.get("desc")) or None
        for bin_item in bins:
            if bin_item.get("desc"):
                destinations.setdefault(bin_item["desc"], bin_item)
        for municipality in municipalities:
            context = MunicipalityContext(municipality["name"], municipality["istat_code"], municipality["source_slug"])
            records_by_istat[context.istat_code].append(make_record(
                record_type="waste_lookup",
                natural_key=f"waste-lookup:{context.istat_code}:{_slug(term)}",
                payload={
                    "municipality_ref": context.municipality_ref,
                    "term": term,
                    "destination_raw": destination,
                    "resolution_status": "resolved" if destination else "missing_destination",
                    "instructions_raw": f"Voce Junker/AliaEstra {generic_id}",
                },
                source=waste_source, evidence_kind="json",
                evidence_selector=f"details['{generic_id}']",
                evidence_quote=f"{term}: {destination or '[destinazione non pubblicata]'}",
            ))

    for municipality in municipalities:
        istat = municipality["istat_code"]
        context = MunicipalityContext(municipality["name"], istat, municipality["source_slug"])
        zone_ref = f"service-zone:{istat}:default"
        records_by_istat[istat].append(make_record(
            record_type="service_zone", natural_key=zone_ref,
            payload={"municipality_ref": context.municipality_ref, "name": "Intero territorio comunale", "scope_type": "municipality_default", "included_places_raw": None, "excluded_places_raw": None, "geometry_geojson": None},
            source=waste_source, evidence_kind="json", evidence_selector="junker.details", evidence_quote="Rifiutario AliaEstra per il territorio servito",
        ))
        for description, item in sorted(destinations.items()):
            color = item.get("color")
            records_by_istat[istat].append(make_record(
                record_type="collection_rule", natural_key=f"collection-rule:{istat}:default:{_slug(description)}",
                payload={
                    "municipality_ref": context.municipality_ref, "zone_ref": zone_ref,
                    "user_type": "all", "collection_method": "other", "stream_name": description,
                    "included_materials_raw": None, "container_type": "contenitore indicato da AliaEstra",
                    "container_color": f"#{color:06x}" if isinstance(color, int) else None,
                    "access_credential": None,
                    "presentation": {"mode": "unspecified", "max_volume_l": None, "instructions_raw": "Consultare il kit e il calendario del proprio indirizzo"},
                    "schedule_raw": "Variabile per indirizzo e sistema di raccolta",
                },
                source=waste_source, evidence_kind="json", evidence_selector=f"bins[id='{item.get('binId')}']", evidence_quote=description,
            ))
        records_by_istat[istat].append(make_record(
            record_type="pickup_service", natural_key=f"alia:pickup:{istat}:on-demand",
            payload={
                "municipality_ref": context.municipality_ref, "zone_ref": None,
                "user_type": "domestic", "accepted_waste_raw": "Rifiuti ingombranti e altri ritiri on demand pubblicati da AliaEstra",
                "booking_methods": booking_methods,
                "max_items": None, "quantity_limit_raw": None,
                "placement_instructions_raw": pickup_text[:4000] or "Verificare disponibilita e condizioni inserendo il proprio indirizzo sul portale AliaEstra.",
                "booking_required": True,
            },
            source=pickup_source, evidence_selector="page", evidence_quote="Ritiri on demand AliaEstra",
        ))

    for centre in bundle.get("centres", []):
        municipality = by_name.get(_municipality_key(str(centre.get("municipality") or "")))
        if not municipality:
            continue
        istat = municipality["istat_code"]
        sap_id = str(centre.get("sapId"))
        detail = details.get(sap_id, {})
        facility_ref = f"alia:facility:{sap_id}"
        records_by_istat[istat].append(make_record(
            record_type="facility", natural_key=facility_ref,
            payload={
                "name": centre.get("description"), "municipality_ref": f"istat:{istat}",
                "facility_type": "collection_centre", "address_raw": centre.get("address"),
                "location": {"latitude": centre["geometry"]["y"], "longitude": centre["geometry"]["x"], "method": "publisher_gis", "accuracy_m": None} if centre.get("geometry") else None,
                "phone": None, "email": None, "operational_status": "unknown", "status_raw": None,
            },
            source=centre_source, evidence_kind="json", evidence_selector=f"centres[sapId='{sap_id}']", evidence_quote=f"{centre.get('description')}: {centre.get('address')}",
        ))
        access_href = (((detail.get("regoleAccesso") or {}).get("jsonValue") or {}).get("value") or {}).get("href")
        records_by_istat[istat].append(make_record(
            record_type="facility_access", natural_key=f"{facility_ref}:access:{istat}:all",
            payload={
                "facility_ref": facility_ref, "municipality_ref": f"istat:{istat}", "user_type": "domestic", "allowed": True,
                "requirements_raw": access_text[:4000] or "Consultare le regole di accesso pubblicate da AliaEstra.", "booking_required": False,
                "information_urls": [f"{ALIA_ROOT}{access_href}" if access_href and access_href.startswith("/") else access_href or CENTRE_PAGE],
                "contact_phone": None, "contact_email": None,
            }, source=access_source, evidence_selector="main", evidence_quote=(access_text[:1000] or access_href or "Regole di accesso non collegate"),
        ))
        records_by_istat[istat].append(make_record(
            record_type="opening_period", natural_key=f"{facility_ref}:opening:published",
            payload={"facility_ref": facility_ref, "period_label": "Orario pubblicato", "start_month_day": None, "end_month_day": None, "weekly_intervals": _opening_hours(detail), "exceptions_raw": "Verificare variazioni e chiusure sul portale AliaEstra"},
            source=centre_source, evidence_kind="json", evidence_selector=f"details[extId='{sap_id}'].openingHours", evidence_quote=f"Orari di {centre.get('description')}",
        ))
        tooltips = {
            item.get("name"): _decode_sitecore_value(item.get("value"))
            for item in (detail.get("tooltipCosaPuoiConferire") or {}).get("values") or []
        }
        for material in (detail.get("cosaPuoiConferire") or {}).get("values") or []:
            description = _decode_sitecore_value(material.get("value"))
            if not description:
                continue
            records_by_istat[istat].append(make_record(
                record_type="facility_acceptance", natural_key=f"{facility_ref}:material:{_slug(description)}",
                payload={
                    "facility_ref": facility_ref, "eer_code_raw": None, "eer_code_normalized": None,
                    "eer_code_status": "unmapped_description", "reconciliation_basis": None,
                    "hazardous": None, "description_raw": description[:1].upper() + description[1:],
                    "operational_group": None, "user_type": "unspecified", "quantity_limit_raw": None,
                    "notes_raw": tooltips.get(material.get("name")),
                }, source=centre_source, evidence_kind="json", evidence_selector=f"details[extId='{sap_id}'].cosaPuoiConferire", evidence_quote=description,
            ))

    for truck in bundle.get("eco_trucks", []):
        municipality = by_name.get(_municipality_key(str(truck.get("municipality") or "")))
        if not municipality:
            continue
        istat = municipality["istat_code"]
        point_id = str(truck.get("idGis"))
        detail = details.get(point_id, {})
        address = ", ".join(part for part in (
            truck.get("streetName"), truck.get("locationDetails")
        ) if part)
        accepted_streams = [
            _decode_sitecore_value(item.get("value"))
            for item in (detail.get("cosaPuoiConferire") or {}).get("values") or []
            if _decode_sitecore_value(item.get("value"))
        ]
        records_by_istat[istat].append(make_record(
            record_type="collection_point", natural_key=f"alia:eco-truck:{point_id}",
            payload={
                "municipality_ref": f"istat:{istat}", "zone_ref": None,
                "name": detail.get("displayName") or truck.get("structureName") or "Ecofurgone AliaEstra",
                "point_type": "mobile", "address_raw": address or "Ubicazione pubblicata in mappa",
                "location": {"latitude": truck["geometry"]["y"], "longitude": truck["geometry"]["x"], "method": "publisher_gis", "accuracy_m": None} if truck.get("geometry") else None,
                "accepted_streams": accepted_streams or ["Materiali indicati nella scheda AliaEstra"],
                "access_credential": None,
                "access_notes_raw": "Postazione mobile pubblicata da AliaEstra.",
                "opening_hours_raw": "; ".join(
                    f"giorno {interval['weekday']} {interval['opens']}-{interval['closes']}"
                    for interval in _opening_hours(detail)
                ) or None,
            },
            source=centre_source, evidence_kind="json",
            evidence_selector=f"eco_trucks[idGis='{point_id}']",
            evidence_quote=f"{truck.get('municipality')}: {address}",
        ))

    reports = []
    total = 0
    missing_detail_by_istat: dict[str, list[str]] = {}
    for item, identifier_key in (
        *((item, "sapId") for item in bundle.get("centres", [])),
        *((item, "idGis") for item in bundle.get("eco_trucks", [])),
    ):
        municipality = by_name.get(_municipality_key(str(item.get("municipality") or "")))
        identifier = str(item.get(identifier_key))
        if municipality and identifier not in details:
            missing_detail_by_istat.setdefault(municipality["istat_code"], []).append(identifier)
    for municipality in municipalities:
        records = records_by_istat[municipality["istat_code"]]
        write_jsonl(output_dir / f"{municipality['source_slug']}-acquisition.jsonl", records)
        counts: dict[str, int] = {}
        for record in records:
            counts[record["record_type"]] = counts.get(record["record_type"], 0) + 1
        warnings = []
        if not counts.get("facility"):
            warnings.append({"code": "facility_not_in_municipality", "detail": "Nessun centro geolocalizzato nel territorio comunale nella fonte AliaEstra", "url": CENTRE_PAGE})
        if missing_detail_by_istat.get(municipality["istat_code"]):
            warnings.append({
                "code": "collection_point_detail_missing",
                "detail": "Scheda Sitecore non pubblicata per gli identificativi: " + ", ".join(missing_detail_by_istat[municipality["istat_code"]]),
                "url": CENTRE_PAGE,
            })
        reports.append({
            "municipality": municipality["name"], "istat_code": municipality["istat_code"],
            "pages_available": 3, "pages_materialized": 3, "equivalent_pages": [],
            "records": len(records), "records_by_type": counts, "warnings": warnings,
        })
        total += len(records)
    return {
        "observed_at": retrieved_at.isoformat(), "pages_checked": 3,
        "pages_remaining": 0, "municipalities_touched": len(municipalities),
        "pages_by_status": {"snapshot": 3},
        "pages_by_category": {"waste_lookup": 1, "facilities": 1, "pickup": 1},
        "access_preflight": bundle.get("access"), "errors": bundle.get("errors", []),
        "extraction": {"municipalities": len(municipalities), "records": total, "warnings": sum(len(item["warnings"]) for item in reports), "municipality_reports": reports},
        "coverage": {
            "autocomplete_queries": len(bundle.get("junker", {}).get("queries", {})),
            "waste_terms": len(waste_details), "centres": len(bundle.get("centres", [])),
            "eco_trucks": len(bundle.get("eco_trucks", [])), "sitecore_details": len(details),
            "method": "three-character prefixes derived from the canonical Tuscany catalog",
        },
    }
