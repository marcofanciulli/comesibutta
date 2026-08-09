from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess
from tempfile import TemporaryDirectory
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

AAMPS_2023_SHA256 = "94b745da64d7886a11eaa77fe169452c10796201eb08fc2c869f0fa06f85ea2c"
AAMPS_FACILITIES_SHA256 = "57dbe81ea504a6e32c3148a4ed662014c0637eff02b11105fc1a6fb27238ba84"
ERSU_MONTIGNOSO_SHA256 = "4e82db9b8c447037a29f5de381331701c69578dbfe9c0d6f2107fab56eeaa2c9"
AAMPS_ICON_COLORS = {
    "Organico": (105, 55, 35),
    "Carta e cartone": (42, 130, 204),
    "Multimateriale": (241, 206, 0),
    "Vetro": (47, 188, 69),
    "Rifiuto indifferenziato": (92, 98, 109),
    "Farmaci": (70, 109, 153),
    "Pile": (239, 15, 33),
    "Abiti": (143, 220, 0),
    "Centri di raccolta": (0, 101, 43),
    "Centri autorizzati": (141, 7, 83),
    "RAEE": (66, 198, 235),
    "Ritiro ingombranti": (139, 73, 189),
    "Ritiro sfalci e potature": (110, 141, 46),
}


def extract_aamps_2023_bundle(
    context: MunicipalityContext,
    retrieved_at: datetime,
    guide_url: str,
    guide_pdf: bytes,
    facilities_url: str,
    facilities_pdf: bytes,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Extract the SHA-locked visual AAMPS guide and its operational facilities page."""
    warnings: list[dict[str, str]] = []
    if hashlib.sha256(guide_pdf).hexdigest() != AAMPS_2023_SHA256:
        return [], [{"code": "aamps_guide_changed", "detail": "Il PDF AAMPS 2023 e cambiato e richiede una nuova verifica visiva", "url": guide_url}]
    if hashlib.sha256(facilities_pdf).hexdigest() != AAMPS_FACILITIES_SHA256:
        return [], [{"code": "aamps_facilities_guide_changed", "detail": "Il calendario AAMPS e cambiato e richiede una nuova verifica", "url": facilities_url}]

    source = SourceDocument(guide_url, retrieved_at, guide_pdf, publisher="AAMPS S.p.A.", parser="aamps_2023_visual_pdf", parser_version="0.1.0")
    records: list[dict[str, Any]] = []
    with TemporaryDirectory() as directory:
        root = Path(directory)
        pdf_path = root / "guide.pdf"
        pdf_path.write_bytes(guide_pdf)
        bbox = subprocess.run(["pdftotext", "-bbox-layout", str(pdf_path), "-"], check=True, capture_output=True).stdout.decode("utf-8", errors="replace")
        subprocess.run(["pdftoppm", "-f", "5", "-l", "31", "-r", "72", str(pdf_path), str(root / "page")], check=True, capture_output=True)
        lines = _aamps_term_lines(bbox)
        images = {page: _read_ppm(next(root.glob(f"page-{page:02d}.ppm"))) for page in range(5, 32)}
        for page, y_min, y_max, term in lines:
            destinations = _aamps_destinations(images[page], y_min, y_max)
            destination = ", ".join(destinations)
            records.append(make_record(
                record_type="waste_lookup",
                natural_key=f"waste-lookup:{context.istat_code}:{_slug(term)}",
                payload={"municipality_ref": context.municipality_ref, "term": term, "destination_raw": destination or None, "resolution_status": "resolved" if destination else "missing_destination", "instructions_raw": "Destinazioni indicate dai simboli nella guida AAMPS 2023"},
                source=source, evidence_kind="pdf", evidence_selector=f"page:{page}:y:{y_min:.1f}", evidence_quote=f"{term}: {destination or '[simbolo non riconosciuto]'}",
                confidence="high" if destination else "low",
            ))
            if not destination:
                warnings.append({"code": "aamps_icon_not_recognized", "detail": f"Pagina {page}: {term}", "url": guide_url})
    records.extend(_aamps_facility_records(context, retrieved_at, facilities_url, facilities_pdf))
    warnings.append({"code": "collection_rules_not_municipality_wide", "detail": "Il calendario acquisito riguarda la zona Pentagono e non viene esteso all'intero comune", "url": facilities_url})
    return records, warnings


def _aamps_term_lines(bbox: str) -> list[tuple[int, float, float, str]]:
    root = ET.fromstring(bbox)
    namespace = {"x": "http://www.w3.org/1999/xhtml"}
    result = []
    for page_number, page in enumerate(root.findall(".//x:page", namespace), 1):
        if not 5 <= page_number <= 31:
            continue
        for line in page.findall(".//x:line", namespace):
            x = float(line.attrib["xMin"])
            if not 68 <= x <= 73:
                continue
            term = clean_text(" ".join(word.text or "" for word in line.findall("x:word", namespace)))
            if (
                term
                and term != "(private del contenuto)"
                and not (len(term) == 1 and term.isalpha())
            ):
                result.append((page_number, float(line.attrib["yMin"]), float(line.attrib["yMax"]), term))
    return result


def _read_ppm(path: Path) -> tuple[int, int, bytes]:
    data = path.read_bytes()
    match = re.match(rb"P6\s+(?:#.*\s+)*(\d+)\s+(\d+)\s+255\s", data)
    if not match:
        raise ValueError(f"Formato PPM inatteso: {path}")
    return int(match.group(1)), int(match.group(2)), data[match.end():]


def _aamps_destinations(image: tuple[int, int, bytes], y_min: float, y_max: float) -> list[str]:
    width, height, pixels = image
    counts = {name: 0 for name in AAMPS_ICON_COLORS}
    for y in range(max(0, int(y_min) - 4), min(height, int(y_max) + 6)):
        for x in range(315, min(width, 479)):
            offset = (y * width + x) * 3
            rgb = pixels[offset:offset + 3]
            if len(rgb) != 3:
                continue
            nearest, distance = min(((name, sum((rgb[index] - color[index]) ** 2 for index in range(3))) for name, color in AAMPS_ICON_COLORS.items()), key=lambda item: item[1])
            if distance < 45 ** 2:
                counts[nearest] += 1
    return [name for name in AAMPS_ICON_COLORS if counts[name] > 35]


def _aamps_facility_records(context: MunicipalityContext, retrieved_at: datetime, url: str, pdf: bytes) -> list[dict[str, Any]]:
    source = SourceDocument(url, retrieved_at, pdf, publisher="AAMPS S.p.A.", parser="aamps_facilities_pdf", parser_version="0.1.0")
    records: list[dict[str, Any]] = []
    centres = (
        ("Picchianti", "Via degli Arrotini 49, Livorno", "19:00"),
        ("Livorno Sud", "Via Cattaneo 81, Livorno", "17:00"),
    )
    materials = ("Rifiuti urbani differenziati", "Mobili e arredi", "Grandi e piccoli elettrodomestici", "Pile e batterie e alcune tipologie di rifiuti speciali")
    for name, address, closes in centres:
        facility_ref = f"aamps:facility:{_slug(name)}"
        records.append(make_record(record_type="facility", natural_key=facility_ref, payload={"name": f"Centro di raccolta {name}", "municipality_ref": context.municipality_ref, "facility_type": "collection_centre", "address_raw": address, "location": None, "phone": "0586416350", "email": "info@aamps.livorno.it", "operational_status": "open", "status_raw": None}, source=source, evidence_kind="pdf", evidence_selector="page:2", evidence_quote=f"{name}: {address}"))
        records.append(make_record(record_type="facility_access", natural_key=f"{facility_ref}:access:{context.istat_code}:domestic", payload={"facility_ref": facility_ref, "municipality_ref": context.municipality_ref, "user_type": "domestic", "allowed": True, "requirements_raw": "Utenze domestiche; accesso con tessera sanitaria", "booking_required": False, "information_urls": [url], "contact_phone": "0586416350", "contact_email": "info@aamps.livorno.it"}, source=source, evidence_kind="pdf", evidence_selector="page:2", evidence_quote="SI ACCEDE CON LA TESSERA SANITARIA"))
        records.append(make_record(record_type="opening_period", natural_key=f"{facility_ref}:opening:ordinario", payload={"facility_ref": facility_ref, "period_label": "Orario ordinario", "start_month_day": None, "end_month_day": None, "weekly_intervals": [{"weekday": day, "opens": "08:00", "closes": "12:00"} for day in range(1, 7)] + [{"weekday": day, "opens": "13:00", "closes": closes} for day in range(1, 7)], "exceptions_raw": "Chiuso la domenica"}, source=source, evidence_kind="pdf", evidence_selector="page:2", evidence_quote=f"dal lunedi al sabato 8.00-12.00 e 13.00-{closes}"))
        for material in materials:
            records.append(make_record(record_type="facility_acceptance", natural_key=f"{facility_ref}:material:{_slug(material)}", payload={"facility_ref": facility_ref, "eer_code_raw": None, "eer_code_normalized": None, "eer_code_status": "unmapped_description", "reconciliation_basis": None, "hazardous": None, "description_raw": material, "operational_group": None, "user_type": "domestic", "quantity_limit_raw": None, "notes_raw": "Descrizione generale pubblicata da AAMPS; verificare le tipologie speciali con il gestore"}, source=source, evidence_kind="pdf", evidence_selector="page:2", evidence_quote=material))
    records.extend(_aamps_collection_points(context, source, url))
    return records


def _aamps_collection_points(context: MunicipalityContext, source: SourceDocument, url: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    mobile = ((1, "Piazza Sforzini"), (2, "Piazza Bartolommei"), (3, "Piazza Barriera Garibaldi"), (4, "Piazza del Luogo Pio"), (5, "Piazza Matteotti"), (6, "Piazza Damiano Chiesa"))
    for weekday, address in mobile:
        ref = f"aamps:point:isola-mobile:{_slug(address)}"
        records.append(make_record(record_type="collection_point", natural_key=ref, payload={"municipality_ref": context.municipality_ref, "zone_ref": None, "name": "Isola ecologica mobile", "point_type": "mobile", "accepted_streams": ["Organico", "Multimateriale", "Rifiuto indifferenziato"], "address_raw": address, "location": None, "access_notes_raw": "Sacchetti ben chiusi; servizio non attivo nei giorni festivi", "access_credential": "Tessera sanitaria", "information_urls": [url], "opening_hours_raw": "07:00-12:00 nel giorno settimanale indicato"}, source=source, evidence_kind="pdf", evidence_selector="page:2", evidence_quote=f"{address}, ore 7-12"))
        records.append(make_record(record_type="collection_schedule", natural_key=f"{ref}:schedule", payload={"collection_point_ref": ref, "expose_from": None, "expose_by": None, "events": [{"kind": "weekly", "weekday": weekday, "dates": [], "start_month_day": None, "end_month_day": None, "raw": "07:00-12:00; esclusi festivi"}]}, source=source, evidence_kind="pdf", evidence_selector="page:2", evidence_quote=f"{address}, ore 7-12"))
    oil_addresses = ("Via Gobetti (angolo Piazza Saragat)", "Piazza Europa (angolo Via Inghilterra)", "Piazza D. Chiesa (fronte Via Vecchia di Salviano)", "Piazza Sforzini (angolo Via Giuliano Ricci)", "Piazza Matteotti", "Piazza 185 Reggimento Artiglieria Folgore", "Piazza delle Carrozze", "Via Buontalenti (angolo Via della Coroncina)", "Via Pietro Nardini (angolo Piazza Fattori, Quercianella)")
    for address in oil_addresses:
        ref = f"aamps:point:olio:{_slug(address)}"
        records.append(make_record(record_type="collection_point", natural_key=ref, payload={"municipality_ref": context.municipality_ref, "zone_ref": None, "name": "Punto itinerante oli vegetali esausti", "point_type": "temporary", "accepted_streams": ["Oli vegetali esausti"], "address_raw": address, "location": None, "access_notes_raw": "Contenitore itinerante blu", "access_credential": None, "information_urls": [url], "opening_hours_raw": "Ogni secondo e quarto giovedi del mese, 08:00-15:00"}, source=source, evidence_kind="pdf", evidence_selector="page:2", evidence_quote=f"{address}; secondo e quarto giovedi 8-15"))
    records.append(make_record(record_type="collection_point", natural_key="aamps:point:centro-riuso-via-cattaneo", payload={"municipality_ref": context.municipality_ref, "zone_ref": None, "name": "Centro del riuso", "point_type": "fixed", "accepted_streams": ["Beni usati riutilizzabili"], "address_raw": "Via Cattaneo 81, Livorno", "location": None, "access_notes_raw": "Consegna gratuita di mobili, elettrodomestici, biciclette e libri ancora riutilizzabili; accesso libero", "access_credential": None, "information_urls": [url], "opening_hours_raw": "Dal martedi al sabato 08:00-12:00 e 15:00-19:00"}, source=source, evidence_kind="pdf", evidence_selector="page:2", evidence_quote="Area per la consegna a titolo gratuito di beni usati"))
    return records


def extract_ersu_montignoso_supplement(
    context: MunicipalityContext,
    retrieved_at: datetime,
    url: str,
    pdf: bytes,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    if hashlib.sha256(pdf).hexdigest() != ERSU_MONTIGNOSO_SHA256:
        return [], [{"code": "ersu_montignoso_guide_changed", "detail": "La guida ERSU Montignoso e cambiata e richiede una nuova verifica", "url": url}]
    source = SourceDocument(url, retrieved_at, pdf, publisher="ERSU S.p.A.", parser="ersu_montignoso_pdf", parser_version="0.1.0")
    records: list[dict[str, Any]] = []
    facilities = (
        ("Centro di raccolta Piedimonte", "ersu:facility:centro-di-raccolta-piedimonte", "istat:045011", "Via Piedimonte snc, 54038 Montignoso (MS)", "13:00", False),
        ("Centro di raccolta Olmi", "ersu:facility:centro-di-raccolta-olmi-pietrasanta", "istat:046024", "Via Olmi snc, 55045 Pietrasanta (LU)", "19:00", True),
        ("Centro di raccolta Ciocche", "ersu:facility:centro-di-raccolta-ciocche-seravezza", "istat:046028", "Via Ciocche snc, 55047 Seravezza (LU)", "19:00", False),
    )
    acceptances = (
        ("150101", False, "Imballaggi carta e cartone"), ("150106", False, "Imballaggi di materiali misti"),
        ("150107", False, "Imballaggi in vetro"), ("160103", False, "Pneumatici fuori uso"),
        ("080318", False, "Componenti rimossi di apparecchiature fuori uso (toner)"),
        ("170107", False, "Cemento, mattoni, mattonelle e ceramiche"), ("200102", False, "Rifiuti in vetro"),
        ("200108", False, "Rifiuti biodegradabili di cucine"), ("200110", False, "Abbigliamento"),
        ("200121", None, "Tubi fluorescenti e altri rifiuti contenenti mercurio (R5)"),
        ("200123", True, "Apparecchiature fuori uso contenenti CFC (R1)"),
        ("200125", False, "Oli e grassi commestibili"),
        ("200127", True, "Vernici, inchiostri, adesivi e resine contenenti sostanze pericolose"),
        ("200132", False, "Medicinali diversi da quelli alla voce 200131"),
        ("200133", True, "Batterie e accumulatori"),
        ("200135", True, "Apparecchiature elettriche ed elettroniche fuori uso contenenti componenti pericolosi (R3)"),
        ("200136", False, "Apparecchiature elettriche ed elettroniche fuori uso non pericolose (R2) (R4)"),
        ("200140", False, "Rifiuti metallici"), ("200307", False, "Rifiuti ingombranti"),
    )
    requirements = "Utenze domestiche residenti con tessera sanitaria; per le seconde case puo accedere l'intestatario TARI con tessera sanitaria."
    for name, ref, host_ref, address, closes, summer_sunday in facilities:
        records.append(make_record(record_type="facility", natural_key=ref, payload={"name": name, "municipality_ref": host_ref, "facility_type": "collection_centre", "address_raw": address, "location": None, "phone": "800942540", "email": "urp@ersu.it", "operational_status": "open", "status_raw": None}, source=source, evidence_kind="pdf", evidence_selector="page:28", evidence_quote=f"{name}: {address}"))
        records.append(make_record(record_type="facility_access", natural_key=f"{ref}:access:{context.istat_code}:domestic", payload={"facility_ref": ref, "municipality_ref": context.municipality_ref, "user_type": "domestic", "allowed": True, "requirements_raw": requirements, "booking_required": False, "information_urls": [url], "contact_phone": "800942540", "contact_email": "urp@ersu.it"}, source=source, evidence_kind="pdf", evidence_selector="page:27", evidence_quote="I cittadini del comune di Montignoso possono recarsi presso il centro Piedimonte o gli altri CdR ERSU"))
        exceptions = "Chiuso la domenica" + ("; in estate aperto anche la domenica, consultare le date sul sito" if summer_sunday else "")
        records.append(make_record(record_type="opening_period", natural_key=f"{ref}:opening:guida-montignoso", payload={"facility_ref": ref, "period_label": "Orario pubblicato nella guida Montignoso", "start_month_day": None, "end_month_day": None, "weekly_intervals": [{"weekday": day, "opens": "07:00", "closes": closes} for day in range(1, 7)], "exceptions_raw": exceptions}, source=source, evidence_kind="pdf", evidence_selector="page:28", evidence_quote=f"dal lunedi al sabato 7:00-{closes}"))
        for code, hazardous, description in acceptances:
            raw_code = code + ("*" if hazardous else "")
            records.append(make_record(record_type="facility_acceptance", natural_key=f"{ref}:eer:{code}", payload={"facility_ref": ref, "eer_code_raw": raw_code, "eer_code_normalized": code, "eer_code_status": "exact", "reconciliation_basis": None, "hazardous": hazardous, "description_raw": description, "operational_group": None, "user_type": "domestic", "quantity_limit_raw": None, "notes_raw": "Elenco comune ai vari Centri di Raccolta nella guida ERSU Montignoso"}, source=source, evidence_kind="pdf", evidence_selector="page:29", evidence_quote=f"{description} CER {raw_code}"))
    green_ref = "ersu:facility:impianto-verde"
    records.append(make_record(record_type="facility", natural_key=green_ref, payload={"name": "Centro di raccolta verde", "municipality_ref": "istat:046024", "facility_type": "temporary_area", "address_raw": "Via Pontenuovo 22, 55045 Pietrasanta (LU)", "location": None, "phone": "0584282211", "email": "urp@ersu.it", "operational_status": "open", "status_raw": None}, source=source, evidence_kind="pdf", evidence_selector="page:31", evidence_quote="Via Pontenuovo n. 22, Pietrasanta"))
    for user_type, access_requirements in (("domestic", requirements), ("non_domestic", "Utenze professionali previa procedura di registrazione e accettazione; consultare ERSU per la documentazione.")):
        records.append(make_record(record_type="facility_access", natural_key=f"{green_ref}:access:{context.istat_code}:{user_type}", payload={"facility_ref": green_ref, "municipality_ref": context.municipality_ref, "user_type": user_type, "allowed": True, "requirements_raw": access_requirements, "booking_required": False, "information_urls": [url], "contact_phone": "0584282211", "contact_email": "urp@ersu.it"}, source=source, evidence_kind="pdf", evidence_selector="page:30", evidence_quote=access_requirements))
    records.append(make_record(record_type="opening_period", natural_key=f"{green_ref}:opening:guida-montignoso", payload={"facility_ref": green_ref, "period_label": "Orario pubblicato nella guida Montignoso", "start_month_day": None, "end_month_day": None, "weekly_intervals": [{"weekday": day, "opens": "07:00", "closes": "19:00"} for day in range(1, 7)], "exceptions_raw": "Orario estivo aperto anche la domenica; consultare le date sul sito"}, source=source, evidence_kind="pdf", evidence_selector="page:31", evidence_quote="orario invernale dal lunedi al sabato 7:00-19:00; orario estivo aperto anche la domenica"))
    records.append(make_record(record_type="facility_acceptance", natural_key=f"{green_ref}:material:sfalci-potature-biomasse", payload={"facility_ref": green_ref, "eer_code_raw": None, "eer_code_normalized": None, "eer_code_status": "unmapped_description", "reconciliation_basis": None, "hazardous": False, "description_raw": "Sfalci, potature e biomasse", "operational_group": None, "user_type": "all", "quantity_limit_raw": None, "notes_raw": None}, source=source, evidence_kind="pdf", evidence_selector="page:30", evidence_quote="centro di conferimento temporaneo di sfalci, potature e biomasse"))
    records.extend(_ersu_montignoso_pickups(context, source))
    return records, []


def _ersu_montignoso_pickups(context: MunicipalityContext, source: SourceDocument) -> list[dict[str, Any]]:
    common = [{"method": "web", "value": "https://ersu.it/", "hours_raw": None}, {"method": "email", "value": "urp@ersu.it", "hours_raw": None}, {"method": "app", "value": "portAPPorta", "hours_raw": None}, {"method": "phone", "value": "800942540", "hours_raw": "Dal lunedi al sabato 08:30-13:30"}]
    definitions = (
        ("ingombranti", "Rifiuti ingombranti domestici", 5, "Fino a 5 pezzi", None, "page:22"),
        ("raee", "RAEE ingombranti", 5, "Fino a 5 pezzi", None, "page:23"),
        ("olio-alimentare", "Oli vegetali esausti", None, "Tanica da 5 litri fornita gratuitamente", "Esporre la tanica la sera prima del giorno concordato", "page:24"),
    )
    records = [make_record(record_type="pickup_service", natural_key=f"ersu:pickup:{context.istat_code}:{key}", payload={"municipality_ref": context.municipality_ref, "zone_ref": None, "user_type": "domestic", "accepted_waste_raw": waste, "booking_methods": common, "max_items": maximum, "quantity_limit_raw": limit, "placement_instructions_raw": placement, "booking_required": True}, source=source, evidence_kind="pdf", evidence_selector=page, evidence_quote=f"Servizio a richiesta: {waste}") for key, waste, maximum, limit, placement, page in definitions]
    records.append(make_record(record_type="pickup_service", natural_key=f"ersu:pickup:{context.istat_code}:pannolini-pannoloni", payload={"municipality_ref": context.municipality_ref, "zone_ref": None, "user_type": "domestic", "accepted_waste_raw": "Pannolini e pannoloni", "booking_methods": [{"method": "phone", "value": "058582711", "hours_raw": None}], "max_items": None, "quantity_limit_raw": None, "placement_instructions_raw": "Ritiro aggiuntivo al calendario domestico; per grandi quantita puo essere fornito un bidone dedicato", "booking_required": True}, source=source, evidence_kind="pdf", evidence_selector="page:25", evidence_quote="servizio aggiuntivo di ritiro a domicilio"))
    return records


def extract_esa_bundle(
    context: MunicipalityContext,
    retrieved_at: datetime,
    pages: list[tuple[str, str | bytes]],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    records: list[dict[str, Any]] = []
    warnings: list[dict[str, str]] = []
    for url, html in pages:
        if isinstance(html, bytes):
            continue
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
    facility_records, facility_warnings = _extract_esa_facility_bundle(
        context, retrieved_at, pages
    )
    records.extend(facility_records)
    warnings.extend(facility_warnings)
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


def _intervals(weekdays: tuple[int, ...], *hours: tuple[str, str]) -> list[dict[str, Any]]:
    return [
        {"weekday": weekday, "opens": opens, "closes": closes}
        for weekday in weekdays for opens, closes in hours
    ]


ESA_FACILITIES: dict[str, dict[str, Any]] = {
    "centro-di-raccolta-portoferraio": {
        "municipality": "Portoferraio", "name": "CDR Portoferraio, Loc. Casaccia",
        "address": "Loc. Casaccia, in prossimità di via del Carburo, Portoferraio",
        "sign": "PORTOFERRAIO.jpeg", "acceptance": "full", "non_domestic": True,
        "periods": [
            ("Tutto l'anno", None, None, _intervals((1, 3, 5), ("07:00", "12:00")) + _intervals((2, 4, 6), ("07:00", "12:00"), ("13:00", "18:00")), "Esclusi i giorni festivi, anche infrasettimanali"),
            ("Periodo estivo - utenze domestiche", "06-15", "09-15", _intervals((7,), ("09:00", "12:00")), "Solo utenze domestiche; esclusi i giorni festivi"),
            ("Tutto l'anno - utenze non domestiche", None, None, _intervals((1, 3, 5), ("13:00", "18:00")), "Solo utenze non domestiche; esclusi i giorni festivi"),
        ],
    },
    "centro-di-raccolta-di-campo-nellelba": {
        "municipality": "Campo nell'Elba", "name": "CDR Campo dell'Elba Loc. Vallone",
        "address": "Ecocentro del Vallone, Campo nell'Elba", "sign": "CAMPO-NELLELBA.jpeg", "acceptance": "full",
        "periods": [("Tutto l'anno", None, None, _intervals((1, 2, 3, 4, 5, 6), ("07:30", "12:30")), None)],
    },
    "centro-di-raccolta-mobile-a-lacona-capoliveri": {
        "municipality": "Capoliveri", "name": "CDR Mobile a Lacona (Capoliveri) solo per le Utenze domestiche",
        "address": "Isola ecologica di Lacona, Capoliveri", "facility_type": "temporary_area", "domestic_only": True,
        "periods": [
            ("Periodo estivo", "04-01", "09-30", _intervals((2, 5), ("09:30", "10:00")), None),
            ("Periodo invernale", "10-01", "03-31", _intervals((5,), ("09:30", "10:00")), None),
        ],
        "generic_acceptance": ("Rifiuti ingombranti", "Apparecchiature elettriche ed elettroniche"),
    },
    "centro-di-raccolta-capoliveri": {
        "municipality": "Capoliveri", "name": "CDR Capoliveri Loc. Spernaino/Vigne Vecchie",
        "address": "Loc. Spernaino/Vigne Vecchie s.n.c., Capoliveri", "sign": "CAPOLIVERI.jpeg", "acceptance": "full",
        "periods": [
            ("Periodo estivo", "05-16", "09-15", _intervals((1, 2, 3, 4, 5, 6, 7), ("08:00", "12:00"), ("17:00", "19:00")), None),
            ("Periodo invernale", "09-16", "05-15", _intervals((1, 2, 3, 4, 6), ("09:00", "12:00"), ("15:00", "17:00")), None),
        ],
    },
    "centro-di-raccolta-porto-azzurro": {
        "municipality": "Porto Azzurro", "name": "CDR Porto Azzurro, Loc. Bocchetto",
        "address": "Loc. Bocchetto, Porto Azzurro", "sign": "PORTO-AZZURRO.jpeg", "acceptance": "minimal",
        "periods": [("Tutto l'anno", None, None, _intervals((1, 3, 6), ("08:00", "12:00")), None)],
    },
    "centro-di-raccolta-mobile-a-cavo-rio": {
        "municipality": "Rio", "name": "CDR Mobile a Cavo (Rio)", "address": "Parcheggio Solana, Cavo (Rio)",
        "facility_type": "temporary_area", "non_domestic": True,
        "periods": [("Tutto l'anno", None, None, [], "Sosta ogni martedì e giovedì alle ore 10:00; la fonte non indica la durata")],
        "generic_acceptance": ("Rifiuti ingombranti", "Apparecchiature elettriche ed elettroniche"),
    },
    "centro-di-raccolta-rio": {
        "municipality": "Rio", "name": "CDR Rio, Loc. Serrantone", "address": "Loc. Serrantone s.n.c., Rio Marina",
        "sign": "RIO.jpeg", "acceptance": "full",
        "periods": [
            ("Periodo estivo", "05-01", "09-30", _intervals((1, 2, 3, 4), ("07:30", "12:30")) + _intervals((6,), ("07:00", "12:00"), ("13:00", "18:00")), None),
            ("Periodo invernale", "10-01", "04-30", _intervals((1, 2, 3, 4), ("07:30", "12:30")) + _intervals((6,), ("13:00", "18:00")), None),
        ],
    },
    "centro-di-raccolta-marciana-loc-san-rocco-marciana": {
        "municipality": "Marciana", "name": "CDR Marciana Loc. San Rocco", "address": "Loc. San Rocco, Marciana",
        "sign": "MARCIANA-SAN-ROCCO.jpeg", "acceptance": "minimal",
        "periods": [
            ("Periodo estivo", "06-15", "09-30", _intervals((1, 3, 5), ("07:30", "10:00")) + _intervals((2, 4, 7), ("10:45", "12:45")) + _intervals((6,), ("08:00", "12:00")), None),
            ("Periodo invernale", "10-01", "06-14", _intervals((2, 3, 5), ("07:30", "12:00")), None),
        ],
    },
    "centro-di-raccolta-marciana": {
        "municipality": "Marciana", "name": "CDR Marciana Loc. Literno (Colle di Procchio)", "address": "Loc. Literno, Colle di Procchio (Marciana)",
        "sign": "MARCIANA.jpeg", "acceptance": "full",
        "periods": [
            ("Periodo estivo", "06-15", "09-30", _intervals((1, 3, 5), ("10:45", "12:45")) + _intervals((2, 4, 7), ("07:30", "10:00")) + _intervals((6,), ("08:00", "12:30")), None),
            ("Periodo invernale", "10-01", "06-14", _intervals((1, 4, 6), ("07:30", "12:00")), None),
        ],
    },
    "centro-di-raccolta-marciana-marina": {
        "municipality": "Marciana Marina", "name": "CDR Marciana Marina, Viale Aldo Moro, 41",
        "address": "Viale Aldo Moro 41, accanto al deposito comunale, Marciana Marina",
        "periods": [
            ("Periodo estivo", "06-01", "09-30", _intervals((1, 2, 3, 4, 5, 6, 7), ("09:00", "12:00")), "Esclusi i giorni festivi, anche infrasettimanali"),
            ("Periodo invernale", "10-01", "05-31", _intervals((1, 2, 3, 4, 5, 6), ("09:00", "12:00")), "Esclusi i giorni festivi, anche infrasettimanali"),
        ],
    },
}


ESA_SIGN_HASHES = {
    "CAMPO-NELLELBA.jpeg": "c5b43e6b1e6b867080d014050863c80102b5a6a203f82a1b097c09341443cb28",
    "CAPOLIVERI.jpeg": "7724dc46b8d9a6d731f16d560c9dd52261157625f0bf36308c7018aac69cc15c",
    "MARCIANA-SAN-ROCCO.jpeg": "0d736ad5f987d2348f72eac5e8ab995befc087306442e08cc735dc823cc6524a",
    "MARCIANA.jpeg": "9ef15738b6c2fca2411dd68e5d44b06d5008ad816344ae9002d6f5fd3e0ef76d",
    "PORTO-AZZURRO.jpeg": "3b685152cc28c91b185de6a212cb0456259efd3b97802b8a78aa82ace3f2d7d2",
    "PORTOFERRAIO.jpeg": "b0ec8d3e090a0cdbf8aa86b48e50b7431da5b7d2fbaa1fcf9db9bca95423f7c8",
    "RIO.jpeg": "08551731417f46cecea90b292bc562c4b9a0f979df32004ee2d89b8391d48216",
}


ESA_FULL_ACCEPTANCE = (
    ("Rifiuti ingombranti", "200307"), ("Rifiuti metallici", "200140"),
    ("Rifiuti legnosi", "200138"), ("Rifiuti di carta e cartone", "200101"),
    ("Imballaggi in materiali misti", "150106"), ("Frazione organica umida", "200108"),
    ("Imballaggi di vetro", "150107"),
    ("Contenitori T/FC", "150110*"), ("Contenitori T/FC", "150111*"),
    ("Tubi fluorescenti ed altri rifiuti contenenti mercurio", "200121*"),
    ("Rifiuti di apparecchiature elettriche ed elettroniche (RAEE)", "200123*"),
    ("Rifiuti di apparecchiature elettriche ed elettroniche (RAEE)", "200135*"),
    ("Rifiuti di apparecchiature elettriche ed elettroniche (RAEE)", "200136"),
    ("Oli e grassi commestibili", "200125"), ("Oli minerali esausti", "200126*"),
    ("Toner per stampa esauriti provenienti da utenze domestiche (diversi da 08 03 17*)", "080318"),
    ("Farmaci", "200131*"), ("Farmaci", "200132"), ("Pile e batterie", "200134"),
    ("Batterie e accumulatori al piombo derivanti dalla manutenzione dei veicoli ad uso privato, effettuata in proprio dalle utenze domestiche", "200133*"),
    ("Sfalci e potature", "200201"),
    ("Vernici, inchiostri, adesivi e resine", "200127*"),
    ("Vernici, inchiostri, adesivi e resine", "200128"),
    ("Pneumatici fuori uso (solo se conferiti da utenze domestiche)", "160103"),
    ("Rifiuti misti dell'attività di costruzione e demolizione, diversi da 17 09 01*, 17 09 02* e 17 09 03* (solo da piccoli interventi domestici eseguiti in proprio)", "170904"),
    ("Abiti e prodotti tessili", "200110"), ("Abiti e prodotti tessili", "200111"),
    ("Gas in contenitori a pressione, limitatamente ad estintori ed aerosol ad uso domestico", "160504*"),
    ("Gas in contenitori a pressione, limitatamente ad estintori ed aerosol ad uso domestico", "160505"),
)


ESA_MINIMAL_ACCEPTANCE = (
    ("Rifiuti ingombranti", "200307"), ("Rifiuti metallici", "200140"),
    ("Rifiuti legnosi", "200138"), ("Rifiuti di carta e cartone", "200101"),
    ("Rifiuti di apparecchiature elettriche ed elettroniche (RAEE)", "200136"),
    ("Oli e grassi commestibili", "200125"), ("Sfalci e potature", "200201"),
    ("Pneumatici fuori uso (solo se conferiti da utenze domestiche)", "160103"),
    ("Rifiuti misti dell'attività di costruzione e demolizione, diversi da 17 09 01*, 17 09 02* e 17 09 03* (solo da piccoli interventi domestici eseguiti in proprio)", "170904"),
)


def _extract_esa_facility_bundle(
    context: MunicipalityContext,
    retrieved_at: datetime,
    pages: list[tuple[str, str | bytes]],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    index_page = next(((url, body) for url, body in pages if url.rstrip("/").endswith("centri-di-raccolta") and isinstance(body, str)), None)
    detail_pages = {
        key: (url, body) for key in ESA_FACILITIES for url, body in pages
        if isinstance(body, str) and f"/{key}/" in url
    }
    if not detail_pages:
        if index_page:
            url, html = index_page
            return _extract_esa_facilities(context, SourceDocument(url, retrieved_at, html, publisher="ESA S.p.A.", parser="esa_html", parser_version="0.2.0"), html), []
        return [], []
    signs = {url.rsplit("/", 1)[-1]: (url, body) for url, body in pages if isinstance(body, bytes)}
    records: list[dict[str, Any]] = []
    warnings: list[dict[str, str]] = []
    access_paragraphs = []
    if index_page:
        index_root = parse_html(index_page[1])
        access_paragraphs = [
            clean_text(element.text) for element in index_root.find_all(lambda item: item.tag == "p")
            if any(marker in element.text for marker in ("iscritte a ruolo TARI", "cinque accessi/anno", "autocertificazioni"))
        ]
    access_text = " ".join(access_paragraphs) or None
    for key, definition in ESA_FACILITIES.items():
        if definition["municipality"] != context.name or key not in detail_pages:
            continue
        url, html = detail_pages[key]
        source = SourceDocument(url, retrieved_at, html, publisher="ESA S.p.A.", parser="esa_centre_html", parser_version="0.2.0")
        facility_ref = f"facility:esa:{_slug(definition['name'])}"
        records.append(make_record(
            record_type="facility", natural_key=facility_ref,
            payload={"name": definition["name"], "municipality_ref": context.municipality_ref, "facility_type": definition.get("facility_type", "collection_centre"), "address_raw": definition["address"], "location": None, "phone": "800 688 850", "email": None, "operational_status": "open", "status_raw": None},
            source=source, evidence_selector="main", evidence_quote=clean_text(parse_html(html).text)[-1800:],
        ))
        domestic_requirements = access_text or "Accesso secondo le condizioni pubblicate da ESA per le utenze TARI"
        if definition.get("domestic_only"):
            domestic_requirements += "; servizio dedicato alle utenze domestiche"
        records.append(make_record(
            record_type="facility_access", natural_key=f"facility-access:{context.istat_code}:{facility_ref}:domestic",
            payload={"facility_ref": facility_ref, "municipality_ref": context.municipality_ref, "user_type": "domestic", "allowed": True, "requirements_raw": domestic_requirements, "booking_required": False, "information_urls": [url], "contact_phone": "800 688 850", "contact_email": None},
            source=source, evidence_selector="main", evidence_quote=domestic_requirements,
        ))
        if definition.get("non_domestic"):
            records.append(make_record(
                record_type="facility_access", natural_key=f"facility-access:{context.istat_code}:{facility_ref}:non-domestic",
                payload={"facility_ref": facility_ref, "municipality_ref": context.municipality_ref, "user_type": "non_domestic", "allowed": True, "requirements_raw": "Accesso delle utenze non domestiche negli orari e alle condizioni pubblicate nella pagina ESA", "booking_required": False, "information_urls": [url], "contact_phone": "800 688 850", "contact_email": None},
                source=source, evidence_selector="main", evidence_quote="utenze non domestiche",
            ))
        for label, start, end, intervals, exceptions in definition["periods"]:
            records.append(make_record(
                record_type="opening_period", natural_key=f"{facility_ref}:opening:{_slug(label)}",
                payload={"facility_ref": facility_ref, "period_label": label, "start_month_day": start, "end_month_day": end, "weekly_intervals": intervals, "exceptions_raw": exceptions},
                source=source, evidence_selector="main", evidence_quote=f"{label}: {exceptions or 'orari pubblicati nella pagina'}",
            ))
        sign_name = definition.get("sign")
        if sign_name:
            sign = signs.get(sign_name)
            if not sign:
                warnings.append({"code": "centre_sign_missing", "detail": f"Cartello ufficiale non acquisito: {sign_name}", "url": url})
            else:
                sign_url, body = sign
                sign_source = SourceDocument(sign_url, retrieved_at, body, publisher="ESA S.p.A.", parser="esa_verified_centre_sign", parser_version="0.2.0")
                if sign_source.sha256 != ESA_SIGN_HASHES[sign_name]:
                    warnings.append({"code": "centre_sign_changed", "detail": f"Il cartello {sign_name} è cambiato: codici EER non materializzati automaticamente", "url": sign_url})
                else:
                    acceptance = ESA_FULL_ACCEPTANCE if definition["acceptance"] == "full" else ESA_MINIMAL_ACCEPTANCE
                    records.extend(_esa_acceptance_records(facility_ref, acceptance, sign_source))
        else:
            generic = definition.get("generic_acceptance")
            if generic:
                records.extend(_esa_unmapped_acceptance_records(facility_ref, generic, source))
    return records, warnings


def _esa_acceptance_records(facility_ref: str, entries: tuple[tuple[str, str], ...], source: SourceDocument) -> list[dict[str, Any]]:
    records = []
    for description, raw_code in entries:
        code = raw_code.rstrip("*")
        records.append(make_record(
            record_type="facility_acceptance", natural_key=f"{facility_ref}:eer:{code}:{_slug(description)}",
            payload={"facility_ref": facility_ref, "eer_code_raw": raw_code, "eer_code_normalized": code, "eer_code_status": "exact", "reconciliation_basis": None, "hazardous": raw_code.endswith("*"), "description_raw": description, "operational_group": None, "user_type": "unspecified", "quantity_limit_raw": None, "notes_raw": "Codice trascritto dal cartello ufficiale ESA"},
            source=source, evidence_kind="image", evidence_selector="cartello-centro-di-raccolta", evidence_quote=f"{description}: EER {raw_code}",
        ))
    return records


def _esa_unmapped_acceptance_records(facility_ref: str, descriptions: tuple[str, ...], source: SourceDocument) -> list[dict[str, Any]]:
    return [make_record(
        record_type="facility_acceptance", natural_key=f"{facility_ref}:description:{_slug(description)}",
        payload={"facility_ref": facility_ref, "eer_code_raw": None, "eer_code_normalized": None, "eer_code_status": "unmapped_description", "reconciliation_basis": None, "hazardous": None, "description_raw": description, "operational_group": None, "user_type": "unspecified", "quantity_limit_raw": None, "notes_raw": "La pagina ESA cita il materiale come esempio senza pubblicare il codice EER"},
        source=source, evidence_selector="main", evidence_quote=description,
    ) for description in descriptions]


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
