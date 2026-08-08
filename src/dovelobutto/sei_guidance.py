from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import re
from typing import Any

from .html import clean_text, parse_html
from .records import SourceDocument, make_record


_BULLET_RE = re.compile(r"\s*[•·]\s*")


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
    if heading is None or accepted is None:
        raise ValueError("The SEI guidance page does not expose a stream and accepted materials")
    stream_name = clean_text(heading.text.replace("Raccolta differenziata", "", 1))
    paragraph = accepted.find_first(lambda element: element.tag == "p")
    if not stream_name or paragraph is None:
        raise ValueError("The SEI guidance page contains no usable accepted materials")
    terms = [clean_text(item) for item in _BULLET_RE.split(paragraph.text) if clean_text(item)]
    if not terms:
        raise ValueError("The SEI guidance page contains no accepted materials")

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
        for index, term in enumerate(terms):
            records.append(make_record(
                record_type="waste_lookup",
                natural_key=f"sei-toscana:guidance:{stream_name.casefold()}:{istat_code}:{index}",
                payload={
                    "municipality_ref": f"istat:{istat_code}",
                    "term": term,
                    "destination_raw": stream_name,
                    "resolution_status": "resolved",
                    "instructions_raw": None,
                },
                source=source,
                evidence_selector=".differenziata__conferimenti.si",
                evidence_quote=term,
            ))
    return records, {
        "source_url": source_url,
        "stream_name": stream_name,
        "accepted_terms": len(terms),
        "municipalities": len(municipalities),
        "records": len(records),
    }
