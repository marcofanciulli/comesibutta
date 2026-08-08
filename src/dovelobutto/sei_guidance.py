from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import re
from typing import Any

from .html import clean_text, parse_html
from .records import SourceDocument, make_record


_BULLET_RE = re.compile(r"\s*[•·]\s*")
_EXAMPLE_RE = re.compile(r"\((?:es\.?|ad esempio)\s+([^()]*)\)", re.IGNORECASE)
_SPECIAL_DESTINATIONS = {
    "RAEE": "Centro di raccolta o rivenditore",
    "Olio alimentare esausto": "Punto di raccolta o centro di raccolta",
    "Pile esauste": "Punto di raccolta o centro di raccolta",
    "Farmaci scaduti": "Punto di raccolta in farmacia o centro di raccolta",
}


def _expand_search_terms(source_terms: list[str]) -> list[tuple[str, str]]:
    """Keep source bullets stable, then add searchable examples they contain."""
    expanded = [(term, term) for term in source_terms]
    seen = {term.casefold() for term in source_terms}
    category_terms = []
    for source_term in source_terms:
        for match in _EXAMPLE_RE.finditer(source_term):
            for item in match.group(1).split(","):
                term = clean_text(re.sub(r"\betc\.?$", "", item, flags=re.IGNORECASE))
                term = term.strip(" .;:")
                if not term or term.casefold() in seen:
                    continue
                seen.add(term.casefold())
                expanded.append((term, source_term))
            if match.end() == len(source_term):
                category = clean_text(source_term[:match.start()]).strip(" .;:")
                if category and category.casefold() not in seen:
                    seen.add(category.casefold())
                    category_terms.append((category, source_term))
    expanded.extend(category_terms)
    return expanded


def extract_sei_stream_guidance(
    html: str,
    registry_path: Path,
    source_url: str,
    retrieved_at: datetime,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    root = parse_html(html)
    heading = root.find_first(
        lambda element: element.tag == "h1" and "Raccolta differenziata" in element.text
    )
    accepted = root.find_first(
        lambda element: (
            element.tag == "div"
            and {"differenziata__conferimenti", "si"}.issubset(element.classes)
        )
    )
    if heading is None:
        raise ValueError("The SEI guidance page does not expose a collection stream")
    stream_name = clean_text(heading.text.replace("Raccolta differenziata", "", 1))
    page_body = root.find_first(lambda element: "page-body" in element.classes)
    if not stream_name:
        raise ValueError("The SEI guidance page contains no usable guidance")
    paragraph = accepted.find_first(lambda element: element.tag == "p") if accepted else None
    if paragraph is not None:
        source_terms = [
            clean_text(item) for item in _BULLET_RE.split(paragraph.text)
            if clean_text(item)
        ]
        terms = _expand_search_terms(source_terms)
        evidence_selector = ".differenziata__conferimenti.si"
        instructions = None
    elif stream_name in _SPECIAL_DESTINATIONS and page_body is not None:
        source_terms = [stream_name]
        terms = [(stream_name, stream_name)]
        paragraphs = page_body.find_all(lambda element: element.tag == "p")
        instructions = " ".join(item.text for item in paragraphs if item.text) or None
        evidence_selector = ".page-body"
    else:
        raise ValueError("The SEI guidance page contains no usable accepted materials")
    if not terms:
        raise ValueError("The SEI guidance page contains no accepted materials")
    destination = _SPECIAL_DESTINATIONS.get(stream_name, stream_name)

    municipalities = []
    for line in registry_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        payload = record.get("payload") or {}
        if payload.get("operator_ref") == "sei-toscana":
            municipalities.append(payload)

    source = SourceDocument(
        source_url,
        retrieved_at,
        html,
        parser="sei_toscana_stream_guidance",
        parser_version="0.1.0",
    )
    records = []
    for municipality in municipalities:
        istat_code = municipality["istat_code"]
        for index, (term, evidence_quote) in enumerate(terms):
            records.append(make_record(
                record_type="waste_lookup",
                natural_key=f"sei-toscana:guidance:{stream_name.casefold()}:{istat_code}:{index}",
                payload={
                    "municipality_ref": f"istat:{istat_code}",
                    "term": term,
                    "destination_raw": destination,
                    "resolution_status": "resolved",
                    "instructions_raw": instructions,
                },
                source=source,
                evidence_selector=evidence_selector,
                evidence_quote=evidence_quote,
            ))
    return records, {
        "source_url": source_url,
        "stream_name": stream_name,
        "destination": destination,
        "accepted_terms": len(terms),
        "source_bullets": len(source_terms),
        "municipalities": len(municipalities),
        "records": len(records),
    }
