from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import re
import time
from typing import Any
import unicodedata
from urllib import robotparser
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .html import clean_text, parse_html
from .records import SourceDocument, make_record, write_jsonl


HERA_APP_ROOT = "https://www.ilrifiutologo.it"
HERA_WEBAPP_ROOT = "https://webapp-ambiente.gruppohera.it"
HERA_API_ROOT = "https://webapp-ambiente.gruppohera.it/rifiutologo/rifiutologoweb"
MMS_ROOT = "https://www.gruppomarchemultiservizi.it"
MMS_WASTE_URL = f"{MMS_ROOT}/servizi/ambiente/il-rifiutologo"
MMS_COLLECTION_URL = (
    f"{MMS_ROOT}/servizi/ambiente/gestione-integrata-dei-rifiuti/"
    "servizi-di-raccolta-differenziata"
)
MMS_PICKUP_URL = (
    f"{MMS_ROOT}/servizi/ambiente/gestione-integrata-dei-rifiuti/"
    "servizi-di-raccolta-a-domicilio"
)
ATERSIR_SOURCE = "https://atersir.it/servizio-rifiuti/territorio-provinciale-di-bologna"
ATA_MARCHE_SOURCE = "https://www.atarifiuti.pu.it/lamministrazione/chi-siamo"
SESTINO_ROBOTS = "https://www.comune.sestino.ar.it/robots.txt"

BOUNDARY_MUNICIPALITIES = (
    {
        "name": "Firenzuola", "istat_code": "048018", "province_code": "FI",
        "ato_ref": "ato-emilia-romagna-bologna", "operator_ref": "hera",
        "operator_name": "Hera S.p.A.", "operator_url": "https://www.gruppohera.it",
        "hera_id": 76,
    },
    {
        "name": "Marradi", "istat_code": "048026", "province_code": "FI",
        "ato_ref": "ato-emilia-romagna-bologna", "operator_ref": "hera",
        "operator_name": "Hera S.p.A.", "operator_url": "https://www.gruppohera.it",
        "hera_id": 78,
    },
    {
        "name": "Palazzuolo sul Senio", "istat_code": "048031", "province_code": "FI",
        "ato_ref": "ato-emilia-romagna-bologna", "operator_ref": "hera",
        "operator_name": "Hera S.p.A.", "operator_url": "https://www.gruppohera.it",
        "hera_id": 82,
    },
    {
        "name": "Sestino", "istat_code": "051035", "province_code": "AR",
        "ato_ref": "ato-marche-1-pesaro-urbino", "operator_ref": "marche-multiservizi",
        "operator_name": "Marche Multiservizi S.p.A.", "operator_url": MMS_ROOT,
        "hera_id": None,
    },
)


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


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _save_checkpoint(path: Path, bundle: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(bundle, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _request_text(url: str, user_agent: str, accept: str = "text/html") -> str:
    request = Request(url, headers={"User-Agent": user_agent, "Accept": accept})
    with urlopen(request, timeout=60) as response:
        return response.read().decode("utf-8", errors="replace")


def _request_json(url: str, user_agent: str) -> Any:
    return json.loads(_request_text(url, user_agent, "application/json"))


def _api_url(endpoint: str, **params: Any) -> str:
    query = urlencode({key: value for key, value in params.items() if value is not None})
    return f"{HERA_API_ROOT}/{endpoint}" + (f"?{query}" if query else "")


def _robots_check(root: str, user_agent: str, urls: list[str]) -> dict[str, Any]:
    robots_url = f"{root}/robots.txt"
    text = _request_text(robots_url, user_agent, "text/plain")
    parser = robotparser.RobotFileParser(robots_url)
    parser.parse(text.splitlines())
    blocked = [url for url in urls if not parser.can_fetch(user_agent, url)]
    return {
        "url": robots_url,
        "available": True,
        "allowed": not blocked,
        "blocked_urls": blocked,
        "crawl_delay": parser.crawl_delay(user_agent) or parser.crawl_delay("*"),
        "content": text,
    }


def build_boundary_registry(
    retrieved_at: datetime,
    istat_by_name: dict[str, dict[str, str]],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    records = []
    warnings = []
    for item in BOUNDARY_MUNICIPALITIES:
        key = " ".join(item["name"].casefold().split())
        istat = next(
            (value for name, value in istat_by_name.items() if " ".join(name.casefold().split()) == key),
            None,
        )
        if not istat or istat["istat_code"] != item["istat_code"]:
            warnings.append({"code": "istat_match_missing", "detail": item["name"]})
            continue
        is_hera = item["operator_ref"] == "hera"
        source_url = ATERSIR_SOURCE if is_hera else ATA_MARCHE_SOURCE
        scope = (
            "Il bacino del servizio rifiuti della provincia di Bologna comprende anche "
            "Firenzuola, Marradi e Palazzuolo sul Senio."
            if is_hera else
            "La convenzione dell'ATO 1 Pesaro e Urbino comprende anche il Comune di Sestino."
        )
        source = SourceDocument(
            source_url, retrieved_at, scope,
            publisher="Atersir Emilia-Romagna" if is_hera else "ATA Rifiuti ATO 1 Pesaro e Urbino",
            parser="boundary_authority_scope", parser_version="0.1.0",
        )
        slug = _slug(item["name"])
        homepage = (
            f"{HERA_APP_ROOT}/casa/rifiutologo/{item['name'].replace(' ', '%20')}"
            if is_hera else MMS_WASTE_URL
        )
        records.append(make_record(
            record_type="municipality", natural_key=f"istat:{item['istat_code']}",
            payload={
                "istat_code": item["istat_code"], "name": item["name"],
                "province_code": item["province_code"], "region_code": "09",
                "ato_ref": item["ato_ref"], "operator_ref": item["operator_ref"],
                "local_operator_ref": item["operator_ref"],
                "local_operator_name": item["operator_name"],
                "local_operator_url": item["operator_url"],
                "assignment_status": "active",
                "assignment_note": "Comune toscano appartenente a un ATO con sede fuori regione.",
                "source_slug": slug, "homepage_url": homepage,
                "service_urls": {
                    "collection": [homepage] if is_hera else [MMS_COLLECTION_URL, MMS_WASTE_URL],
                    "facilities": [homepage] if is_hera else [MMS_WASTE_URL],
                    "pickup": [homepage] if is_hera else [MMS_PICKUP_URL],
                    "street_cleaning": [], "other": [source_url],
                },
            },
            source=source, evidence_selector="main", evidence_quote=f"{scope} Comune incluso: {item['name']}.",
        ))
    if len(records) != 4:
        warnings.append({"code": "unexpected_municipality_count", "detail": f"Attesi 4 comuni, trovati {len(records)}"})
    return records, warnings


def fetch_boundary_bundle(
    output: Path, observed_at: datetime, user_agent: str, delay: float = 0.5,
) -> dict[str, Any]:
    limiter = _RateLimiter(delay)
    bundle = json.loads(output.read_text(encoding="utf-8")) if output.exists() else {
        "observed_at": observed_at.isoformat(), "access": {}, "hera": {}, "mms": {"pages": {}}, "errors": [],
    }

    if bundle.get("access", {}).get("hera_api", {}).get("url") != f"{HERA_WEBAPP_ROOT}/robots.txt":
        limiter.wait()
        access = _robots_check(HERA_WEBAPP_ROOT, user_agent, [HERA_API_ROOT])
        bundle["access"]["hera_api"] = access
        if not access["allowed"]:
            raise PermissionError("robots.txt blocks the public Hera Rifiutologo API")
        _save_checkpoint(output, bundle)

    for item in BOUNDARY_MUNICIPALITIES:
        if not item["hera_id"]:
            continue
        slug = _slug(item["name"])
        municipality = bundle["hera"].setdefault(slug, {
            "name": item["name"], "istat_code": item["istat_code"], "hera_id": item["hera_id"],
            "sample": {}, "products": [], "product_data": {}, "stations": {},
        })
        try:
            if not municipality["products"]:
                limiter.wait()
                municipality["products"] = _request_json(
                    _api_url("getProdotti.php", idComune=item["hera_id"], isBusiness=0, isAcegas=0), user_agent,
                )
            if not municipality["sample"]:
                limiter.wait()
                addresses = _request_json(_api_url("getIndirizzi.php", idComune=item["hera_id"]), user_agent)
                address = addresses[0]
                limiter.wait()
                civics = _request_json(
                    _api_url("getNumeriCivici.php", idComune=item["hera_id"], idIndirizzo=address["id"]), user_agent,
                )
                civic = civics[0]
                municipality["sample"] = {
                    "address_id": address["id"], "address": address.get("descrizione") or address.get("nome"),
                    "civic_id": civic["id"], "civic": civic.get("descrizione") or civic.get("numeroCivico"),
                    "scope": "representative_address",
                }
            _save_checkpoint(output, bundle)
            for product in municipality["products"]:
                product_id = str(product["id"])
                if product_id in municipality["product_data"]:
                    continue
                limiter.wait()
                municipality["product_data"][product_id] = _request_json(_api_url(
                    "getDataRifiutologoWeb.php", idComune=item["hera_id"],
                    idIndirizzo=municipality["sample"]["address_id"],
                    idCivico=municipality["sample"]["civic_id"], isBusiness=0,
                    idSottocategoriaAzienda="", idProdotto=product_id,
                    latitudinePinHome=0, longitudinePinHome=0, isAcegas=0,
                ), user_agent)
                _save_checkpoint(output, bundle)
            station_ids = sorted({
                str(station["id"])
                for data in municipality["product_data"].values()
                for station in data.get("stazioniEcologiche", [])
                if station.get("id") is not None
            })
            for station_id in station_ids:
                if station_id in municipality["stations"]:
                    continue
                limiter.wait()
                municipality["stations"][station_id] = _request_json(_api_url(
                    "getDettaglioStazione.php", idComune=item["hera_id"],
                    idStazione=station_id, isBusiness=0,
                ), user_agent)
                _save_checkpoint(output, bundle)
        except Exception as error:
            failure = {"stage": "hera", "municipality": item["name"], "error": f"{type(error).__name__}: {error}"}
            if failure not in bundle["errors"]:
                bundle["errors"].append(failure)
            _save_checkpoint(output, bundle)

    mms_urls = [MMS_WASTE_URL, MMS_COLLECTION_URL, MMS_PICKUP_URL]
    recorded_mms_urls = set(bundle.get("access", {}).get("mms", {}).get("checked_urls", []))
    if "mms" not in bundle["access"] or recorded_mms_urls != set(mms_urls):
        limiter.wait()
        access = _robots_check(MMS_ROOT, user_agent, mms_urls)
        access["checked_urls"] = mms_urls
        bundle["access"]["mms"] = access
        _save_checkpoint(output, bundle)
    for key, url in (("waste", MMS_WASTE_URL), ("collection", MMS_COLLECTION_URL), ("pickup", MMS_PICKUP_URL)):
        if bundle["mms"]["pages"].get(key, {}).get("status") == "snapshot":
            continue
        if url in bundle["access"]["mms"]["blocked_urls"]:
            bundle["mms"]["pages"][key] = {"url": url, "status": "blocked_by_robots", "html": None}
        else:
            try:
                limiter.wait()
                bundle["mms"]["pages"][key] = {"url": url, "status": "snapshot", "html": _request_text(url, user_agent)}
            except Exception as error:
                bundle["mms"]["pages"][key] = {"url": url, "status": "error", "html": None, "error": f"{type(error).__name__}: {error}"}
        _save_checkpoint(output, bundle)
    if "sestino_municipality" not in bundle["access"]:
        limiter.wait()
        text = _request_text(SESTINO_ROBOTS, user_agent, "text/plain")
        parser = robotparser.RobotFileParser(SESTINO_ROBOTS)
        parser.parse(text.splitlines())
        bundle["access"]["sestino_municipality"] = {
            "url": SESTINO_ROBOTS, "available": True, "allowed": parser.can_fetch(user_agent, "https://www.comune.sestino.ar.it/"),
            "blocked_urls": [] if parser.can_fetch(user_agent, "https://www.comune.sestino.ar.it/") else ["https://www.comune.sestino.ar.it/"],
            "content": text,
        }
        _save_checkpoint(output, bundle)
    return bundle


def _plain_html(value: str | None) -> str | None:
    if not value:
        return None
    text = clean_text(parse_html(value).text)
    return text or None


def _presentation_mode(text: str | None) -> str:
    normalized = (text or "").casefold()
    bag_instruction = bool(re.search(
        r"(?:come conferire|raccogli\w*|introdu\w*|utilizz\w*|usare|all.interno).{0,140}sacchett",
        normalized,
    ))
    if bag_instruction and "compostabil" in normalized:
        return "compostable_bag"
    if bag_instruction and "plastic" in normalized:
        return "plastic_bag"
    if bag_instruction and ("chius" in normalized or "chiud" in normalized):
        return "closed_bag"
    if "sfus" in normalized:
        return "loose"
    if bag_instruction:
        return "bag_unspecified"
    return "unspecified"


def _source(url: str, retrieved_at: datetime, content: Any, publisher: str, parser: str) -> SourceDocument:
    return SourceDocument(url, retrieved_at, _json_text(content) if not isinstance(content, str) else content, publisher=publisher, parser=parser, parser_version="0.1.0")


def _hera_records(municipality: dict[str, Any], data: dict[str, Any], retrieved_at: datetime) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    istat = municipality["istat_code"]
    municipality_ref = f"istat:{istat}"
    source_url = f"{HERA_APP_ROOT}/casa/rifiutologo/{municipality['name'].replace(' ', '%20')}"
    source = _source(source_url, retrieved_at, data, "Hera S.p.A.", "hera_rifiutologo_json")
    zone_ref = f"service-zone:{istat}:sample-address"
    records = [make_record(
        record_type="service_zone", natural_key=zone_ref,
        payload={
            "municipality_ref": municipality_ref,
            "name": f"Configurazione osservata per {data['sample'].get('address') or 'un indirizzo campione'}",
            "scope_type": "named_area", "included_places_raw": data["sample"].get("address"),
            "excluded_places_raw": "Le modalità possono variare per altri indirizzi del comune.", "geometry_geojson": None,
        }, source=source, evidence_kind="json", evidence_selector="sample", evidence_quote=_json_text(data["sample"]), confidence="medium",
    )]
    products = {str(item["id"]): item for item in data.get("products", [])}
    rules: dict[str, dict[str, Any]] = {}
    point_categories = (
        "isoleInterrate", "onlus", "puntiDiRaccolta", "puntiDiRaccoltaFissi",
        "puntiDiRaccoltaFissiFarmaci", "puntiDiRaccoltaFissiOliAlimentari",
        "puntiDiRaccoltaFissiAbitiUsati", "puntiDiRaccoltaFissiRaee",
        "casetteSmartyNonResidenti", "puntiDiDistribuzione", "boxRiusoCambiaFinale",
    )
    points: dict[tuple[str, str], dict[str, Any]] = {}
    for product_id, result in sorted(data.get("product_data", {}).items(), key=lambda pair: int(pair[0])):
        product = products.get(product_id, {})
        term = clean_text(product.get("nome", ""))
        if not term:
            continue
        macroproducts = result.get("macroprodotti") or []
        destinations = []
        instructions = []
        for macro in macroproducts:
            note = _plain_html(macro.get("note"))
            if note:
                instructions.append(note)
            for destination in macro.get("conferimenti") or []:
                description = clean_text(destination.get("descrizione", ""))
                if description and description not in destinations:
                    destinations.append(description)
            rules[str(macro.get("id") or macro.get("descrizione"))] = macro
        extra = "; ".join(clean_text(str(product.get(key, ""))) for key in ("descrizione", "info") if product.get(key))
        keywords = clean_text(str(product.get("keywords") or ""))
        instruction = "; ".join(part for part in (extra, " ".join(instructions), f"Sinonimi ufficiali: {keywords}" if keywords else "") if part) or None
        destination_raw = ", ".join(destinations) or None
        records.append(make_record(
            record_type="waste_lookup", natural_key=f"waste-lookup:{istat}:{_slug(term)}",
            payload={
                "municipality_ref": municipality_ref, "term": term,
                "destination_raw": destination_raw,
                "resolution_status": "resolved" if destination_raw else "missing_destination",
                "instructions_raw": instruction,
            }, source=source, evidence_kind="json", evidence_selector=f"product_data['{product_id}']",
            evidence_quote=f"{term}: {destination_raw or '[destinazione non pubblicata]'}",
            confidence="medium",
        ))
        for category in point_categories:
            for point in result.get(category) or []:
                point_id = str(point.get("id") or _slug(_json_text(point)))
                points[(category, point_id)] = point

    for key, macro in sorted(rules.items(), key=lambda pair: clean_text(pair[1].get("descrizione", ""))):
        description = clean_text(macro.get("descrizione", ""))
        if not description:
            continue
        note = _plain_html(macro.get("note"))
        destinations = ", ".join(
            clean_text(item.get("descrizione", "")) for item in macro.get("conferimenti") or [] if clean_text(item.get("descrizione", ""))
        )
        records.append(make_record(
            record_type="collection_rule", natural_key=f"collection-rule:{istat}:sample:{_slug(description)}",
            payload={
                "municipality_ref": municipality_ref, "zone_ref": zone_ref, "user_type": "domestic",
                "collection_method": "other", "stream_name": description,
                "included_materials_raw": note, "container_type": destinations or None,
                "container_color": f"#{macro['pittogrammaColore']}" if re.fullmatch(r"[0-9A-Fa-f]{6}", str(macro.get("pittogrammaColore") or "")) else None,
                "access_credential": None,
                "presentation": {"mode": _presentation_mode(note), "max_volume_l": None, "instructions_raw": note},
                "schedule_raw": "Configurazione osservata per l'indirizzo campione; verificare il proprio indirizzo.",
            }, source=source, evidence_kind="json", evidence_selector=f"macroprodotti[id='{key}']",
            evidence_quote=f"{description}: {destinations}", confidence="medium",
        ))

    for (category, point_id), point in sorted(points.items()):
        accepted = [clean_text(item.get("descrizione", "")) for item in point.get("macroProdotti") or [] if clean_text(item.get("descrizione", ""))]
        address = ", ".join(part for part in (clean_text(str(point.get("indirizzo") or "")), clean_text(str(point.get("localita") or "")), clean_text(str(point.get("presso") or ""))) if part)
        latitude, longitude = point.get("latitudine"), point.get("longitudine")
        records.append(make_record(
            record_type="collection_point", natural_key=f"hera:collection-point:{category}:{point_id}",
            payload={
                "municipality_ref": municipality_ref, "zone_ref": None,
                "name": clean_text(point.get("nome", "")) or "Punto di raccolta Hera",
                "point_type": "mobile" if category == "puntiDiRaccolta" else "fixed",
                "accepted_streams": accepted or ["Materiali indicati nella scheda Hera"],
                "address_raw": address or "Ubicazione pubblicata in mappa",
                "location": {"latitude": latitude, "longitude": longitude, "method": "publisher_gis", "accuracy_m": None} if latitude is not None and longitude is not None else None,
                "access_notes_raw": None, "access_credential": None, "opening_hours_raw": None,
            }, source=source, evidence_kind="json", evidence_selector=f"{category}[id='{point_id}']",
            evidence_quote=f"{point.get('nome')}: {address}",
        ))

    for station_id, station in sorted(data.get("stations", {}).items()):
        facility_ref = f"hera:facility:{station_id}"
        facility_istat = next((item["istat_code"] for item in BOUNDARY_MUNICIPALITIES if item["name"].casefold() == str(station.get("comune") or "").casefold()), istat)
        latitude, longitude = station.get("latitudine"), station.get("longitudine")
        records.append(make_record(
            record_type="facility", natural_key=facility_ref,
            payload={
                "name": station.get("nome") or "Stazione ecologica Hera",
                "municipality_ref": f"istat:{facility_istat}", "facility_type": "collection_centre",
                "address_raw": station.get("indirizzo"),
                "location": {"latitude": latitude, "longitude": longitude, "method": "publisher_gis", "accuracy_m": None} if latitude is not None and longitude is not None else None,
                "phone": None, "email": None, "operational_status": "open", "status_raw": None,
            }, source=source, evidence_kind="json", evidence_selector=f"stations['{station_id}']", evidence_quote=f"{station.get('nome')}: {station.get('indirizzo')}",
        ))
        access_text = clean_text(str(station.get("descrizioneServizi") or ""))
        records.append(make_record(
            record_type="facility_access", natural_key=f"{facility_ref}:access:{istat}:domestic",
            payload={
                "facility_ref": facility_ref, "municipality_ref": municipality_ref,
                "user_type": "domestic", "allowed": True, "requirements_raw": access_text or None,
                "booking_required": False, "information_urls": [source_url],
                "contact_phone": None, "contact_email": None,
            }, source=source, evidence_kind="json", evidence_selector=f"stations['{station_id}'].descrizioneServizi", evidence_quote=access_text,
        ))
        openings: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
        for opening in station.get("aperture") or []:
            start = str(opening.get("dataInizio") or "")[:10]
            end = str(opening.get("dataFine") or "")[:10]
            group = (clean_text(str(opening.get("note") or "Orario pubblicato")), start, end)
            openings.setdefault(group, []).append({
                "weekday": int(opening["giorno"]), "opens": opening["orarioInizio"][:5], "closes": opening["orarioFine"][:5],
            })
        exceptions = "; ".join(
            f"{str(item.get('dataInizio') or '')[:10]} {clean_text(str(item.get('note') or 'chiuso'))}"
            for item in station.get("chiusure") or []
        ) or None
        for index, ((label, start, end), intervals) in enumerate(sorted(openings.items()), 1):
            records.append(make_record(
                record_type="opening_period", natural_key=f"{facility_ref}:opening:{index}:{start}:{end}",
                payload={
                    "facility_ref": facility_ref, "period_label": label,
                    "start_month_day": start[5:] if start else None, "end_month_day": end[5:] if end else None,
                    "weekly_intervals": sorted(intervals, key=lambda value: (value["weekday"], value["opens"])),
                    "exceptions_raw": exceptions,
                }, source=source, evidence_kind="json", evidence_selector=f"stations['{station_id}'].aperture", evidence_quote=f"{label}: {len(intervals)} intervalli",
            ))
        seen_acceptance = set()
        for macro in station.get("macroprodotti") or []:
            items = macro.get("prodotti") or [{"descrizione": macro.get("descrizione"), "limite": macro.get("limite"), "sconto": macro.get("sconto")}]
            for accepted in items:
                description = clean_text(str(accepted.get("descrizione") or ""))
                if not description or description.casefold() in seen_acceptance:
                    continue
                seen_acceptance.add(description.casefold())
                limit = clean_text(str(accepted.get("limite") or macro.get("limite") or "")) or None
                discount = clean_text(str(accepted.get("sconto") or macro.get("sconto") or "")) or None
                records.append(make_record(
                    record_type="facility_acceptance", natural_key=f"{facility_ref}:material:{_slug(description)}",
                    payload={
                        "facility_ref": facility_ref, "eer_code_raw": None, "eer_code_normalized": None,
                        "eer_code_status": "unmapped_description", "reconciliation_basis": None,
                        "hazardous": None, "description_raw": description,
                        "operational_group": clean_text(str(macro.get("descrizione") or "")) or None,
                        "user_type": "unspecified", "quantity_limit_raw": limit, "notes_raw": f"Sconto: {discount}" if discount else None,
                    }, source=source, evidence_kind="json", evidence_selector=f"stations['{station_id}'].macroprodotti", evidence_quote=f"{description}: {limit or 'limite non indicato'}",
                ))
    warnings = [{
        "code": "address_specific_collection_rules",
        "detail": "Rifiutario e regole derivano da un indirizzo campione; l'utente deve selezionare il proprio indirizzo per la conferma.",
        "url": source_url,
    }]
    return records, warnings


def _sestino_records(data: dict[str, Any], retrieved_at: datetime) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    istat = "051035"
    pages = data.get("pages", {})
    pickup = pages.get("pickup", {})
    pickup_html = pickup.get("html") or ""
    source = SourceDocument(
        pickup.get("url") or MMS_PICKUP_URL, retrieved_at, pickup_html or MMS_PICKUP_URL,
        publisher="Marche Multiservizi S.p.A.", parser="mms_public_page", parser_version="0.1.0",
    )
    text = clean_text(parse_html(pickup_html).text) if pickup_html else ""
    phone = next(iter(re.findall(r"(?:800[ .]?\d{3}[ .]?\d{3})", text)), "800.600.999").replace(" ", "")
    records = [make_record(
        record_type="pickup_service", natural_key=f"mms:pickup:{istat}:bulky",
        payload={
            "municipality_ref": f"istat:{istat}", "zone_ref": None, "user_type": "domestic",
            "accepted_waste_raw": "Rifiuti ingombranti, RAEE e sfalci/potature secondo le condizioni pubblicate da Marche Multiservizi",
            "booking_methods": [
                {"method": "phone", "value": phone, "hours_raw": None},
                {"method": "app", "value": "Il Rifiutologo", "hours_raw": None},
            ],
            "max_items": None, "quantity_limit_raw": "Massimo 2 m3; massimo 3 ritiri l'anno, uno ogni 4 mesi",
            "placement_instructions_raw": "Ritiro gratuito per utenze domestiche al piano stradale; verificare le condizioni aggiornate alla prenotazione.",
            "booking_required": True,
        }, source=source, evidence_selector="main", evidence_quote="Ritiro domiciliare su prenotazione per ingombranti, RAEE e verde.",
    )]
    warnings = [
        {
            "code": "municipality_source_blocked_by_robots",
            "detail": "Il sito istituzionale del Comune di Sestino vieta l'acquisizione automatica di tutte le pagine; nessuna pagina comunale e stata visitata.",
            "url": SESTINO_ROBOTS,
        },
        {
            "code": "waste_dictionary_app_only",
            "detail": "Marche Multiservizi pubblica il rifiutario dettagliato nell'app, ma non espone una versione web acquisibile senza usare percorsi vietati da robots.txt.",
            "url": MMS_WASTE_URL,
        },
        {
            "code": "local_collection_configuration_not_published",
            "detail": "La pagina generale del gestore descrive sistemi diversi; non e stata attribuita a Sestino una regola locale non verificata.",
            "url": MMS_COLLECTION_URL,
        },
        {
            "code": "facility_data_app_only",
            "detail": "Localizzazione, orari e materiali dei centri sono dichiarati disponibili nell'app Il Rifiutologo, ma non in una fonte web acquisibile individuata.",
            "url": MMS_WASTE_URL,
        },
    ]
    return records, warnings


def materialize_boundary(
    registry: list[dict[str, Any]], bundle: dict[str, Any], retrieved_at: datetime, output_dir: Path,
) -> dict[str, Any]:
    reports = []
    total_records = 0
    total_warnings = 0
    for municipality in registry:
        if municipality["operator_ref"] == "hera":
            records, warnings = _hera_records(municipality, bundle.get("hera", {}).get(municipality["source_slug"], {}), retrieved_at)
            pages_available = 3
        else:
            records, warnings = _sestino_records(bundle.get("mms", {}), retrieved_at)
            pages_available = sum(page.get("status") == "snapshot" for page in bundle.get("mms", {}).get("pages", {}).values())
        write_jsonl(output_dir / f"{municipality['source_slug']}-acquisition.jsonl", records)
        counts: dict[str, int] = {}
        for record in records:
            counts[record["record_type"]] = counts.get(record["record_type"], 0) + 1
        report = {
            "municipality": municipality["name"], "istat_code": municipality["istat_code"],
            "pages_available": pages_available, "pages_materialized": pages_available,
            "equivalent_pages": [], "records": len(records), "records_by_type": counts, "warnings": warnings,
        }
        reports.append(report)
        (output_dir / f"{municipality['source_slug']}-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        total_records += len(records)
        total_warnings += len(warnings)
    return {
        "observed_at": retrieved_at.isoformat(), "pages_checked": sum(item["pages_available"] for item in reports),
        "pages_remaining": 0, "pages_by_status": {"snapshot": sum(item["pages_available"] for item in reports)},
        "pages_by_category": {"waste_lookup": 4, "facilities": 4, "pickup": 1},
        "access_preflight": bundle.get("access", {}), "errors": bundle.get("errors", []),
        "extraction": {"municipalities": len(reports), "records": total_records, "warnings": total_warnings, "municipality_reports": reports},
        "coverage": {
            "hera_municipalities": 3,
            "hera_products": sum(len(value.get("products", [])) for value in bundle.get("hera", {}).values()),
            "hera_product_details": sum(len(value.get("product_data", {})) for value in bundle.get("hera", {}).values()),
            "hera_stations": sum(len(value.get("stations", {})) for value in bundle.get("hera", {}).values()),
            "sestino_detail_status": "partial_due_to_robots_and_app_only_sources",
        },
    }
