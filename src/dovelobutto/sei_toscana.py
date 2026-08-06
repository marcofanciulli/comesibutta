from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import re
from typing import Any, Iterable
import unicodedata
from urllib.parse import unquote, urlparse

from .html import Element, clean_text, has_class, parse_html, table_matrix
from .records import SourceDocument, make_record


_TIME_RANGE_RE = re.compile(r"(?P<opens>[0-2][0-9]:[0-5][0-9])\s*-\s*(?P<closes>[0-2][0-9]:[0-5][0-9])")
_COORDINATES_RE = re.compile(r"(?P<lat>4[0-9](?:\.\d+)?)[,%2C]+(?P<lon>1[0-9](?:\.\d+)?)", re.IGNORECASE)
_COLOR_RE = re.compile(r"\b(blu|azzurro|bianco|marrone|giallo|verde|grigio)\b", re.IGNORECASE)
_MAX_ITEMS_RE = re.compile(r"massimo\s+(\d+)\s+pezz", re.IGNORECASE)
_SEASON_RANGE_RE = re.compile(
    r"periodo\s+(?P<start_day>\d{1,2})\s+(?P<start_month>[a-zà]+)\s*[-–]\s*"
    r"(?P<end_day>\d{1,2})\s+(?P<end_month>[a-zà]+)",
    re.IGNORECASE,
)
_ITALIAN_MONTHS = {
    "gennaio": 1,
    "febbraio": 2,
    "marzo": 3,
    "aprile": 4,
    "maggio": 5,
    "giugno": 6,
    "luglio": 7,
    "agosto": 8,
    "settembre": 9,
    "ottobre": 10,
    "novembre": 11,
    "dicembre": 12,
}


@dataclass(frozen=True)
class MunicipalityContext:
    name: str
    istat_code: str
    slug: str

    @property
    def ref(self) -> str:
        return f"istat:{self.istat_code}"

    @property
    def source_prefix(self) -> str:
        return f"sei-toscana:{self.slug}"


class SeiToscanaExtractor:
    def __init__(self, context: MunicipalityContext, retrieved_at: datetime) -> None:
        self.context = context
        self.retrieved_at = retrieved_at
        self.warnings: list[dict[str, str]] = []

    def extract_facilities(self, html: str, url: str) -> list[dict[str, Any]]:
        source = SourceDocument(url, self.retrieved_at, html)
        root = parse_html(html)
        records: list[dict[str, Any]] = []
        sections = root.find_all(has_class("section-cdr"))
        operator_phone = self._operator_phone(root)
        if not sections:
            self._warn(url, "facility_sections_missing", "No section-cdr elements found")
        for section in sections:
            title = self._text_of(section, "section-cdr__title") or "Centro di raccolta"
            intermunicipal = self._intermunicipal_access(section, source)
            if intermunicipal:
                records.append(intermunicipal)
                continue
            address_element = section.find_first(lambda element: element.tag == "address")
            address = address_element.text if address_element else None
            section_id = self._canonical_facility_slug(title)
            facility_ref = f"{self.context.source_prefix}:facility:{section_id}"
            map_link = self._map_link(section)
            location = self._coordinates(map_link) if map_link else None
            operational_status, status_raw = self._facility_status(section)
            records.append(make_record(
                record_type="facility",
                natural_key=facility_ref,
                payload={
                    "name": title,
                    "municipality_ref": self.context.ref,
                    "facility_type": "collection_centre",
                    "address_raw": address,
                    "location": location,
                    "phone": operator_phone,
                    "email": None,
                    "operational_status": operational_status,
                    "status_raw": status_raw,
                },
                source=source,
                evidence_selector=f"section.{next(iter(section.classes), 'section-cdr')}",
                evidence_quote=clean_text(f"{title} {address or ''}"),
            ))
            records.extend(self._extract_opening_periods(section, facility_ref, source))
            records.extend(self._extract_acceptances(section, facility_ref, source))
            records.extend(self._extract_facility_access(root, facility_ref, source))
        return records

    def extract_collection_rules(self, html: str, url: str) -> list[dict[str, Any]]:
        source = SourceDocument(url, self.retrieved_at, html)
        root = parse_html(html)
        records: list[dict[str, Any]] = []
        seen_zone_refs: set[str] = set()
        sections = root.find_all(has_class("section-raccolta"))
        for section in sections:
            title = self._text_of(section, "section-raccolta__title") or "Raccolta"
            method = self._collection_method(title)
            credential = self._credential(section)
            for zone_raw, instructions, note, table in self._collection_segments(section):
                zone_name, valid_from = self._zone_and_start_date(zone_raw)
                zone_slug = self._slug(zone_name) if zone_name else "default"
                zone_ref = f"{self.context.source_prefix}:zone:{zone_slug}"
                validity = {
                    "valid_from": valid_from,
                    "valid_to": None,
                    "inferred": valid_from is None,
                }
                if zone_ref not in seen_zone_refs:
                    seen_zone_refs.add(zone_ref)
                    records.append(make_record(
                        record_type="service_zone",
                        natural_key=zone_ref,
                        payload={
                            "municipality_ref": self.context.ref,
                            "name": zone_name or "Zona comunale predefinita",
                            "scope_type": "locality" if zone_name else "municipality_default",
                            "included_places_raw": zone_raw,
                            "excluded_places_raw": None,
                            "geometry_geojson": None,
                        },
                        source=source,
                        evidence_selector=".section-raccolta__zona" if zone_raw else f"#{section.attrs.get('id', '')}",
                        evidence_quote=zone_raw or title,
                        validity=validity,
                    ))
                headers, rows = table_matrix(table)
                rules, schedules = self._collection_table_records(
                    headers,
                    rows,
                    title,
                    zone_ref,
                    method,
                    credential,
                    instructions,
                    note,
                    validity,
                    source,
                )
                records.extend(rules)
                records.extend(schedules)
        records.extend(self._extract_special_points(root, source))
        records.extend(self._extract_ecosites(root, source))
        return records

    def extract_pickup_service(self, html: str, url: str) -> list[dict[str, Any]]:
        source = SourceDocument(url, self.retrieved_at, html)
        root = parse_html(html)
        main = root.find_first(lambda element: element.tag == "main") or root
        page_text = main.text
        faq = root.find_first(lambda element: element.attrs.get("id") == "faqs")
        faq_text = faq.text if faq else ""
        max_match = _MAX_ITEMS_RE.search(faq_text)
        phone_link = root.find_first(
            lambda element: element.tag == "a" and element.attrs.get("href", "").startswith("tel:")
        )
        phone = phone_link.attrs["href"].removeprefix("tel:") if phone_link else ""
        booking_methods = [{"method": "web", "value": url, "hours_raw": None}]
        if phone:
            booking_block = phone_link.parent.parent if phone_link.parent and phone_link.parent.parent else phone_link
            booking_methods.append({
                "method": "phone",
                "value": phone,
                "hours_raw": booking_block.text,
            })
        natural_key = f"{self.context.source_prefix}:pickup:bulky-waste"
        return [make_record(
            record_type="pickup_service",
            natural_key=natural_key,
            payload={
                "municipality_ref": self.context.ref,
                "zone_ref": None,
                "user_type": "domestic",
                "accepted_waste_raw": "Rifiuti ingombranti",
                "booking_methods": booking_methods,
                "max_items": int(max_match.group(1)) if max_match else None,
                "quantity_limit_raw": max_match.group(0) if max_match else None,
                "placement_instructions_raw": faq_text or page_text,
                "booking_required": True,
            },
            source=source,
            evidence_selector="#faqs",
            evidence_quote=faq_text[:1000] or page_text[:1000],
        )]

    def _extract_opening_periods(
        self, section: Element, facility_ref: str, source: SourceDocument
    ) -> list[dict[str, Any]]:
        records = []
        for index, table in enumerate(section.find_all(has_class("table-cdr"))):
            headers, rows = table_matrix(table)
            caption = table.find_first(lambda element: element.tag == "caption")
            period_label = caption.text if caption else None
            start_month_day, end_month_day = self._season_range(period_label)
            intervals = []
            weekdays = headers[1:]
            for row in rows:
                for weekday_index, cell in enumerate(row[1:]):
                    match = _TIME_RANGE_RE.search(cell)
                    if not match or weekday_index >= len(weekdays):
                        continue
                    intervals.append({
                        "weekday": weekday_index + 1,
                        "opens": match.group("opens"),
                        "closes": match.group("closes"),
                    })
            natural_key = f"{facility_ref}:opening:{index}"
            records.append(make_record(
                record_type="opening_period",
                natural_key=natural_key,
                payload={
                    "facility_ref": facility_ref,
                    "period_label": period_label,
                    "start_month_day": start_month_day,
                    "end_month_day": end_month_day,
                    "weekly_intervals": intervals,
                    "exceptions_raw": None,
                },
                source=source,
                evidence_kind="table",
                evidence_selector="table.table-cdr",
                evidence_quote=clean_text(" | ".join([*headers, *(" / ".join(row) for row in rows)])),
            ))
        return records

    @staticmethod
    def _season_range(period_label: str | None) -> tuple[str | None, str | None]:
        if not period_label:
            return None, None
        match = _SEASON_RANGE_RE.search(period_label)
        if not match:
            return None, None
        start_month = _ITALIAN_MONTHS.get(match.group("start_month").lower())
        end_month = _ITALIAN_MONTHS.get(match.group("end_month").lower())
        if not start_month or not end_month:
            return None, None
        return (
            f"{start_month:02d}-{int(match.group('start_day')):02d}",
            f"{end_month:02d}-{int(match.group('end_day')):02d}",
        )

    def _extract_acceptances(
        self, section: Element, facility_ref: str, source: SourceDocument
    ) -> list[dict[str, Any]]:
        records = []
        tables = section.find_all(has_class("tabellaconferimenti"))
        if not tables:
            prose_records = self._extract_prose_acceptances(section, facility_ref, source)
            if prose_records:
                return prose_records
            self._warn(source.url, "acceptance_table_missing", facility_ref)
        for table in tables:
            _, rows = table_matrix(table)
            for index, row in enumerate(rows):
                if len(row) < 2:
                    continue
                code, description = row[0].replace(" ", ""), row[1]
                records.append(self._acceptance_record(
                    code=code,
                    description=description,
                    index=index,
                    facility_ref=facility_ref,
                    source=source,
                    selector="table.tabellaconferimenti",
                ))
        return records

    def _extract_prose_acceptances(
        self, section: Element, facility_ref: str, source: SourceDocument
    ) -> list[dict[str, Any]]:
        records = []
        pattern = re.compile(
            r"(?P<context>[^.!?]{1,220}?)\(\s*(?:CER|EER)\s*(?P<code>\d{6}\*?)\s*\)",
            re.IGNORECASE,
        )
        for index, match in enumerate(pattern.finditer(section.text)):
            description = clean_text(match.group("context"))
            conferimento = re.search(r"conferimento\s+(?:del(?:la)?|dei|degli|di)\s+(.+)$", description, re.IGNORECASE)
            if conferimento:
                description = conferimento.group(1)
            description = re.sub(r"^solo\s+", "", description, flags=re.IGNORECASE)
            code = match.group("code")
            records.append(self._acceptance_record(
                code=code,
                description=description,
                index=index,
                facility_ref=facility_ref,
                source=source,
                selector="section.section-cdr",
            ))
        return records

    def _acceptance_record(
        self,
        *,
        code: str,
        description: str,
        index: int,
        facility_ref: str,
        source: SourceDocument,
        selector: str,
    ) -> dict[str, Any]:
        normalized_code = code.rstrip("*") if re.fullmatch(r"\d{6}\*?", code) else None
        code_status = "exact"
        confidence = "high"
        if normalized_code is None:
            self._warn(source.url, "invalid_eer_code", code)
            code_status = "malformed"
            confidence = "low"
            if re.fullmatch(r"\d{5}\*?", code):
                raw_digits = code.rstrip("*")
                normalized_code = f"{raw_digits[:2]}0{raw_digits[2:]}"
                code_status = "inferred_candidate"
        operational = None
        match = re.match(r"(RAEE\s+R\d+)", description, re.IGNORECASE)
        if match:
            operational = match.group(1).upper()
        discriminator = self._slug(operational or description[:40])
        natural_key = f"{facility_ref}:eer:{code.rstrip('*')}:{discriminator}:{index}"
        return make_record(
            record_type="facility_acceptance",
            natural_key=natural_key,
            payload={
                "facility_ref": facility_ref,
                "eer_code_raw": code,
                "eer_code_normalized": normalized_code,
                "eer_code_status": code_status,
                "reconciliation_basis": None,
                "hazardous": code.endswith("*"),
                "description_raw": description,
                "operational_group": operational,
                "user_type": "unspecified",
                "quantity_limit_raw": None,
                "notes_raw": None,
            },
            source=source,
            evidence_kind="table" if selector.startswith("table") else "html",
            evidence_selector=selector,
            evidence_quote=f"{code} - {description}",
            confidence=confidence,
        )

    @staticmethod
    def _facility_status(section: Element) -> tuple[str, str | None]:
        status_element = section.find_first(
            lambda element: "alert" in element.classes and "chius" in element.text.lower()
        )
        if status_element:
            return "temporarily_closed", status_element.text
        return "unknown", None

    def _extract_facility_access(
        self, root: Element, facility_ref: str, source: SourceDocument
    ) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        access_section = root.find_first(
            lambda element: element.attrs.get("id") == "cdrUtenzeCommerciali"
        )
        if access_section:
            requirements = clean_text(" ".join(
                paragraph.text for paragraph in access_section.find_all(lambda element: element.tag == "p")
            ))
            links = [
                link.attrs.get("href", "")
                for link in access_section.find_all(lambda element: element.tag == "a")
            ]
            information_urls = [link for link in links if link.startswith("http")]
            email = next((link.removeprefix("mailto:").strip() for link in links if link.startswith("mailto:")), None)
            natural_key = f"{facility_ref}:access:{self.context.istat_code}:non-domestic"
            records.append(make_record(
            record_type="facility_access",
            natural_key=natural_key,
            payload={
                "facility_ref": facility_ref,
                "municipality_ref": self.context.ref,
                "user_type": "non_domestic",
                "allowed": True,
                "requirements_raw": requirements,
                "booking_required": None,
                "information_urls": information_urls,
                "contact_phone": None,
                "contact_email": email,
            },
            source=source,
            evidence_selector="#cdrUtenzeCommerciali",
            evidence_quote=requirements[:1000],
            ))
        instruction_link = root.find_first(
            lambda element: element.tag == "a"
            and "istruzioni per l'accesso al centro" in element.text.lower()
        )
        if instruction_link:
            information_url = instruction_link.attrs.get("href")
            natural_key = f"{facility_ref}:access:{self.context.istat_code}:domestic"
            records.append(make_record(
                record_type="facility_access",
                natural_key=natural_key,
                payload={
                    "facility_ref": facility_ref,
                    "municipality_ref": self.context.ref,
                    "user_type": "domestic",
                    "allowed": True,
                    "requirements_raw": instruction_link.text,
                    "booking_required": None,
                    "information_urls": [information_url] if information_url else [],
                    "contact_phone": None,
                    "contact_email": None,
                },
                source=source,
                evidence_selector="a[href*='Misure-di-sicurezza']",
                evidence_quote=instruction_link.text,
                confidence="medium",
            ))
        return records

    def _collection_table_records(
        self,
        headers: list[str],
        rows: list[list[str]],
        section_title: str,
        zone_ref: str,
        method: str,
        credential: str | None,
        exposure_instructions: str | None,
        note: str | None,
        validity: dict[str, Any],
        source: SourceDocument,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        records: list[dict[str, Any]] = []
        schedules: list[dict[str, Any]] = []
        normalized_headers = [header.lower() for header in headers]
        for index, row in enumerate(rows):
            values = {normalized_headers[i]: value for i, value in enumerate(row) if i < len(normalized_headers)}
            material_label = values.get("tipo di materiale") or values.get("materiale") or row[0]
            stream, equipment = self._split_material_equipment(material_label)
            container = (
                values.get("colore del contenitore")
                or values.get("colore del cassonetto")
                or equipment
            )
            instructions = values.get("modalità di conferimento") or equipment
            specification = values.get("specifica")
            included = self._parenthetical(stream) or specification
            color = self._color(container)
            natural_stream = self._slug(self._without_parenthetical(stream))
            natural_key = f"{zone_ref}:{method}:{natural_stream}:{index}"
            schedule_days = [
                header for header, value in zip(headers[1:], row[1:]) if clean_text(value)
            ] if normalized_headers and normalized_headers[0] == "materiale" else []
            schedule_raw = ", ".join(schedule_days) or None
            records.append(make_record(
                record_type="collection_rule",
                natural_key=natural_key,
                payload={
                    "municipality_ref": self.context.ref,
                    "zone_ref": zone_ref,
                    "user_type": "domestic",
                    "collection_method": method,
                    "stream_name": self._without_parenthetical(stream),
                    "included_materials_raw": included,
                    "container_type": self._container_type(container),
                    "container_color": color,
                    "access_credential": credential,
                    "presentation": {
                        "mode": self._presentation_mode(instructions),
                        "max_volume_l": self._volume(instructions),
                        "instructions_raw": instructions,
                    },
                    "schedule_raw": schedule_raw,
                },
                source=source,
                evidence_kind="table",
                evidence_selector="table.table-raccolta",
                evidence_quote=clean_text(" | ".join(row)),
                validity=validity,
            ))
            if schedule_days:
                events = self._schedule_events(stream, schedule_days, note)
                expose_from, expose_by = self._exposure_times(exposure_instructions)
                schedules.append(make_record(
                    record_type="collection_schedule",
                    natural_key=f"{natural_key}:schedule",
                    payload={
                        "collection_rule_ref": natural_key,
                        "expose_from": expose_from,
                        "expose_by": expose_by,
                        "events": events,
                    },
                    source=source,
                    evidence_kind="table",
                    evidence_selector="table.table-raccolta",
                    evidence_quote=clean_text(" | ".join(filter(None, [*row, exposure_instructions, note]))),
                    validity=validity,
                ))
        return records, schedules

    def _collection_segments(
        self, section: Element
    ) -> list[tuple[str | None, str | None, str | None, Element]]:
        segments: list[tuple[str | None, str | None, str | None, Element]] = []
        zone: str | None = None
        instructions: str | None = None
        children = section.children
        for index, child in enumerate(children):
            if not isinstance(child, Element):
                continue
            if "section-raccolta__zona" in child.classes:
                zone = child.text
                instructions = None
                continue
            if "section-raccolta__istruzioni" in child.classes:
                instructions = child.text
                continue
            if "table-container" not in child.classes:
                continue
            table = child.find_first(has_class("table-raccolta"))
            if not table:
                continue
            note = None
            for following in children[index + 1:]:
                if not isinstance(following, Element):
                    continue
                if "section-raccolta__zona" in following.classes or "table-container" in following.classes:
                    break
                if "note" in following.classes:
                    note = following.text
                    break
            segments.append((zone, instructions, note, table))
        if not segments:
            for table in section.find_all(has_class("table-raccolta")):
                segments.append((zone, instructions, None, table))
        return segments

    def _zone_and_start_date(self, raw: str | None) -> tuple[str | None, str | None]:
        if not raw:
            return None, None
        match = re.search(
            r"calendario\s+attivo\s+dal\s+(\d{1,2})\s+([a-zà]+)\s+(\d{4})",
            raw,
            re.IGNORECASE,
        )
        valid_from = None
        if match and match.group(2).lower() in _ITALIAN_MONTHS:
            valid_from = date(
                int(match.group(3)),
                _ITALIAN_MONTHS[match.group(2).lower()],
                int(match.group(1)),
            ).isoformat()
        name = clean_text(re.split(r"\s*-\s*ATTENZIONE:", raw, maxsplit=1, flags=re.IGNORECASE)[0])
        return name, valid_from

    def _split_material_equipment(self, value: str) -> tuple[str, str | None]:
        cleaned = clean_text(value).replace("*", "")
        stream_names = (
            "Carta e cartone",
            "Indifferenziato",
            "Multimateriale",
            "Organico",
            "Vetro",
            "Pannolini",
        )
        for stream in stream_names:
            if cleaned.lower().startswith(stream.lower()):
                equipment = clean_text(cleaned[len(stream):]) or None
                return stream, equipment
        return cleaned, None

    def _schedule_events(self, stream: str, weekdays: list[str], note: str | None) -> list[dict[str, Any]]:
        dates = self._explicit_dates(note) if "vetro" in stream.lower() else []
        if dates:
            return [{"kind": "date_list", "weekday": None, "dates": dates, "raw": note}]
        weekday_numbers = {
            "lunedì": 1,
            "martedì": 2,
            "mercoledì": 3,
            "giovedì": 4,
            "venerdì": 5,
            "sabato": 6,
            "domenica": 7,
        }
        return [
            {"kind": "weekly", "weekday": weekday_numbers[weekday.lower()], "dates": [], "raw": None}
            for weekday in weekdays
            if weekday.lower() in weekday_numbers
        ]

    def _explicit_dates(self, note: str | None) -> list[str]:
        if not note:
            return []
        year_match = re.search(r"\b(20\d{2})\b", note)
        if not year_match:
            return []
        year = int(year_match.group(1))
        tail = note.split(":", 1)[-1]
        dates: list[str] = []
        for part in tail.split(";"):
            month_match = next((
                (name, number) for name, number in _ITALIAN_MONTHS.items() if name in part.lower()
            ), None)
            if not month_match:
                continue
            _, month = month_match
            for day_text in re.findall(r"\b([0-3]?\d)\b", re.sub(r"20\d{2}", "", part)):
                day = int(day_text)
                if 1 <= day <= 31:
                    dates.append(date(year, month, day).isoformat())
        return dates

    @staticmethod
    def _exposure_times(instructions: str | None) -> tuple[str | None, str | None]:
        if not instructions:
            return None, None
        normalized = instructions.replace(".", ":")
        times = re.findall(r"\b([0-2]?\d:[0-5]\d)\b", normalized)
        padded = [time if len(time) == 5 else f"0{time}" for time in times]
        if "dalle" in normalized.lower() and len(padded) >= 2:
            return padded[0], padded[1]
        return None, padded[-1] if padded else None

    def _extract_special_points(self, root: Element, source: SourceDocument) -> list[dict[str, Any]]:
        records = []
        stream_names = {
            "olio alimentare": "Olio alimentare esausto",
            "medicinali": "Medicinali scaduti",
            "pile": "Pile esauste",
            "piccoli elettrodomestici": "Piccoli RAEE",
            "sfalci e potature": "Sfalci e potature",
        }
        for heading in root.find_all(has_class("section-raccolta__title")):
            lowered = heading.text.lower()
            stream = next((value for key, value in stream_names.items() if key in lowered), None)
            if not stream or not heading.parent:
                continue
            siblings = heading.parent.children
            heading_index = siblings.index(heading)
            list_element = next((
                sibling for sibling in siblings[heading_index + 1:]
                if isinstance(sibling, Element) and sibling.tag == "ul"
            ), None)
            if not list_element:
                continue
            list_items = list_element.find_all(lambda element: element.tag == "li")
            raw = "\n".join(item.text_with_breaks for item in list_items) or list_element.text_with_breaks
            locations = self._location_fragments(raw)
            if stream == "Sfalci e potature":
                locations = self._temporary_green_area(raw)
            for index, location in enumerate(locations):
                natural_key = f"{self.context.source_prefix}:point:{self._slug(stream)}:{index}:{self._slug(location)}"
                records.append(make_record(
                    record_type="collection_point",
                    natural_key=natural_key,
                    payload={
                        "municipality_ref": self.context.ref,
                        "zone_ref": None,
                        "name": None,
                        "point_type": "temporary" if stream == "Sfalci e potature" else "special",
                        "accepted_streams": [stream],
                        "address_raw": location,
                        "location": None,
                        "access_notes_raw": raw,
                        "access_credential": None,
                        "opening_hours_raw": self._opening_hours_phrase(raw),
                    },
                    source=source,
                    evidence_selector=f"#{heading.parent.attrs.get('id', 'sec_altre-raccolte')}",
                    evidence_quote=raw,
                    confidence="medium",
                ))
        return records

    def _extract_ecosites(self, root: Element, source: SourceDocument) -> list[dict[str, Any]]:
        records = []
        for heading in root.find_all(has_class("section-raccolta__title")):
            if "altre metodologie di raccolta" not in heading.text.lower() or not heading.parent:
                continue
            siblings = heading.parent.children
            index = siblings.index(heading)
            list_element = next((
                sibling for sibling in siblings[index + 1:]
                if isinstance(sibling, Element) and sibling.tag == "ul"
            ), None)
            if not list_element:
                continue
            paragraphs = list_element.find_all(lambda element: element.tag == "p")
            access_notes = next((p.text for p in paragraphs if "accesso" in p.text.lower()), None)
            for point_index, paragraph in enumerate(paragraphs):
                if not paragraph.text.lower().startswith("ecosito"):
                    continue
                match = re.match(r"Ecosito\s*-\s*(.+?),\s*aperto\s+(.+)", paragraph.text, re.IGNORECASE)
                address = match.group(1) if match else paragraph.text
                hours = match.group(2) if match else None
                natural_key = f"{self.context.source_prefix}:point:ecosito:{self._slug(address)}"
                records.append(make_record(
                    record_type="collection_point",
                    natural_key=natural_key,
                    payload={
                        "municipality_ref": self.context.ref,
                        "zone_ref": None,
                        "name": "Ecosito",
                        "point_type": "container_station",
                        "accepted_streams": [
                            "Raccolta differenziata",
                            "Indifferenziato",
                            "Pile esauste",
                            "Medicinali scaduti",
                            "Piccoli RAEE",
                            "Olio alimentare esausto",
                        ],
                        "address_raw": address,
                        "location": None,
                        "access_notes_raw": access_notes,
                        "access_credential": "6Card" if access_notes and "card" in access_notes.lower() else None,
                        "opening_hours_raw": hours,
                    },
                    source=source,
                    evidence_selector="#sec_altre-raccolte",
                    evidence_quote=clean_text(f"{paragraph.text} {access_notes or ''}"),
                    confidence="medium",
                ))
        return records

    def _location_fragments(self, text: str) -> list[str]:
        markers = ["si trova presso:", "si trovano presso:", "si trovano:", "si trovano a:", "posizionati presso:"]
        lowered = text.lower()
        start = -1
        marker_length = 0
        for marker in markers:
            position = lowered.find(marker)
            if position >= 0:
                start, marker_length = position, len(marker)
                break
        location_text = text[start + marker_length:] if start >= 0 else text
        location_text = location_text.rstrip(" .")
        parts = [
            clean_text(part).removeprefix("- ")
            for part in re.split(r";|\n", location_text)
            if clean_text(part).removeprefix("- ")
        ]
        expanded: list[str] = []
        for part in parts:
            match = re.match(r"presso le isole ecologiche di (.+)", part, re.IGNORECASE)
            if match:
                names = [clean_text(name) for name in re.split(r",|\se\s", match.group(1)) if clean_text(name)]
                expanded.extend(f"Isola ecologica di {name}" for name in names)
            else:
                expanded.append(part)
        return expanded or [text]

    @staticmethod
    def _temporary_green_area(text: str) -> list[str]:
        match = re.search(
            r"area di raccolta temporanea in ([^,]+),\s*a ([^,]+)",
            text,
            re.IGNORECASE,
        )
        return [clean_text(f"{match.group(1)}, {match.group(2)}")] if match else []

    @staticmethod
    def _opening_hours_phrase(text: str) -> str | None:
        match = re.search(r"apert[ao]\s+(.+?)(?:\.|$)", text, re.IGNORECASE)
        return clean_text(match.group(1)) if match else None

    def _intermunicipal_access(
        self, section: Element, source: SourceDocument
    ) -> dict[str, Any] | None:
        if "autorizzati a conferire" not in section.text.lower():
            return None
        link = section.find_first(
            lambda element: element.tag == "a"
            and re.search(r"/comuni/[^/]+/centr[oi]", element.attrs.get("href", "")) is not None
        )
        if not link:
            return None
        href = link.attrs.get("href", "")
        owner_match = re.search(r"/comuni/([^/]+)/", href)
        if not owner_match:
            return None
        owner_slug = owner_match.group(1)
        target_name = link.text
        target_ref = f"sei-toscana:{owner_slug}:facility:{self._canonical_facility_slug(target_name)}"
        requirements = section.text
        natural_key = f"{target_ref}:access:{self.context.istat_code}:domestic"
        return make_record(
            record_type="facility_access",
            natural_key=natural_key,
            payload={
                "facility_ref": target_ref,
                "municipality_ref": self.context.ref,
                "user_type": "domestic",
                "allowed": True,
                "requirements_raw": requirements,
                "booking_required": None,
                "information_urls": [href],
                "contact_phone": None,
                "contact_email": None,
            },
            source=source,
            evidence_selector="section.section-cdr",
            evidence_quote=requirements[:1000],
        )

    def _map_link(self, section: Element) -> str | None:
        link = section.find_first(lambda element: element.tag == "a" and (
            "maps." in element.attrs.get("href", "") or element.text.lower() == "mappa"
        ))
        return link.attrs.get("href") if link else None

    @staticmethod
    def _operator_phone(root: Element) -> str | None:
        link = root.find_first(
            lambda element: element.tag == "a" and element.attrs.get("href", "").startswith("tel:")
        )
        return link.attrs["href"].removeprefix("tel:").strip() if link else None

    def _coordinates(self, url: str) -> dict[str, Any] | None:
        decoded = unquote(url)
        match = _COORDINATES_RE.search(decoded)
        if not match:
            self._warn(url, "map_coordinates_missing", decoded[:200])
            return None
        return {
            "latitude": float(match.group("lat")),
            "longitude": float(match.group("lon")),
            "method": "map_link",
            "accuracy_m": None,
        }

    def _credential(self, section: Element) -> str | None:
        text = section.text.lower()
        if "6card" in text or "tessera" in text:
            if "senza utilizzo della tessera" in text or "non è necessario l'uso della tessera" in text:
                return "not_currently_required"
            return "6Card"
        return None

    @staticmethod
    def _collection_method(title: str) -> str:
        lowered = title.lower()
        if "domiciliare" in lowered or "porta a porta" in lowered:
            return "door_to_door"
        if "stradale" in lowered or "cassonett" in lowered:
            return "street"
        return "other"

    @staticmethod
    def _presentation_mode(instructions: str | None) -> str:
        if not instructions:
            return "unspecified"
        lowered = instructions.lower()
        has_bag = "sacc" in lowered
        if "sfus" in lowered and has_bag:
            return "mixed"
        if "sfus" in lowered:
            return "loose"
        if has_bag and "carta" in lowered:
            return "paper_bag"
        if has_bag and "compostabil" in lowered:
            return "compostable_bag"
        if has_bag and "biodegradabil" in lowered:
            return "biodegradable_bag"
        if has_bag and "plastic" in lowered:
            return "plastic_bag"
        if has_bag and "chius" in lowered:
            return "closed_bag"
        if has_bag:
            return "bag_unspecified"
        if any(container in lowered for container in ("mastello", "bidone", "cassonetto", "contenitore")):
            return "container"
        if "fascin" in lowered:
            return "bundle"
        return "unspecified"

    @staticmethod
    def _volume(instructions: str | None) -> float | None:
        if not instructions:
            return None
        match = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:l|litri)", instructions, re.IGNORECASE)
        return float(match.group(1).replace(",", ".")) if match else None

    @staticmethod
    def _container_type(container: str | None) -> str | None:
        if not container:
            return None
        lowered = container.lower()
        for candidate in ("cassonetto", "contenitore", "bidone", "campana", "mastello", "sacco", "box"):
            if candidate in lowered:
                return candidate
        return container

    @staticmethod
    def _color(container: str | None) -> str | None:
        if not container:
            return None
        match = _COLOR_RE.search(container)
        return match.group(1).lower() if match else None

    @staticmethod
    def _parenthetical(value: str) -> str | None:
        match = re.search(r"\((.+)\)", value)
        return match.group(1) if match else None

    @staticmethod
    def _without_parenthetical(value: str) -> str:
        return clean_text(re.sub(r"\s*\(.+\)\s*", "", value))

    @staticmethod
    def _text_of(parent: Element, class_name: str) -> str | None:
        element = parent.find_first(has_class(class_name))
        return element.text if element else None

    @staticmethod
    def _slug(value: str | None) -> str:
        if not value:
            return "unknown"
        normalized = value.lower()
        translations = str.maketrans("àèéìòù", "aeeiou")
        normalized = normalized.translate(translations)
        return re.sub(r"[^a-z0-9]+", "-", normalized).strip("-") or "unknown"

    def _canonical_facility_slug(self, title: str) -> str:
        normalized = re.sub(r"\bcomune\s+di\b", "", title, flags=re.IGNORECASE)
        return self._slug(normalized)

    def _warn(self, url: str, code: str, detail: str) -> None:
        self.warnings.append({"url": url, "code": code, "detail": detail})


def extract_municipality_bundle(
    *,
    context: MunicipalityContext,
    retrieved_at: datetime,
    pages: Iterable[tuple[str, str]],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    extractor = SeiToscanaExtractor(context, retrieved_at)
    records: list[dict[str, Any]] = []
    for url, html in pages:
        path = urlparse(url).path.rstrip("/")
        if path.endswith("/centro-di-raccolta") or path.endswith("/centri-di-raccolta"):
            records.extend(extractor.extract_facilities(html, url))
        elif path.endswith("/raccolta-rifiuti"):
            records.extend(extractor.extract_collection_rules(html, url))
        elif path.endswith("/ritiro-ingombranti"):
            records.extend(extractor.extract_pickup_service(html, url))
    return records, extractor.warnings


def build_eer_description_reference(
    record_groups: Iterable[Iterable[dict[str, Any]]],
) -> dict[str, set[str]]:
    reference: dict[str, set[str]] = {}
    for records in record_groups:
        for record in records:
            if record["record_type"] != "facility_acceptance":
                continue
            payload = record["payload"]
            if payload.get("eer_code_status") != "exact" or not payload.get("eer_code_normalized"):
                continue
            key = _eer_description_key(payload["description_raw"])
            reference.setdefault(key, set()).add(payload["eer_code_normalized"])
    return reference


def reconcile_eer_records(
    records: list[dict[str, Any]],
    warnings: list[dict[str, str]],
    reference: dict[str, set[str]],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    reconciled_warning_keys: set[tuple[str, str]] = set()
    for record in records:
        if record["record_type"] != "facility_acceptance":
            continue
        payload = record["payload"]
        if payload.get("eer_code_status") != "inferred_candidate":
            continue
        matches = reference.get(_eer_description_key(payload["description_raw"]), set())
        if matches == {payload.get("eer_code_normalized")}:
            payload["eer_code_status"] = "reconciled"
            payload["reconciliation_basis"] = "unique_batch_description_match"
            record["confidence"] = "high"
            reconciled_warning_keys.add((record["source"]["url"], payload["eer_code_raw"]))
    remaining_warnings = [
        warning for warning in warnings
        if not (
            warning["code"] == "invalid_eer_code"
            and (warning["url"], warning["detail"]) in reconciled_warning_keys
        )
    ]
    return records, remaining_warnings


def _eer_description_key(value: str) -> str:
    without_details = re.sub(r"\([^)]*\)", "", value)
    normalized = unicodedata.normalize("NFKD", without_details)
    ascii_value = "".join(character for character in normalized if not unicodedata.combining(character))
    return re.sub(r"[^a-z0-9]+", " ", ascii_value.lower()).strip()
